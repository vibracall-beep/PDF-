"""Own a process group until its final signal, then collect its leader exactly once.

A Popen wait/poll/communicate must not be used before group cleanup: collecting
its leader releases the PID which pins our PGID. Exit observation instead uses
waitid(WNOWAIT) or Darwin kqueue. Callers receive bytes and the actual exit status
only after cleanup; inherited lease descriptors retain their usual ownership.
"""
from __future__ import annotations

import contextlib
import errno
import json
import os
from pathlib import Path
import select
import selectors
import signal
import stat
import subprocess
import sys
import time


class ProcessInterrupted(BaseException):
    """An explicit CLI cancellation, kept separate from recoverable failures."""
    def __init__(self, number):
        super().__init__('Interrupted by signal ' + str(number))
        self.number = number


@contextlib.contextmanager
def cooperative_signals():
    """Install only at a CLI boundary that does not own its own signal policy.

    Imports have no side effects. The first INT/TERM unwinds normal finally
    blocks; repeated signals cannot interrupt child cleanup. Restore exactly
    the prior handlers even when installation or the operation fails.
    """
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(number, _frame):
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, signal.SIG_IGN)
        raise ProcessInterrupted(number)
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(number, interrupted)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


class ExitObservation:
    @staticmethod
    def supported():
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise RuntimeError('A custom SIGCHLD handler could collect the owned child.')
        if all(hasattr(os, name) for name in ('waitid', 'WNOWAIT', 'P_PID', 'WEXITED', 'WNOHANG')):
            return 'waitid'
        if sys.platform == 'darwin' and all(hasattr(select, name) for name in
                ('kqueue', 'kevent', 'KQ_FILTER_PROC', 'KQ_NOTE_EXIT', 'KQ_EV_ADD', 'KQ_EV_ONESHOT')):
            return 'kqueue'
        raise RuntimeError('Non-reaping child exit observation is unavailable.')

    def __init__(self, pid):
        backend = self.supported()
        self.pid, self.queue, self.observed = pid, None, False
        if backend == 'kqueue':
            self.queue = select.kqueue()
            event = select.kevent(pid, filter=select.KQ_FILTER_PROC,
                                 flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT)
            try:
                self.queue.control([event], 0, 0)
            except OSError as error:
                if error.errno != errno.ESRCH:
                    self.queue.close(); self.queue = None
                    raise
                # No wait/poll or SIGCHLD reaper has released this short-lived
                # child; ESRCH when registering NOTE_EXIT means it already exited.
                self.observed = True

    def exited(self):
        if not self.observed:
            if self.queue is None:
                result = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                self.observed = result is not None and result.si_pid == self.pid
            else:
                self.observed = bool(self.queue.control([], 1, 0))
        return self.observed

    def close(self):
        if self.queue is not None:
            self.queue.close(); self.queue = None


def _group_snapshot_helper():
    """Only fixed bundle/build locations; never PATH or an environment override."""
    root = Path(__file__).resolve().parent.parent
    bundled = root.name == 'Resources' and root.parent.name == 'Contents'
    helper = root / ('runtime/bin/pdf-process-group-check' if bundled else '.build/pdf-process-group-check')
    try:
        info = helper.lstat()
    except FileNotFoundError:
        if (not bundled and (root / 'Package.swift').is_file()
                and (root / 'scripts/ProcessGroupSnapshot.c').is_file()):
            # A source checkout outside the portable sandbox can still use the
            # existing system ps. A bundle must always carry its signed helper.
            return None
        raise RuntimeError('The native process-group witness is missing.') from None
    if (not stat.S_ISREG(info.st_mode) or info.st_mode & (stat.S_ISUID | stat.S_ISGID | 0o022)
            or info.st_uid not in (0, os.geteuid()) or not os.access(helper, os.X_OK)):
        raise RuntimeError('The native process-group witness is not a regular unprivileged executable.')
    return helper


def _validate_group_snapshot(data, leader):
    if not isinstance(data, bytes) or len(data) > 1024 * 1024:
        raise RuntimeError('The native process-group snapshot exceeds its limit.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate process-group snapshot key.')
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=unique)
    keys = {'schemaVersion', 'pgid', 'zombieState', 'libprocComplete', 'sysctlComplete',
            'stable', 'leaderPresent', 'allZombies', 'members'}
    if (not isinstance(value, dict) or set(value) != keys
            or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
            or type(value['pgid']) is not int or value['pgid'] != leader
            or type(value['zombieState']) is not int or value['zombieState'] != 5
            or any(value[key] is not True for key in ('libprocComplete', 'sysctlComplete', 'stable', 'leaderPresent'))
            or type(value['allZombies']) is not bool or not isinstance(value['members'], list)
            or not 1 <= len(value['members']) <= 4096):
        raise RuntimeError('The native process-group snapshot is incomplete or inconsistent.')
    members = {}
    for item in value['members']:
        if (not isinstance(item, dict) or set(item) != {'pid', 'pgid', 'status'}
                or any(type(item[key]) is not int for key in ('pid', 'pgid', 'status'))
                or not 0 < item['pid'] <= 2147483647 or item['pgid'] != leader
                or not 1 <= item['status'] <= 5 or item['pid'] in members):
            raise RuntimeError('The native process-group snapshot contains an invalid member.')
        members[item['pid']] = item['status']
    zombies = all(state == 5 for state in members.values())
    if leader not in members or value['allZombies'] is not zombies:
        raise RuntimeError('The native process-group snapshot lacks its leader or contradicts its members.')
    return zombies


def group_has_only_zombies(leader):
    if type(leader) is not int or not 0 < leader <= 2147483647:
        raise ValueError('A positive owned process-group ID is required.')
    if sys.platform == 'darwin':
        helper = _group_snapshot_helper()
        if helper is not None:
            # This fixed read-only helper neither forks nor signals. Its direct
            # child is collected by run(); the owned group leader is untouched.
            result = subprocess.run([str(helper), str(leader)], capture_output=True,
                                    check=True, timeout=5, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
            if result.stderr or len(result.stdout) > 1024 * 1024:
                raise RuntimeError('The native process-group witness returned invalid output.')
            return _validate_group_snapshot(result.stdout, leader)
    # Same conservative XNU EPERM policy as the reviewed Office diagnostic.
    # This runs while the unreaped leader pins the group. It never signals a
    # PID learned from ps, and absence/partial output is not proof of death.
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,pgid=,stat='],
                            capture_output=True, text=True, check=True, timeout=5,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if len(result.stdout) > 1024 * 1024:
        raise RuntimeError('The process-group snapshot exceeds its limit.')
    group = {}
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) != 3:
            raise RuntimeError('The process-group snapshot is incomplete.')
        pid, pgid = int(columns[0]), int(columns[1])
        if pgid == leader:
            if pid in group:
                raise RuntimeError('The process-group snapshot contains duplicate members.')
            group[pid] = columns[2]
    return leader in group and all(state.startswith('Z') for state in group.values())


def signal_owned_group(process, observation, signum):
    if process.returncode is not None:
        raise RuntimeError('The owned leader was already collected; refusing to signal its old group.')
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        if sys.platform == 'darwin' and error.errno == errno.EPERM and observation is not None:
            try:
                if observation.exited() and group_has_only_zombies(process.pid):
                    return
            except Exception as proof_error:
                error.add_note('Could not prove the owned group is dead: ' + type(proof_error).__name__)
        raise


@contextlib.contextmanager
def _defer_cancellation():
    # A second SIGINT/SIGTERM must not interrupt the first cancellation's kill
    # and reap. Unmasking delivers a pending signal after ownership is released.
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


class OutputLimitExceeded(RuntimeError):
    def __init__(self, stdout, stderr):
        super().__init__('The child exceeded its output limit.')
        self.stdout, self.stderr = stdout, stderr


class OwnedProcess:
    """Synchronous owner; do not call poll/wait/communicate on .process yourself."""
    def __init__(self, arguments, *, grace_seconds=3, **kwargs):
        ExitObservation.supported()  # Refuse unsupported ownership before spawn.
        if kwargs.get('text') or kwargs.get('encoding') or kwargs.get('universal_newlines'):
            raise ValueError('OwnedProcess captures bytes; decode only after cleanup.')
        if 'start_new_session' in kwargs:
            raise ValueError('OwnedProcess controls its own process group.')
        self.arguments = arguments
        self.grace_seconds = grace_seconds
        self.observation = None
        self.closed = False
        self.signals_finished = False
        self.cleanup_confirmed = False
        self._cleanup_failed = False
        self.process = subprocess.Popen(arguments, start_new_session=True, **kwargs)
        try:
            self.observation = ExitObservation(self.process.pid)
        except BaseException as error:
            self._finish(error)
            raise

    @property
    def pid(self):
        return self.process.pid

    @property
    def returncode(self):
        return self.process.returncode

    def exited(self):
        if self.closed:
            return self.returncode is not None
        return self.observation.exited()

    def _finish(self, original=None, *, close_streams=True):
        try:
            self.close(close_streams=close_streams)
        except BaseException as cleanup:
            if original is None:
                raise
            original.add_note('Owned process cleanup failed: ' + type(cleanup).__name__ + ': ' + str(cleanup))

    def close(self, *, close_streams=True):
        if self.closed:
            if close_streams:
                try:
                    self._close_streams()
                except BaseException:
                    self.cleanup_confirmed = False
                    self._cleanup_failed = True
                    raise
            return
        failure = None
        try:
            with _defer_cancellation():
                if not self.signals_finished:
                    try:
                        signal_owned_group(self.process, self.observation, signal.SIGTERM)
                        deadline = time.monotonic() + self.grace_seconds
                        while self.observation is not None and not self.observation.exited() and time.monotonic() < deadline:
                            time.sleep(0.02)
                    except BaseException as error:
                        failure = error
                    finally:
                        try:
                            signal_owned_group(self.process, self.observation, signal.SIGKILL)
                        except BaseException as error:
                            if failure is None: failure = error
                            else: failure.add_note('Group kill also failed: ' + type(error).__name__)
                        self.signals_finished = True
                try:
                    self.process.wait(timeout=5)
                except BaseException as error:
                    if failure is None: failure = error
                    else: failure.add_note('Leader collection also failed: ' + type(error).__name__)
                # A failed/timed-out wait has not collected the child. A later
                # close may retry collection, but must never signal again.
                self.closed = self.process.returncode is not None
        except BaseException:
            self._cleanup_failed = True
            raise
        finally:
            try:
                if self.closed and self.observation is not None:
                    self.observation.close()
                if close_streams:
                    self._close_streams()
            except BaseException:
                self._cleanup_failed = True
                raise
        if failure is not None:
            self._cleanup_failed = True
            raise failure
        # A prior signal/collection error cannot be relabeled as proof merely
        # because a later close finally reaped the leader. Supervisors may use
        # this receipt to decide whether an IPC namespace can be removed.
        self.cleanup_confirmed = self.closed and not self._cleanup_failed

    def _close_streams(self):
        # Popen creates these handles only for PIPE. Caller-owned files and
        # pass_fds/lease handles are not exposed here and remain caller-owned.
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()

    def wait(self, timeout, *, before_timeout=None):
        error = None
        try:
            deadline = time.monotonic() + timeout
            while not self.exited():
                if time.monotonic() >= deadline:
                    if before_timeout is not None:
                        before_timeout(self)
                    raise subprocess.TimeoutExpired(self.arguments, timeout)
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        except BaseException as caught:
            error = caught
            raise
        finally:
            self._finish(error)
        return self.returncode

    def communicate(self, timeout, *, input_bytes=None, output_limit=None):
        """Drain bounded reads without allowing EOF/wait to release group identity.

        output_limit is per stream, or None for the existing engine contract.
        A closed-pipe descendant is still killed after its leader exits. A
        descendant holding a pipe cannot extend cleanup/drain beyond its budget.
        """
        buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        error = None
        try:
            with selectors.DefaultSelector() as selector:
                for name in buffers:
                    pipe = getattr(self.process, name)
                    if pipe is not None:
                        os.set_blocking(pipe.fileno(), False)
                        selector.register(pipe, selectors.EVENT_READ, name)
                pending = memoryview(input_bytes or b'')
                if self.process.stdin is not None:
                    if pending:
                        os.set_blocking(self.process.stdin.fileno(), False)
                        selector.register(self.process.stdin, selectors.EVENT_WRITE, 'stdin')
                    else:
                        self.process.stdin.close()
                deadline = time.monotonic() + timeout
                draining = False
                while True:
                    if not draining and self.exited():
                        # Cleanup before collecting output EOF: a descendant may
                        # inherit the pipe or may close it and retain other files.
                        self.close(close_streams=False)
                        draining = True
                        deadline = time.monotonic() + 2
                    if draining and not selector.get_map():
                        break
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(self.arguments, timeout,
                                                        output=bytes(buffers['stdout']), stderr=bytes(buffers['stderr']))
                    for key, _ in selector.select(min(.05, max(0, deadline - time.monotonic()))):
                        pipe = key.fileobj
                        if key.data == 'stdin':
                            try:
                                written = os.write(pipe.fileno(), pending[:65536])
                                pending = pending[written:]
                            except BrokenPipeError:
                                pending = memoryview(b'')
                            if not pending:
                                selector.unregister(pipe); pipe.close()
                            continue
                        data = os.read(pipe.fileno(), 65536)
                        if not data:
                            selector.unregister(pipe)
                            continue
                        buffer = buffers[key.data]
                        available = len(data) if output_limit is None else max(0, output_limit - len(buffer))
                        buffer.extend(data[:available])
                        if len(data) > available:
                            raise OutputLimitExceeded(bytes(buffers['stdout']), bytes(buffers['stderr']))
        except BaseException as caught:
            error = caught
            raise
        finally:
            self._finish(error)
        return bytes(buffers['stdout']), bytes(buffers['stderr'])
