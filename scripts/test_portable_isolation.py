"""Portable verifier safety; actual Seatbelt behavior requires the Mac gates."""
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import portable_isolation as isolation


class PortableIsolationTests(unittest.TestCase):
    def test_policy_preserves_base_and_opens_only_canonical_private_namespace(self):
        base = '(version 1)(allow default)(deny network*)(deny file-read* file-write* (subpath "/opt/homebrew"))'
        with isolation.private_namespace() as (root, ipc, outside, state):
            result = isolation.candidate_profile(base, ipc, Path.home())
            self.assertTrue(result.startswith(base + '\n'))
            self.assertEqual(result.count('(allow network-'), 1)
            self.assertIn('(subpath "' + str(ipc) + '")', result)
            self.assertIn('(literal "' + str(Path('/tmp').resolve()) + '")', result)
            self.assertNotIn('remote ip', result)
            with self.assertRaises(ValueError): isolation.candidate_profile(base, ipc / 'escape', Path.home())
            ipc.chmod(0o755)
            with self.assertRaises(ValueError): isolation.candidate_profile(base, ipc, Path.home())
        self.assertTrue(state['removed']); self.assertFalse(root.exists())

    def test_denied_controls_require_eperm_and_exact_types(self):
        denied = {'socketCreated': True, 'socketErrno': 0, 'bound': False, 'bindErrno': errno.EPERM,
                  'listening': False, 'listenErrno': 0, 'connected': False, 'connectErrno': 0,
                  'exchanged': False, 'exchangeErrno': 0}
        self.assertTrue(isolation.probe_expected(0, denied, False))
        for changed in ({'bindErrno': errno.ECONNREFUSED}, {'bindErrno': True}, {'exchanged': True}):
            self.assertFalse(isolation.probe_expected(0, dict(denied, **changed), False))
        self.assertFalse(isolation.probe_expected(False, denied, False))
        self.assertFalse(isolation.probe_expected(124, denied, False))
        self.assertTrue(isolation.access_expected(0, {'writable': False, 'accessErrno': errno.EACCES}, False))
        self.assertFalse(isolation.access_expected(0, {'writable': False, 'accessErrno': errno.ENOENT}, False))

    def test_snapshot_detects_data_mode_addition_and_rejects_external_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve(); app = parent / 'PDF.app'; app.mkdir()
            original = app / 'resource'; original.write_bytes(b'original'); original.chmod(0o600)
            before = isolation.snapshot(app)
            moved = parent / 'moved.app'; app.rename(moved); original = moved / 'resource'
            self.assertEqual(isolation.snapshot(moved), before)
            original.chmod(0o644); self.assertNotEqual(isolation.snapshot(moved), before)
            original.chmod(0o600); original.write_bytes(b'altered'); self.assertNotEqual(isolation.snapshot(moved), before)
            original.write_bytes(b'original'); extra = moved / 'extra'; extra.write_bytes(b'new')
            self.assertNotEqual(isolation.snapshot(moved), before)
            extra.unlink(); extra.symlink_to(parent)
            with self.assertRaises(ValueError): isolation.snapshot(moved)

    def test_worker_receipt_requires_actual_parent_and_pdf_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            ipc = Path(temporary)
            content = b'%PDF-' + b'synthetic receipt fixture' * 16
            path = ipc / 'browser.pdf'; path.write_bytes(content)
            report = {'schemaVersion': 1, 'passed': True, 'mode': 'browser', 'parentPID': 123,
                      'pageCount': 1, 'recognizedTextMatched': True, 'browserClosed': True,
                      'browserPDFBytes': len(content), 'browserPDFSHA256': hashlib.sha256(content).hexdigest()}
            self.assertTrue(isolation.worker_expected(0, report, 'browser', ipc, 123))
            self.assertFalse(isolation.worker_expected(0, report, 'browser', ipc, 456))
            for changed in ({'pageCount': True}, {'schemaVersion': True}, {'browserClosed': False},
                            {'browserPDFSHA256': 'a' * 64}, {'browserPDFBytes': len(content) - 1}):
                self.assertFalse(isolation.worker_expected(0, dict(report, **changed), 'browser', ipc, 123))
            path.write_bytes(content + b'changed')
            self.assertFalse(isolation.worker_expected(0, report, 'browser', ipc, 123))

    def test_real_exit_is_preserved_and_namespace_removed_after_collection(self):
        with isolation.private_namespace() as (root, ipc, outside, state):
            code, output = isolation.run_owned([sys.executable, '-c', 'print("real child");raise SystemExit(7)'],
                                                seconds=5, capture=True)
            self.assertEqual(code, 7); self.assertEqual(output, b'real child\n')
            self.assertTrue(state['children'][0]['cleanupConfirmed'])
            self.assertTrue(root.is_dir())
        self.assertTrue(state['removed']); self.assertFalse(root.exists())

    def test_uncertain_collection_preserves_namespace_and_original_timeout(self):
        class RefusedCollection:
            cleanup_confirmed = False
            pid = 123
            def __init__(self, *args, **kwargs): pass
            def wait(self, timeout): raise subprocess.TimeoutExpired(['synthetic refused-reap'], timeout)
            def close(self): raise ChildProcessError(errno.ECHILD, 'synthetic collection refused')
        root = None
        try:
            with mock.patch.object(isolation, 'OwnedProcess', RefusedCollection):
                with self.assertRaises(subprocess.TimeoutExpired) as caught:
                    with isolation.private_namespace() as (root, ipc, outside, state):
                        (ipc / 'must-survive').write_bytes(b'preserve until collection is established')
                        isolation.run_owned(['synthetic'], seconds=1)
            self.assertTrue(root.is_dir()); self.assertTrue((ipc / 'must-survive').is_file())
            self.assertTrue(state['preserved']); self.assertFalse(state['removed'])
            self.assertTrue(any('preserved' in note for note in caught.exception.__notes__))
        finally:
            if root is not None: shutil.rmtree(root)

    def test_replaced_namespace_is_not_deleted(self):
        root = replacement = None
        try:
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                with isolation.private_namespace() as (root, ipc, outside, state):
                    replacement = root.with_name(root.name + '-original')
                    root.rename(replacement); root.mkdir(mode=0o700)
                    (root / 'unrelated').write_bytes(b'do not remove')
            self.assertEqual((root / 'unrelated').read_bytes(), b'do not remove')
            self.assertTrue(state['preserved']); self.assertTrue(replacement.is_dir())
        finally:
            for item in (root, replacement):
                if item is not None: shutil.rmtree(item)

    def test_failed_checker_does_not_delete_root_held_by_other_session(self):
        # The orphaned fixture releases its lock only after our explicit file
        # handshake, with a short emergency deadline. No post-reap PID signal.
        with tempfile.TemporaryDirectory(prefix='pdf-transitive-control-') as temporary:
            fixture = Path(temporary); ready = fixture / 'ready'
            release = fixture / 'release'; released = fixture / 'released'
            descendant = fixture / 'descendant.py'
            descendant.write_text('import fcntl,os,sys,time\nfrom pathlib import Path\n'
                'fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)\n'
                'fcntl.flock(fd,fcntl.LOCK_EX)\n'
                'Path(sys.argv[2]).write_text(str(os.getpgrp()))\n'
                'deadline=time.monotonic()+10\n'
                'while not Path(sys.argv[3]).exists() and time.monotonic()<deadline: time.sleep(.01)\n'
                'os.close(fd)\nPath(sys.argv[4]).write_text("released")\n')
            checker = fixture / 'checker.py'
            checker.write_text('import os,subprocess,sys,time\nfrom pathlib import Path\n'
                'child=subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4],sys.argv[5]],'
                'start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n'
                'deadline=time.monotonic()+5\n'
                'while not Path(sys.argv[3]).exists() and time.monotonic()<deadline: time.sleep(.01)\n'
                'assert Path(sys.argv[3]).exists()\n'
                'assert int(Path(sys.argv[3]).read_text()) != os.getpgrp()\n'
                'raise SystemExit(1)\n')
            root = None
            try:
                with self.assertRaisesRegex(RuntimeError, 'synthetic checker failure'):
                    with isolation.private_namespace() as (root, ipc, outside, state):
                        state['workloadsStarted'] = True
                        lock = ipc / 'held.lock'
                        code, _ = isolation.run_owned([sys.executable, checker, descendant, lock, ready, release, released], seconds=7, capture=True)
                        self.assertEqual(code, 1)
                        raise RuntimeError('synthetic checker failure after uncertain inner cleanup')
                self.assertTrue(state['children'][0]['cleanupConfirmed'])
                self.assertTrue(state['transitiveCleanupUnverified']); self.assertTrue(state['preserved'])
                self.assertFalse(state['removed']); self.assertTrue(root.is_dir())
                with lock.open('rb') as stream:
                    with self.assertRaises(BlockingIOError): fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                release.touch(exist_ok=True)
                if ready.exists():
                    deadline = time.monotonic() + 5
                    while not released.exists() and time.monotonic() < deadline: time.sleep(.01)
                    self.assertTrue(released.exists(), 'The owned fixture must acknowledge releasing its lock.')
                if root is not None and root.exists():
                    with lock.open('rb') as stream: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    shutil.rmtree(root)


if __name__ == '__main__': unittest.main()
