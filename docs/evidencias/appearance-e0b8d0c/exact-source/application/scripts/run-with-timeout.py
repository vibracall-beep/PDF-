#!/usr/bin/env python3
"""Run a validation command with a deadline and terminate its entire process group."""
import argparse
import math
import os
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bundle_lease import inherited_from_environment

# Both checkout scripts/ and bundle Resources/distribution/ have ../engine.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from owned_process import OwnedProcess


def stop(process):
    process.close()


def sample_owned_process(process):
    """Best-effort stack diagnostic for this wrapper's still-running child only.

    macOS sample(1) otherwise writes a default file under /tmp. An explicit
    /dev/stdout destination sends its report directly to the existing CI log.
    No name lookup, process enumeration, TCC change or permission request occurs.
    """
    if sys.platform != 'darwin' or process.exited():
        return
    print(f'Sampling the owned validation process {process.pid} for 3 seconds before cleanup.',
          file=sys.stderr, flush=True)
    try:
        result = subprocess.run(
            ['/usr/bin/sample', str(process.pid), '3', '-mayDie', '-file', '/dev/stdout'],
            stdin=subprocess.DEVNULL, stdout=None, stderr=None,
            timeout=12, check=False,
        )
        if result.returncode:
            print(f'Stack sampling returned {result.returncode}; the original timeout remains a failure.',
                  file=sys.stderr, flush=True)
    except (OSError, subprocess.SubprocessError) as error:
        print(f'Stack sampling unavailable ({type(error).__name__}); the original timeout remains a failure.',
              file=sys.stderr, flush=True)


class Interrupted(Exception):
    def __init__(self, number):
        self.number = number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=180)
    parser.add_argument('--sample-on-timeout', action='store_true',
                        help='On macOS only, sample this command process for 3 seconds before timeout cleanup.')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error('Provide a command and a finite positive timeout.')
    process = None
    primary_error = None
    previous = {}

    def interrupted(number, frame):
        raise Interrupted(number)

    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            previous[number] = signal.signal(number, interrupted)
        process = OwnedProcess(command, pass_fds=inherited_from_environment(), grace_seconds=10)
        def before_timeout(child):
            print(f'Validation failed: command exceeded {args.seconds:g} seconds; terminating its process group.', file=sys.stderr, flush=True)
            for number in previous:
                signal.signal(number, signal.SIG_IGN)
            try:
                if args.sample_on_timeout:
                    sample_owned_process(child)
            except Exception as error:
                print(f'Stack diagnostic failed ({type(error).__name__}); continuing timeout cleanup.',
                      file=sys.stderr, flush=True)
        try:
            result = process.wait(args.seconds, before_timeout=before_timeout)
            return result if result >= 0 else 128 - result
        except subprocess.TimeoutExpired as error:
            primary_error = error
            return 124
    except Interrupted as error:
        primary_error = error
        for number in previous:
            signal.signal(number, signal.SIG_IGN)
        return 128 + error.number
    except (OSError, ValueError) as error:
        primary_error = error
        print(f'Could not run validation command: {error}', file=sys.stderr)
        return 127
    finally:
        try:
            if process is not None:
                try:
                    stop(process)
                except BaseException as cleanup:
                    if primary_error is None:
                        raise
                    primary_error.add_note("Owned process cleanup failed: " + type(cleanup).__name__)
            if primary_error is not None:
                for note in getattr(primary_error, "__notes__", []):
                    print(note, file=sys.stderr)
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)



if __name__ == '__main__':
    raise SystemExit(main())
