"""Real process-group lifetimes, pipe draining and lease/lock release."""
import errno
import fcntl
import importlib.util
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
import owned_process
from owned_process import ExitObservation, OwnedProcess, OutputLimitExceeded
from pdf_engine import _external

spec = importlib.util.spec_from_file_location('pdfkit_process_audit', ROOT / 'diagnostics/run_pdfkit_diagnostics.py')
diagnostic = importlib.util.module_from_spec(spec); spec.loader.exec_module(diagnostic)

# The child acknowledges a real file lock and installed TERM handler before
# its leader exits. It cannot keep the parent alive merely through its pipes.
DESCENDANT = r'''import fcntl,os,signal,sys,time
r,w=os.pipe()
pid=os.fork()
if pid==0:
 os.close(r)
 fd=os.open(sys.argv[1],os.O_CREAT|os.O_RDWR,0o600)
 fcntl.flock(fd,fcntl.LOCK_EX)
 signal.signal(signal.SIGTERM,signal.SIG_IGN)
 if sys.argv[2]=='closed':
  null=os.open(os.devnull,os.O_WRONLY);os.dup2(null,1);os.dup2(null,2);os.close(null)
 os.write(w,b'ready');os.close(w)
 time.sleep(10);os._exit(0)
os.close(w)
assert os.read(r,5)==b'ready'
os.close(r)
os.write(1,b'leader output\n');os.write(2,b'leader diagnostic\n')
os._exit(7)
'''


class OwnedProcessTests(unittest.TestCase):
    def assert_unlocked(self, path):
        with Path(path).open('rb') as stream:
            deadline = time.monotonic() + 2
            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return
                except BlockingIOError:
                    if time.monotonic() >= deadline: raise
                    time.sleep(.01)

    def test_normal_exit_cleans_descendants_with_closed_or_inherited_pipes_in_all_callers(self):
        with tempfile.TemporaryDirectory(prefix='pdf-owned-descendants-') as temporary:
            for caller in ('owned', 'engine', 'wrapper', 'diagnostic'):
                for pipes in ('closed', 'inherited'):
                    with self.subTest(caller=caller, pipes=pipes):
                        lock = Path(temporary) / (caller + '-' + pipes + '.lock')
                        command = [sys.executable, '-c', DESCENDANT, str(lock), pipes]
                        began = time.monotonic()
                        if caller == 'owned':
                            child = OwnedProcess(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            out, err = child.communicate(3)
                            code = child.returncode
                        elif caller == 'engine':
                            result = _external(command, timeout=3, allowed_returncodes=(7,))
                            code, out, err = result.returncode, result.stdout.encode(), result.stderr.encode()
                        elif caller == 'wrapper':
                            result = subprocess.run([sys.executable, str(ROOT / 'scripts/run-with-timeout.py'),
                                                     '--seconds', '3', '--', *command],
                                                    capture_output=True, timeout=6)
                            code, out, err = result.returncode, result.stdout, result.stderr
                        else:
                            result = diagnostic.run(command, seconds=3)
                            self.assertFalse(result['timedOut']); self.assertFalse(result['outputLimitExceeded'])
                            code, out, err = result['exitCode'], result['stdout'].encode(), result['stderr'].encode()
                        self.assertEqual(code, 7)
                        self.assertEqual(out, b'leader output\n')
                        self.assertEqual(err, b'leader diagnostic\n')
                        self.assertLess(time.monotonic() - began, 3)
                        self.assert_unlocked(lock)

    def test_signals_precede_reap_and_repeated_close_never_signals_again(self):
        real_signal = owned_process.signal_owned_group
        observed = []
        def checked(process, observation, signum):
            self.assertIsNone(process.returncode)
            if hasattr(os, 'waitid'):
                os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            observed.append(signum)
            real_signal(process, observation, signum)
        with mock.patch.object(owned_process, 'signal_owned_group', side_effect=checked):
            child = OwnedProcess([sys.executable, '-c', 'raise SystemExit(9)'])
            self.assertEqual(child.wait(3), 9)
            child.close(); child.close()
        self.assertEqual(observed, [signal.SIGTERM, signal.SIGKILL])

    def test_large_two_stream_output_and_universal_newlines_are_preserved(self):
        command = [sys.executable, '-c', 'import os;os.write(1,b"x"*1048576+b"\\r\\nend\\r");os.write(2,b"y"*1048576)']
        result = _external(command, timeout=5)
        self.assertEqual(result.stdout, 'x' * 1048576 + '\nend\n')
        self.assertEqual(result.stderr, 'y' * 1048576)

    def test_pipe_input_larger_than_capacity_does_not_deadlock_and_owned_handles_close(self):
        child = OwnedProcess([sys.executable, '-c', 'import sys;data=sys.stdin.buffer.read();sys.stdout.buffer.write(data)'],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        payload = b'payload\n' * 131072
        out, err = child.communicate(5, input_bytes=payload)
        self.assertEqual((out, err, child.returncode), (payload, b'', 0))
        self.assertTrue(all(stream.closed for stream in (child.process.stdin, child.process.stdout, child.process.stderr)))

    def test_timeout_kills_term_resistant_leader_without_changing_timeout_error(self):
        command = [sys.executable, '-c', 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(10)']
        child = OwnedProcess(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, grace_seconds=.1)
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            child.communicate(.3)
        self.assertIn(b'ready', caught.exception.output)
        self.assertEqual(child.returncode, -signal.SIGKILL)
        self.assertTrue(child.process.stdout.closed)

    def test_output_limit_is_explicit_bounded_and_fatal_in_diagnostic(self):
        command = [sys.executable, '-c', 'import os,time;os.write(1,b"x"*32768);time.sleep(10)']
        result = diagnostic.run(command, seconds=3, output_limit=128)
        self.assertTrue(result['outputLimitExceeded']); self.assertFalse(result['timedOut'])
        self.assertEqual(len(result['stdout']), 128)
        self.assertLess(result['exitCode'], 0)

    def test_diagnostic_timeout_and_wrapper_statuses_remain_failures(self):
        command = [sys.executable, '-c', 'import time;time.sleep(10)']
        result = diagnostic.run(command, seconds=.1)
        self.assertTrue(result['timedOut']); self.assertLess(result['exitCode'], 0)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run-with-timeout.py'),
                                 '--seconds', '.1', '--', *command], capture_output=True, timeout=4)
        self.assertEqual(result.returncode, 124)
        self.assertIn(b'exceeded 0.1 seconds', result.stderr)

    def test_wrapper_sigint_and_sigterm_cancel_live_group_and_release_child_lock(self):
        with tempfile.TemporaryDirectory(prefix='pdf-owned-cancel-') as temporary:
            for requested in (signal.SIGINT, signal.SIGTERM):
                with self.subTest(signal=requested):
                    lock = Path(temporary) / (str(requested) + '.lock')
                    ready = Path(temporary) / (str(requested) + '.ready')
                    source = DESCENDANT.replace('os._exit(7)',
                        'open(sys.argv[3], "w").write("ready");time.sleep(10)')
                    command = [sys.executable, str(ROOT / 'scripts/run-with-timeout.py'), '--seconds', '20', '--',
                               sys.executable, '-c', source, str(lock), 'closed', str(ready)]
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    try:
                        deadline = time.monotonic() + 3
                        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                            time.sleep(.01)
                        self.assertTrue(ready.exists(), 'The real group must start before cancellation.')
                        process.send_signal(requested)
                        process.communicate(timeout=5)
                        self.assertEqual(process.returncode, 128 + requested)
                        self.assert_unlocked(lock)
                    finally:
                        if process.poll() is None: process.kill()
                        process.communicate(timeout=5)

    def test_passed_lease_remains_callers_property_and_descendants_release_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'lease'; path.touch()
            descriptor = os.open(path, os.O_RDONLY)
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            child = OwnedProcess([sys.executable, '-c', 'import os,sys;os.fstat(int(sys.argv[1]));print("lease inherited")', str(descriptor)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(descriptor,))
            try:
                self.assertEqual(child.communicate(3), (b'lease inherited\n', b''))
                os.fstat(descriptor)  # close() never closes the caller's FD.
            finally:
                os.close(descriptor)
            self.assert_unlocked(path)

    def test_observer_setup_failure_still_kills_and_collects_child(self):
        created = []
        real_popen = subprocess.Popen
        def spawn(*args, **kwargs):
            process = real_popen(*args, **kwargs); created.append(process); return process
        with mock.patch.object(owned_process.subprocess, 'Popen', side_effect=spawn), \
             mock.patch.object(ExitObservation, '__init__', side_effect=RuntimeError('synthetic registration failure')):
            with self.assertRaisesRegex(RuntimeError, 'registration failure'):
                OwnedProcess([sys.executable, '-c', 'import time;time.sleep(10)'], stdout=subprocess.PIPE)
        self.assertEqual(len(created), 1)
        self.assertLess(created[0].returncode, 0)
        self.assertTrue(created[0].stdout.closed)

    def test_original_timeout_retains_cleanup_failure_as_note(self):
        real_signal = owned_process.signal_owned_group
        def fail_term(process, observation, signum):
            if signum == signal.SIGTERM: raise PermissionError(errno.EPERM, 'synthetic live denial')
            real_signal(process, observation, signum)
        child = OwnedProcess([sys.executable, '-c', 'import time;time.sleep(10)'], stdout=subprocess.PIPE)
        with mock.patch.object(owned_process, 'signal_owned_group', side_effect=fail_term):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                child.communicate(.1)
        self.assertLess(child.returncode, 0)
        self.assertTrue(any('PermissionError' in note for note in caught.exception.__notes__))

    def test_timed_out_collection_remains_pending_and_retry_does_not_signal(self):
        child = OwnedProcess([sys.executable, '-c', 'import time;time.sleep(10)'])
        real_wait = child.process.wait
        with mock.patch.object(child.process, 'wait', side_effect=subprocess.TimeoutExpired('collect', 5)), \
             mock.patch.object(owned_process, 'signal_owned_group', wraps=owned_process.signal_owned_group) as sent:
            with self.assertRaises(subprocess.TimeoutExpired): child.close()
            self.assertFalse(child.closed)
            self.assertTrue(child.signals_finished)
            self.assertEqual(sent.call_count, 2)
        with mock.patch.object(owned_process, 'signal_owned_group') as sent:
            child.close()
            sent.assert_not_called()
        self.assertTrue(child.closed)
        self.assertLess(child.returncode, 0)

    def test_relocated_wrapper_imports_bundled_helper_without_host_pythonpath(self):
        with tempfile.TemporaryDirectory(prefix='PDF bundle with spaces ') as temporary:
            resources = Path(temporary) / 'PDF.app/Contents/Resources'
            engine = resources / 'engine'; distribution = resources / 'distribution'
            engine.mkdir(parents=True); distribution.mkdir()
            shutil.copy2(ROOT / 'engine/owned_process.py', engine / 'owned_process.py')
            for name in ('run-with-timeout.py', 'bundle_lease.py'):
                shutil.copy2(ROOT / 'scripts' / name, distribution / name)
            result = subprocess.run([sys.executable, '-I', str(distribution / 'run-with-timeout.py'),
                                     '--seconds', '3', '--', sys.executable, '-c', 'print("relocated")'],
                                    cwd='/', capture_output=True, timeout=5)
            self.assertEqual((result.returncode, result.stdout), (0, b'relocated\n'))

    def test_custom_sigchld_is_rejected_before_spawn(self):
        with mock.patch.object(owned_process.signal, 'getsignal', return_value=signal.SIG_IGN), \
             mock.patch.object(owned_process.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'SIGCHLD'):
                OwnedProcess([sys.executable, '-c', 'pass'])
            spawn.assert_not_called()

    def test_darwin_eperm_requires_positive_zombie_proof(self):
        child = OwnedProcess([sys.executable, '-c', 'raise SystemExit(9)'])
        deadline = time.monotonic() + 3
        while not child.exited() and time.monotonic() < deadline: time.sleep(.01)
        self.assertTrue(child.exited())
        self.assertTrue(owned_process.group_has_only_zombies(child.pid))
        with mock.patch.object(owned_process.sys, 'platform', 'darwin'), \
             mock.patch.object(owned_process.os, 'killpg', side_effect=PermissionError(errno.EPERM, 'zombie fixture')):
            child.close()
        self.assertEqual(child.returncode, 9)

    def test_live_darwin_eperm_is_not_accepted(self):
        child = OwnedProcess([sys.executable, '-c', 'import time;time.sleep(10)'])
        real_killpg = os.killpg
        def deny_term(pid, signum):
            if signum == signal.SIGTERM: raise PermissionError(errno.EPERM, 'live fixture')
            return real_killpg(pid, signum)
        with mock.patch.object(owned_process.sys, 'platform', 'darwin'), \
             mock.patch.object(owned_process.os, 'killpg', side_effect=deny_term):
            with self.assertRaisesRegex(PermissionError, 'live fixture'): child.close()
        self.assertLess(child.returncode, 0)


if __name__ == '__main__': unittest.main()
