#!/usr/bin/env python3
"""Run a validation command with a deadline and terminate its entire process group."""
import argparse
import math
import os
import signal
import subprocess
import sys


def stop(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    # A child can outlive its parent or ignore SIGTERM. Clear the entire group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


class Interrupted(Exception):
    def __init__(self, number):
        self.number = number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=180)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error('Provide a command and a finite positive timeout.')
    process = None
    previous = {}

    def interrupted(number, frame):
        raise Interrupted(number)

    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            previous[number] = signal.signal(number, interrupted)
        process = subprocess.Popen(command, start_new_session=True)
        try:
            result = process.wait(timeout=args.seconds)
            return result if result >= 0 else 128 - result
        except subprocess.TimeoutExpired:
            print(f'Validation failed: command exceeded {args.seconds:g} seconds; terminating its process group.', file=sys.stderr, flush=True)
            # Ignore further cancellation while cleaning up the child group.
            for number in previous:
                signal.signal(number, signal.SIG_IGN)
            stop(process)
            return 124
    except Interrupted as error:
        for number in previous:
            signal.signal(number, signal.SIG_IGN)
        if process is not None:
            stop(process)
        return 128 + error.number
    except OSError as error:
        print(f'Could not run validation command: {error}', file=sys.stderr)
        return 127
    finally:
        if process is not None and process.poll() is None:
            stop(process)
        for number, handler in previous.items():
            signal.signal(number, handler)


if __name__ == '__main__':
    raise SystemExit(main())
