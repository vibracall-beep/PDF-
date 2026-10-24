"""Real child lifetimes for the focused converter diagnostic, without macOS."""
import fcntl
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import portable_office_diagnostics as diagnosis
from portable_office_diagnostics import ExitObservation, causal_denial, exact_office_profile, group_has_only_zombies, measure, office_socket, probe_expectation, stop


class OfficeDiagnosticProcessTests(unittest.TestCase):
    def test_causal_denial_cannot_be_a_timeout_signal_or_unrelated_error(self):
        denied = {'exit': 1, 'stoppedBecause': None, 'pdfExists': False, 'conversionPassed': False}
        self.assertTrue(causal_denial(denied))
        for changed in ({'stoppedBecause': 'deadline'}, {'stoppedBecause': 'log-limit'},
                        {'exit': -9}, {'exit': 2}, {'exit': True}, {'pdfExists': True}):
            with self.subTest(changed=changed):
                self.assertFalse(causal_denial(dict(denied, **changed)))

    def test_candidate_policy_adds_only_the_calculated_unix_literal(self):
        with tempfile.TemporaryDirectory(prefix='pdf-lo-profile-') as temporary:
            profile = Path(temporary).resolve()
            path = office_socket(profile, os.getuid())
            base = '(version 1)(allow default)(deny network*)(deny file-read* (subpath "/opt/homebrew"))'
            candidate = exact_office_profile(base, path)
            self.assertTrue(candidate.startswith(base + '\n'))
            self.assertEqual(candidate.count('(allow network-'), 1)
            self.assertIn('(literal "' + str(path) + '")', candidate)
            self.assertRegex(path.name, r'^OSL_PIPE_\d+_SingleOfficeIPC_[0-9a-f]{16,32}$')
            with self.assertRaises(ValueError): exact_office_profile(base, path.parent / 'unrelated')
            with self.assertRaises(ValueError): exact_office_profile(base, profile / path.name)

    def test_denied_network_requires_bind_eperm_not_an_absent_listener(self):
        outcome = {'exit': 0, 'stoppedBecause': None}
        denied = {'socketCreated': True, 'socketErrno': 0, 'bound': False, 'bindErrno': errno.EPERM,
                  'listening': False, 'listenErrno': 0, 'connected': False, 'connectErrno': 0,
                  'exchanged': False, 'exchangeErrno': 0}
        self.assertTrue(probe_expectation(outcome, denied, False))
        self.assertFalse(probe_expectation(outcome, dict(denied, bindErrno=0, connectErrno=errno.ECONNREFUSED), False))
        self.assertFalse(probe_expectation(outcome, dict(denied, bindErrno=True), False))
        self.assertFalse(probe_expectation({'exit': 124}, denied, False))
        self.assertFalse(probe_expectation(outcome, dict(denied, exchanged=True), False))

    def test_normal_exit_remains_unreaped_until_group_cleanup_finishes(self):
        ExitObservation.supported()
        process = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(7)'],
                                   start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Also exercise registration after a very short-lived child can have
        # exited, without calling poll()/wait() to collect it.
        time.sleep(0.1)
        observation = ExitObservation(process.pid)
        try:
            deadline = time.monotonic() + 5
            while not observation.exited() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(observation.exited())
            self.assertIsNone(process.returncode)
            if hasattr(os, 'waitid'):
                # An independent non-reaping wait proves the exit record is
                # still available, rather than only trusting a Python field.
                result = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                self.assertEqual((result.si_pid, result.si_status), (process.pid, 7))
        finally:
            try: stop(process, observation)
            finally: observation.close()
        self.assertEqual(process.returncode, 7)

    def test_exited_leader_cannot_leave_term_ignoring_child_holding_file_lock(self):
        with tempfile.TemporaryDirectory(prefix='pdf-office-process-') as temporary:
            root = Path(temporary); lock = root / 'child.lock'
            # The child signals readiness only after obtaining a real lock and
            # ignoring TERM. Its parent then exits before measure's cleanup.
            source = '''import fcntl,os,signal,sys,time
read_end,write_end=os.pipe()
pid=os.fork()
if pid==0:
    os.close(read_end)
    descriptor=os.open(sys.argv[1],os.O_CREAT|os.O_RDWR,0o600)
    fcntl.flock(descriptor,fcntl.LOCK_EX)
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    os.write(write_end,b"ready"); os.close(write_end)
    time.sleep(10)
    os._exit(0)
os.close(write_end)
assert os.read(read_end,5)==b"ready"
os.close(read_end)
os._exit(0)
'''
            result = measure([sys.executable, '-c', source, str(lock)], root / 'measurement', seconds=5)
            self.assertEqual(result['exit'], 0)
            self.assertIsNone(result['stoppedBecause'])
            self.assertLess(result['seconds'], 5)
            with lock.open('rb') as stream:
                # A live descendant would retain this lock even with all its
                # standard streams closed. Zombie PIDs do not retain handles.
                # SIGKILL delivery is asynchronous even though its leader has
                # been collected, so allow a bounded interval for FD closure.
                deadline = time.monotonic() + 1
                while True:
                    try:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline: raise
                        time.sleep(0.01)

    def test_deadline_terminates_owned_group_and_preserves_failure(self):
        with tempfile.TemporaryDirectory(prefix='pdf-office-timeout-') as temporary:
            result = measure([sys.executable, '-c', 'import time;time.sleep(20)'],
                             Path(temporary) / 'measurement', seconds=0.1)
            self.assertEqual(result['stoppedBecause'], 'deadline')
            self.assertLess(result['exit'], 0)
            self.assertLess(result['seconds'], 5)

    def test_darwin_eperm_requires_a_real_zombie_only_group(self):
        process = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(9)'], start_new_session=True)
        observation = ExitObservation(process.pid)
        try:
            deadline = time.monotonic() + 5
            while not observation.exited() and time.monotonic() < deadline: time.sleep(0.01)
            self.assertTrue(observation.exited())
            self.assertTrue(group_has_only_zombies(process.pid))
            # Inject only Darwin's signal error; exit observation and the
            # process table are real, and wait() must still recover status 9.
            with mock.patch.object(diagnosis.sys, 'platform', 'darwin'), \
                 mock.patch.object(diagnosis.os, 'killpg', side_effect=PermissionError(errno.EPERM, 'synthetic Darwin zombie EPERM')):
                stop(process, observation)
            self.assertEqual(process.returncode, 9)
        finally:
            if process.returncode is None: stop(process, observation)
            observation.close()

    def test_live_group_eperm_remains_fatal_and_leader_is_collected(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(20)'], start_new_session=True)
        observation = ExitObservation(process.pid)
        real_killpg = os.killpg
        def deny_term(group, signum):
            if signum == diagnosis.signal.SIGTERM:
                raise PermissionError(errno.EPERM, 'synthetic live-group denial')
            return real_killpg(group, signum)
        try:
            self.assertFalse(group_has_only_zombies(process.pid))
            with mock.patch.object(diagnosis.sys, 'platform', 'darwin'), \
                 mock.patch.object(diagnosis.os, 'killpg', side_effect=deny_term):
                with self.assertRaisesRegex(PermissionError, 'live-group denial'):
                    stop(process, observation)
            self.assertIsNotNone(process.returncode)
            self.assertLess(process.returncode, 0)
        finally:
            if process.returncode is None: stop(process, observation)
            observation.close()


if __name__ == '__main__':
    unittest.main()
