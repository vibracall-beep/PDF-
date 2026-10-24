#!/usr/bin/env python3
"""Exercise actual descriptor inheritance, process lifetime and update refusal."""
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

import binary_update as updater
import bundle_lease
from test_binary_update import fixture_app
from package_binary import write_manifest

SCRIPTS = Path(__file__).resolve().parent


class BundleLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app = self.root / 'PDF.app'; fixture_app(self.app, 'old')
        self.distribution = self.root / 'package'; self.distribution.mkdir()
        fixture_app(self.distribution / 'PDF.app', 'new')
        write_manifest(self.distribution, 'a' * 40)

    def tearDown(self):
        self.temporary.cleanup()

    def reader(self, app):
        code = 'import fcntl,os,sys;fd=os.open(sys.argv[1],os.O_RDONLY);fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB);print("ready",flush=True);sys.stdin.read()'
        process = subprocess.Popen([sys.executable, '-c', code, str(app / bundle_lease.RESOURCE)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(process.stdout.readline().strip(), 'ready')
        return process

    def stop(self, process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def test_running_reader_blocks_update_then_real_kill_releases_lease(self):
        process = self.reader(self.app)
        try:
            with self.assertRaisesRegex(ValueError, 'execução'):
                updater.install(self.distribution, self.root, validate=lambda _: None)
            self.assertEqual((self.app / 'Contents/MacOS/PDF').read_text(), 'old')
            self.assertFalse((self.root / '.pdf-update.json').exists())
            self.assertEqual(list(self.root.glob('PDF.previous.*')), [])
            process.kill(); process.wait(timeout=5)
            self.assertEqual(process.returncode, -signal.SIGKILL)
            updater.install(self.distribution, self.root, validate=lambda _: None)
            self.assertEqual((self.app / 'Contents/MacOS/PDF').read_text(), 'new')
        finally:
            self.stop(process)

    def test_wrapper_passes_same_descriptor_without_unlocking_parent(self):
        with bundle_lease.exclusive(self.app) as descriptor:
            environment = dict(os.environ, PDF_INSTALLATION_LOCK_FD=str(descriptor), PDF_INSTALLATION_LOCK_BUNDLE=str(self.app))
            code = 'import os,fcntl;fd=int(os.environ["PDF_INSTALLATION_LOCK_FD"]);assert os.fstat(fd).st_size==0;fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)'
            subprocess.run([sys.executable, str(SCRIPTS / 'run-with-timeout.py'), '--seconds', '5', '--',
                            sys.executable, '-c', code], env=environment, pass_fds=(descriptor,), check=True, timeout=8)
            other = bundle_lease.open_resource(self.app)
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_SH | fcntl.LOCK_NB)
            finally:
                os.close(other)

    def test_foreign_inherited_descriptor_is_refused(self):
        with bundle_lease.exclusive(self.distribution / 'PDF.app') as descriptor:
            with self.assertRaisesRegex(ValueError, 'não pertence'):
                bundle_lease.validate_inherited(self.app, descriptor)

    def test_source_shell_retains_lock_after_python_child_exits(self):
        shell = '''set -eu
exec 9< "$1/Contents/Resources/installation.lock"
"$2" "$3/bundle_lease.py" --app "$1" --fd 9
"$2" - "$1/Contents/Resources/installation.lock" <<'CHECK'
import fcntl,os,sys
fd=os.open(sys.argv[1],os.O_RDONLY)
try:
 fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
except BlockingIOError:
 sys.exit(0)
sys.exit('The source installer lost its exclusive lease')
CHECK
'''
        subprocess.run(['/bin/bash', '-c', shell, 'source-install-fixture', str(self.app), sys.executable, str(SCRIPTS)],
                       check=True, capture_output=True, timeout=10)

    def test_legacy_bundle_is_preserved_without_unsafe_update(self):
        (self.app / bundle_lease.RESOURCE).unlink()
        with self.assertRaisesRegex(ValueError, 'diretório novo'):
            updater.install(self.distribution, self.root, validate=lambda _: None)
        self.assertEqual((self.app / 'Contents/MacOS/PDF').read_text(), 'old')
        self.assertEqual(list(self.root.glob('PDF.previous.*')), [])

    def test_writable_or_symlink_lease_is_not_trusted(self):
        resource = self.app / bundle_lease.RESOURCE
        resource.chmod(0o644)
        with self.assertRaises(ValueError):
            bundle_lease.open_resource(self.app)
        resource.unlink(); resource.symlink_to(self.distribution / 'PDF.app' / bundle_lease.RESOURCE)
        with self.assertRaises(OSError):
            bundle_lease.open_resource(self.app)

    def test_restart_preserves_open_candidate_and_journal_until_closed(self):
        token = 'a' * 32
        old_id = updater.identity(self.app)
        backup = self.root / ('PDF.previous.' + token + '.app')
        self.app.rename(backup)
        fixture_app(self.app, 'new')
        updater.write_journal(self.root, {'schemaVersion': 1, 'transaction': token, 'state': 'activated',
                                         'oldIdentity': old_id, 'newIdentity': updater.identity(self.app)})
        process = self.reader(self.app)
        try:
            with self.assertRaisesRegex(ValueError, 'execução'):
                updater.recover(self.root)
            self.assertTrue((self.root / '.pdf-update.json').is_file())
            self.assertEqual((self.app / 'Contents/MacOS/PDF').read_text(), 'new')
            self.stop(process)
            updater.recover(self.root)
            self.assertEqual((self.app / 'Contents/MacOS/PDF').read_text(), 'old')
            self.assertFalse((self.root / '.pdf-update.json').exists())
        finally:
            self.stop(process)


if __name__ == '__main__':
    unittest.main()
