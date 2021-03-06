#!/usr/bin/env python
# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import fcntl
import os
import platform
import select
import signal
import socket
import subprocess
import sys
import time


def is_kvm_supported(arch):
  return (sys.platform.startswith('linux') and
          platform.machine() == arch and
          os.path.exists('/dev/kvm'))


def stop_qemu():
  try:
    pid = int(open('qemu.pid').read())
  except IOError:
    # If shutdown already happened, qemu.pid will have been cleaned up.
    return

  os.kill(pid, signal.SIGTERM)

  while True:
    time.sleep(0.5)
    try:
      os.kill(pid, 0)
    except OSError:  # process completed
      break


def main():
  main_parser = argparse.ArgumentParser(description='QEMU')
  subparsers = main_parser.add_subparsers(dest='command')
  run_parser = subparsers.add_parser('run',
      description='run QEMU in the foreground')
  start_parser = subparsers.add_parser('start',
      description='start QEMU in the background')
  stop_parser = subparsers.add_parser('stop',
      description='stop the background QEMU process')

  for parser in run_parser, start_parser:
    parser.add_argument('--memory', type=int, default=2048)
    parser.add_argument('--smp', type=int, default=4)
    parser.add_argument('--arch', type=str, required=True)
    parser.add_argument('--kvm', dest='kvm', action='store_true', default=True)
    parser.add_argument('--no-kvm', dest='kvm', action='store_false')
    parser.add_argument('--initrd', type=str, default=None)
    parser.add_argument('--cmdline', type=str, default=None)
    parser.add_argument('--executable', type=str, required=True)
    parser.add_argument('--netdev', type=str, default=None)
    parser.add_argument('--device', type=str, action='append', default=[])
    parser.add_argument('kernel', type=str, default=None)

  stop_parser.add_argument('--log', dest='log', action='store_true',
      default=False)
  stop_parser.add_argument('--no-log', dest='log', action='store_false')

  args = main_parser.parse_args()

  if args.command == 'stop':
    try:
      stop_qemu()
    finally:
      if args.log:
        sys.stdout.write(open('qemu.stdout').read())
    return 0

  cmd = [
    args.executable,
    '-m', str(args.memory),
    '-smp', str(args.smp),
    '-nographic',
    '-machine', {'aarch64': 'virt', 'x86_64': 'q35'}[args.arch],
    '-kernel', args.kernel,
  ]
  if args.kvm and is_kvm_supported(args.arch):
    cmd.extend(['-enable-kvm', '-cpu', 'host'])
  else:
    cmd.extend({
      'aarch64': ['-cpu', 'cortex-a53'],
      'x86_64': ['-cpu', 'Haswell,+smap,-check'],
    }[args.arch])
  if args.initrd:
    cmd.extend(['-initrd', args.initrd])
  if args.cmdline:
    cmd.extend(['-append', args.cmdline])
  if args.netdev:
    cmd.extend(['-netdev', args.netdev])
  for device in args.device:
    cmd.extend(['-device', device])

  print ' '.join(cmd)

  if args.command == 'start':
    daemon = True
    if os.fork() != 0:
      os._exit(0)
    stdout = open('qemu.stdout', 'w')
  else:
    daemon = False
    stdout = sys.stdout

  qemu = subprocess.Popen(cmd, stdout=subprocess.PIPE)
  flags = fcntl.fcntl(qemu.stdout, fcntl.F_GETFL)
  fcntl.fcntl(qemu.stdout, fcntl.F_SETFL, flags | os.O_NONBLOCK)

  if daemon:
    with open('qemu.pid', 'w') as pidfile:
      pidfile.write(str(qemu.pid) + '\n')

  return_code = None

  while True:
    if qemu.poll() is not None:
      break
    if select.select([qemu.stdout], [], [], 60)[0]:
      stdout.write(qemu.stdout.read())
      stdout.flush()
    else:
      return_code = 2
      break

  if qemu.poll() is None:
    qemu.kill()

  if daemon:
    os.remove('qemu.pid')

  if return_code is None:
    return qemu.returncode
  else:
    return return_code


if __name__ == '__main__':
    sys.exit(main())
