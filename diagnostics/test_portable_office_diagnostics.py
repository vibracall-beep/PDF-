"""Real child lifetimes for the focused converter diagnostic, without macOS."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from portable_office_diagnostics import ExitObservation, measure, stop


class OfficeDiagnosticProcessTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
