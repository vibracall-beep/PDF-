#!/usr/bin/env python3
"""Real process interruption and filesystem fault coverage for binary updates."""
import errno
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import binary_update as updater
from package_binary import write_manifest

SCRIPTS = Path(__file__).resolve().parent


def fixture_app(path, version):
    (path / 'Contents/MacOS').mkdir(parents=True)
    (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'local.pdf.desktop'}))
    (path / 'Contents/MacOS/PDF').write_text(version)


class BinaryUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.distribution = self.root / 'package'; self.distribution.mkdir()
        fixture_app(self.distribution / 'PDF.app', 'new')
        write_manifest(self.distribution, 'a' * 40)
        self.parent = self.root / 'Applications'; self.parent.mkdir()
        fixture_app(self.parent / 'PDF.app', 'old')
        self.preferences = self.root / 'Preferences'; self.preferences.write_bytes(b'private preferences unchanged')

    def tearDown(self):
        self.temp.cleanup()

    def version(self):
        return (self.parent / 'PDF.app/Contents/MacOS/PDF').read_text()

    def test_valid_update_preserves_previous_bundle_and_preferences(self):
        seen = []
        updater.install(self.distribution, self.parent, validate=lambda path: seen.append(path))
        self.assertEqual(self.version(), 'new')
        self.assertEqual(len(seen), 2)
        backups = list(self.parent.glob('PDF.previous.*.app'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'Contents/MacOS/PDF').read_text(), 'old')
        self.assertEqual(self.preferences.read_bytes(), b'private preferences unchanged')
        self.assertFalse((self.parent / '.pdf-update.json').exists())

    def test_activation_validation_failure_restores_old_and_preserves_failed(self):
        def validate(path):
            if path.name == 'PDF.app':
                raise ValueError('real validation rejected the candidate')
        with self.assertRaises(ValueError):
            updater.install(self.distribution, self.parent, validate=validate)
        self.assertEqual(self.version(), 'old')
        self.assertEqual(len(list(self.parent.glob('PDF.failed.*.app'))), 1)

    def test_manifest_rejects_tampering_added_file_and_changed_mode(self):
        app = self.distribution / 'PDF.app/Contents/MacOS/PDF'
        for mutate, restore in (
            (lambda: app.write_text('evil'), lambda: app.write_text('new')),
            (lambda: app.chmod(0o755), lambda: app.chmod(0o644)),
            (lambda: (self.distribution / 'extra').write_text('extra'), lambda: (self.distribution / 'extra').unlink()),
        ):
            mutate()
            with self.assertRaises(ValueError):
                updater.install(self.distribution, self.parent, validate=lambda _: None)
            restore()
            self.assertEqual(self.version(), 'old')

    def test_manifest_rejects_external_symlink_before_installation(self):
        (self.distribution / 'escape').symlink_to(self.preferences)
        with self.assertRaises(ValueError):
            updater.verify_manifest(self.distribution)
        self.assertEqual(self.version(), 'old')

    def test_journal_cannot_redirect_recovery_to_user_paths(self):
        (self.parent / '.pdf-update.json').write_text(json.dumps({'schemaVersion': 1,
            'transaction': '../../Preferences', 'state': 'activated', 'newIdentity': '1:2', 'oldIdentity': None}))
        with self.assertRaises(ValueError):
            updater.recover(self.parent)
        self.assertEqual(self.preferences.read_bytes(), b'private preferences unchanged')
        self.assertEqual(self.version(), 'old')

    def test_fifo_lock_is_rejected_without_blocking(self):
        os.mkfifo(self.parent / '.pdf-update.lock')
        started = time.monotonic()
        with self.assertRaises((OSError, ValueError)):
            updater.install(self.distribution, self.parent, validate=lambda _: None)
        self.assertLess(time.monotonic() - started, 1)

    def test_sigkill_between_each_publication_step_recovers_on_new_process(self):
        for step in ('prepared', 'backup-renamed', 'activation-renamed', 'validated-destination', 'committed'):
            with self.subTest(step=step):
                # Each iteration uses its own original bundle and preferences.
                parent = self.root / step; parent.mkdir(); fixture_app(parent / 'PDF.app', 'old')
                ready = self.root / (step + '.ready')
                child = '''import sys,time\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nimport binary_update as update\ndef checkpoint(step):\n if step==sys.argv[4]:\n  Path(sys.argv[5]).write_text(step)\n  while True: time.sleep(1)\nupdate.install(Path(sys.argv[2]),Path(sys.argv[3]),validate=lambda _:None,checkpoint=checkpoint)\n'''
                process = subprocess.Popen([sys.executable, '-c', child, str(SCRIPTS), str(self.distribution),
                                            str(parent), step, str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
                        time.sleep(0.02)
                    self.assertTrue(ready.exists(), 'child did not reach exact durable transaction boundary')
                    os.kill(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                    self.assertEqual(process.returncode, -signal.SIGKILL)
                finally:
                    if process.poll() is None:
                        process.kill(); process.wait()
                    process.communicate()
                result = subprocess.run([sys.executable, str(SCRIPTS / 'binary_update.py'), 'recover',
                                         '--destination', str(parent)], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((parent / 'PDF.app/Contents/MacOS/PDF').read_text(), 'new' if step == 'committed' else 'old')
                self.assertFalse((parent / '.pdf-update.json').exists())
                self.assertEqual(self.preferences.read_bytes(), b'private preferences unchanged')

    @unittest.skipUnless(Path('/dev/full').exists(), 'Linux /dev/full supplies a real ENOSPC write')
    def test_real_enospc_after_backup_restores_old_bundle(self):
        real_write = updater.write_journal
        full = False
        def write(parent, data):
            if full:
                descriptor = os.open('/dev/full', os.O_WRONLY)
                try:
                    os.write(descriptor, b'journal data')  # actual kernel ENOSPC
                finally:
                    os.close(descriptor)
            real_write(parent, data)
        def checkpoint(step):
            nonlocal full
            if step == 'backup-renamed':
                full = True
        with patch.object(updater, 'write_journal', write):
            with self.assertRaises(OSError) as caught:
                updater.install(self.distribution, self.parent, validate=lambda _: None, checkpoint=checkpoint)
        self.assertEqual(caught.exception.errno, errno.ENOSPC)
        self.assertEqual(self.version(), 'old')
        self.assertFalse((self.parent / '.pdf-update.json').exists())

    def test_concurrent_destination_is_never_overwritten_during_recovery(self):
        def checkpoint(step):
            if step == 'backup-renamed':
                fixture_app(self.parent / 'PDF.app', 'concurrent user bundle')
                raise ValueError('injected interruption with concurrent owner')
        with self.assertRaises(ValueError):
            updater.install(self.distribution, self.parent, validate=lambda _: None, checkpoint=checkpoint)
        self.assertEqual(self.version(), 'concurrent user bundle')
        self.assertTrue((self.parent / '.pdf-update.json').exists())
        backup = next(self.parent.glob('PDF.previous.*.app'))
        self.assertEqual((backup / 'Contents/MacOS/PDF').read_text(), 'old')

    @unittest.skipUnless(sys.platform == 'darwin', 'real bounded macOS disk image full-disk test')
    def test_real_full_disk_during_update_can_recover_after_space_is_freed(self):
        image = self.root / 'bounded-full-disk.dmg'
        mount = self.root / 'volume'; mount.mkdir()
        subprocess.run(['/usr/bin/hdiutil', 'create', '-size', '32m', '-fs', 'HFS+', '-volname', 'PDFFaultFixture', str(image)],
                       check=True, capture_output=True, timeout=60)
        attached = False
        try:
            subprocess.run(['/usr/bin/hdiutil', 'attach', '-nobrowse', '-mountpoint', str(mount), str(image)],
                           check=True, capture_output=True, timeout=60)
            attached = True
            volume = os.statvfs(mount)
            self.assertLess(volume.f_blocks * volume.f_frsize, 64 * 1024 ** 2)
            parent = mount / 'Applications'; parent.mkdir(); fixture_app(parent / 'PDF.app', 'old')
            filler = mount / 'fill.bin'
            def checkpoint(step):
                if step == 'backup-renamed':
                    with filler.open('wb', buffering=0) as stream:
                        while True:
                            try:
                                stream.write(b'X' * 4096)
                            except OSError as error:
                                self.assertEqual(error.errno, errno.ENOSPC)
                                break
            with self.assertRaises(OSError) as caught:
                updater.install(self.distribution, parent, validate=lambda _: None, checkpoint=checkpoint)
            self.assertEqual(caught.exception.errno, errno.ENOSPC)
            filler.unlink()
            with updater.installation_lock(parent):
                updater.recover(parent)
            self.assertEqual((parent / 'PDF.app/Contents/MacOS/PDF').read_text(), 'old')
        finally:
            if attached:
                subprocess.run(['/usr/bin/hdiutil', 'detach', str(mount)], check=True, capture_output=True, timeout=60)


if __name__ == '__main__':
    unittest.main()
