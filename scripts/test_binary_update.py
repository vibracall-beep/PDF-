#!/usr/bin/env python3
"""Real process interruption and filesystem fault coverage for binary updates."""
import errno
import json
import os
from pathlib import Path
import plistlib
import re
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


def detach_fixture_image(image, device):
    """Retry transient busy only for our exact synthetic image; never force."""
    if re.fullmatch(r'/dev/disk[0-9]+', device) is None:
        raise ValueError('Invalid fixture device identity.')
    for attempt in range(4):
        inspection = subprocess.run(['/usr/bin/hdiutil', 'info', '-plist'],
                                    check=True, capture_output=True, timeout=15)
        images = plistlib.loads(inspection.stdout).get('images', [])
        owned = [item for item in images
                 if Path(item.get('image-path', '')).resolve() == image.resolve()]
        if not owned:
            return  # The synthetic image is already detached; touch no device.
        if len(owned) != 1 or device not in {item.get('dev-entry') for item in owned[0].get('system-entities', [])}:
            raise RuntimeError('Fixture image device changed; unrelated devices were preserved.')
        result = subprocess.run(['/usr/bin/hdiutil', 'detach', device],
                                capture_output=True, timeout=15)
        if result.returncode == 0:
            return
        if result.returncode != errno.EBUSY or attempt == 3:
            diagnostic = result.stderr.decode('utf-8', errors='replace')[:2048].strip()
            raise RuntimeError(f'Fixture detach failed with status {result.returncode}: {diagnostic}')
        time.sleep(2 ** attempt)


def cleanup_fixture_image(image, device, primary_error=None):
    try:
        detach_fixture_image(image, device)
    except Exception as cleanup_error:
        if primary_error is None:
            raise
        primary_error.add_note('Synthetic HFS cleanup also failed: ' + str(cleanup_error))


def fixture_app(path, version):
    (path / 'Contents/MacOS').mkdir(parents=True)
    (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'local.pdf.desktop'}))
    (path / 'Contents/MacOS/PDF').write_text(version)
    (path / 'Contents/Resources').mkdir()
    lease = path / 'Contents/Resources/installation.lock'
    lease.touch(); lease.chmod(0o444)


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

    def test_failed_staging_validation_does_not_accumulate_copies(self):
        def reject(path):
            self.assertTrue((path / 'Contents/MacOS/PDF').is_file())
            raise ValueError('candidate failed before publication')
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'before publication'):
                updater.install(self.distribution, self.parent, validate=reject)
            self.assertEqual(list(self.parent.glob('.pdf-incoming.*.app')), [])
            self.assertFalse((self.parent / '.pdf-update.json').exists())
            self.assertEqual(self.version(), 'old')

    def test_partial_copy_failure_removes_only_this_staging_directory(self):
        def fail_copy(source, destination):
            Path(destination).write_bytes(b'partial')
            raise OSError(errno.ENOSPC, 'no space for copy')
        with patch.object(updater, 'copy_regular_file', fail_copy):
            with self.assertRaises((OSError, updater.shutil.Error)):
                updater.install(self.distribution, self.parent, validate=lambda _: None)
        self.assertEqual(list(self.parent.glob('.pdf-incoming.*.app')), [])
        self.assertEqual(self.version(), 'old')

    def test_staging_failure_preserves_foreign_replacement(self):
        def replace(path):
            path.rename(self.parent / 'owned-copy-preserved.app')
            path.mkdir()
            (path / 'foreign.txt').write_text('foreign replacement')
            raise ValueError('directory identity changed')
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            updater.install(self.distribution, self.parent, validate=replace)
        incoming = next(self.parent.glob('.pdf-incoming.*.app'))
        self.assertEqual((incoming / 'foreign.txt').read_text(), 'foreign replacement')
        self.assertEqual(self.version(), 'old')

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

    def test_sigkill_before_journal_and_during_copy_reclaims_only_registered_staging(self):
        for step in ('registered-staging', 'copied-file', 'validated-staging'):
            with self.subTest(step=step):
                parent = self.root / ('early-' + step); parent.mkdir()
                fixture_app(parent / 'PDF.app', 'old')
                unregistered = parent / ('.pdf-incoming.' + 'f' * 32 + '.app')
                unregistered.mkdir(); (unregistered / 'user.txt').write_text('never registered')
                ready = self.root / (step + '.ready')
                child = """import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import binary_update as update
def checkpoint(step):
 if step==sys.argv[4]:
  Path(sys.argv[5]).write_text(step)
  while True: time.sleep(1)
update.install(Path(sys.argv[2]),Path(sys.argv[3]),validate=lambda _:None,checkpoint=checkpoint)
"""
                process = subprocess.Popen([sys.executable, '-c', child, str(SCRIPTS), str(self.distribution),
                                            str(parent), step, str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
                        time.sleep(0.02)
                    self.assertTrue(ready.exists(), 'child did not reach the actual pre-journal copy boundary')
                    self.assertFalse((parent / '.pdf-update.json').exists())
                    self.assertEqual(len(list(parent.glob('.pdf-staging.*.json'))), 1)
                    os.kill(process.pid, signal.SIGKILL); process.wait(timeout=5)
                    self.assertEqual(process.returncode, -signal.SIGKILL)
                finally:
                    if process.poll() is None: process.kill(); process.wait()
                    process.communicate()
                result = subprocess.run([sys.executable, str(SCRIPTS / 'binary_update.py'), 'recover',
                                         '--destination', str(parent)], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((parent / 'PDF.app/Contents/MacOS/PDF').read_text(), 'old')
                self.assertEqual(list(parent.glob('.pdf-staging.*.json')), [])
                self.assertEqual(list(parent.glob('.pdf-incoming.*.app')), [unregistered])
                self.assertEqual((unregistered / 'user.txt').read_text(), 'never registered')
                # A normal retry also works and keeps the original history.
                updater.install(self.distribution, parent, validate=lambda _: None)
                self.assertEqual((parent / 'PDF.app/Contents/MacOS/PDF').read_text(), 'new')

    def test_sigkill_while_staging_marker_is_empty_or_partial_does_not_block_retry(self):
        for phase in ('staging-marker-empty', 'staging-marker-partial'):
            with self.subTest(phase=phase):
                parent = self.root / phase; parent.mkdir(); fixture_app(parent / 'PDF.app', 'old')
                ready = self.root / (phase + '.ready')
                code = """import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import binary_update as update
def checkpoint(phase):
 if phase==sys.argv[4]:
  Path(sys.argv[5]).write_text(phase)
  while True: time.sleep(1)
update.install(Path(sys.argv[2]),Path(sys.argv[3]),validate=lambda _:None,checkpoint=checkpoint)
"""
                process = subprocess.Popen([sys.executable, '-c', code, str(SCRIPTS), str(self.distribution),
                                            str(parent), phase, str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
                        time.sleep(.02)
                    self.assertTrue(ready.exists(), 'child did not reach actual incomplete marker write')
                    pending = next(parent.glob('.pdf-staging.*.pending'))
                    marker_bytes = pending.read_bytes()
                    if phase.endswith('empty'): self.assertEqual(marker_bytes, b'')
                    else:
                        self.assertGreater(len(marker_bytes), 0)
                        with self.assertRaises(json.JSONDecodeError): json.loads(marker_bytes)
                    self.assertFalse(list(parent.glob('.pdf-staging.*.json')))
                    os.kill(process.pid, signal.SIGKILL); process.wait(timeout=5)
                    self.assertEqual(process.returncode, -signal.SIGKILL)
                finally:
                    if process.poll() is None: process.kill(); process.wait()
                    process.communicate()
                orphan = next(parent.glob('.pdf-incoming.*.app'))
                result = subprocess.run([sys.executable, str(SCRIPTS / 'binary_update.py'), 'recover',
                                         '--destination', str(parent)], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(pending.read_bytes(), marker_bytes)
                self.assertTrue(orphan.is_dir())  # Not registered: never guess ownership.
                self.assertEqual((parent / 'PDF.app/Contents/MacOS/PDF').read_text(), 'old')
                updater.install(self.distribution, parent, validate=lambda _: None)
                self.assertEqual((parent / 'PDF.app/Contents/MacOS/PDF').read_text(), 'new')
                self.assertEqual(pending.read_bytes(), marker_bytes)
                self.assertEqual(list(parent.glob('.pdf-incoming.*.app')), [orphan])

    def test_staging_record_publication_refuses_replacement_and_existing_target(self):
        temporary = self.parent / 'marker.pending'
        destination = self.parent / 'marker.json'
        temporary.write_bytes(b'original'); temporary.chmod(0o600)
        expected = temporary.stat(); expected = (expected.st_dev, expected.st_ino)
        original = self.parent / 'marker-original'; temporary.rename(original)
        temporary.write_bytes(b'replacement'); temporary.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'mudou'):
            updater.publish_staging_record(self.parent, temporary, destination, expected)
        self.assertEqual(temporary.read_bytes(), b'replacement')
        temporary.unlink(); original.rename(temporary)
        destination.write_bytes(b'existing marker')
        with self.assertRaises(FileExistsError):
            updater.publish_staging_record(self.parent, temporary, destination, expected)
        self.assertEqual(destination.read_bytes(), b'existing marker')
        self.assertEqual(temporary.read_bytes(), b'original')

    def test_corrupt_committed_staging_marker_still_refuses_recovery(self):
        incoming, marker = self.staging_fixture()
        marker.write_bytes(b'{"schemaVersion":')
        with updater.installation_lock(self.parent):
            with self.assertRaises(json.JSONDecodeError): updater.recover(self.parent)
        self.assertEqual((incoming / 'partial').read_bytes(), b'unpublished bytes')
        self.assertEqual(self.version(), 'old')

    def staging_fixture(self):
        token = 'b' * 32
        incoming = self.parent / ('.pdf-incoming.' + token + '.app')
        incoming.mkdir(mode=0o700)
        marker = updater.register_staging(self.parent, token, incoming)
        (incoming / 'partial').write_bytes(b'unpublished bytes')
        return incoming, marker

    def test_staging_cleanup_refuses_live_runtime_lease_then_recovers(self):
        incoming, marker = self.staging_fixture()
        with updater.exclusive(incoming):
            with updater.installation_lock(self.parent):
                with self.assertRaisesRegex(ValueError, 'execução'):
                    updater.recover(self.parent)
            self.assertTrue(marker.exists()); self.assertTrue((incoming / 'partial').exists())
        with updater.installation_lock(self.parent): updater.recover(self.parent)
        self.assertFalse(incoming.exists()); self.assertFalse(marker.exists())
        self.assertEqual(self.version(), 'old')

    def test_staging_cleanup_preserves_directory_and_lease_replacements(self):
        incoming, marker = self.staging_fixture()
        moved = self.parent / 'preserve-original'; incoming.rename(moved)
        incoming.mkdir(); (incoming / 'foreign').write_text('foreign content')
        with updater.installation_lock(self.parent):
            with self.assertRaisesRegex(ValueError, 'identidade'): updater.recover(self.parent)
        self.assertEqual((incoming / 'foreign').read_text(), 'foreign content')
        self.assertTrue(marker.exists())
        updater.shutil.rmtree(incoming); moved.rename(incoming)
        lease = incoming / 'Contents/Resources/installation.lock'
        lease.rename(incoming / 'old-lease')
        lease.touch(); lease.chmod(0o444)
        with updater.installation_lock(self.parent):
            with self.assertRaisesRegex(ValueError, 'bloqueio'): updater.recover(self.parent)
        self.assertTrue(marker.exists()); self.assertTrue((incoming / 'partial').exists())

    def test_staging_cleanup_rejects_marker_links_fifo_and_parent_rebinding(self):
        incoming, marker = self.staging_fixture()
        original = marker.read_bytes(); marker.unlink()
        marker.symlink_to(self.preferences)
        with updater.installation_lock(self.parent):
            with self.assertRaisesRegex(ValueError, 'inseguro'): updater.recover(self.parent)
        marker.unlink(); os.mkfifo(marker, 0o600)
        with updater.installation_lock(self.parent):
            with self.assertRaisesRegex(ValueError, 'inseguro'): updater.recover(self.parent)
        marker.unlink(); record = json.loads(original); record['parentIdentity'] = '0:0'
        marker.write_text(json.dumps(record)); marker.chmod(0o600)
        with updater.installation_lock(self.parent):
            with self.assertRaisesRegex(ValueError, 'inválido'): updater.recover(self.parent)
        self.assertEqual(self.preferences.read_bytes(), b'private preferences unchanged')
        self.assertTrue((incoming / 'partial').exists())

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

    def test_fixture_cleanup_retries_busy_only_on_the_owned_image(self):
        image = self.root / 'fixture.dmg'; image.touch()
        device = '/dev/disk912'
        info = plistlib.dumps({'images': [{'image-path': str(image),
                            'system-entities': [{'dev-entry': device}]}]})
        attempts = []
        def run(command, **kwargs):
            if command[1] == 'info':
                return subprocess.CompletedProcess(command, 0, info, b'')
            attempts.append(command)
            return subprocess.CompletedProcess(command, errno.EBUSY if len(attempts) == 1 else 0,
                                                b'', b'hdiutil: resource busy')
        with patch.object(subprocess, 'run', run), patch.object(time, 'sleep') as delay:
            detach_fixture_image(image, device)
        self.assertEqual(attempts, [['/usr/bin/hdiutil', 'detach', device]] * 2)
        delay.assert_called_once_with(1)
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, info, b'')) as runner:
            with self.assertRaisesRegex(RuntimeError, 'device changed'):
                detach_fixture_image(image, '/dev/disk913')
            self.assertEqual(runner.call_count, 1)  # No unrelated detach is issued.

    def test_fixture_cleanup_preserves_failures_and_never_ignores_persistent_busy(self):
        image = self.root / 'fixture.dmg'; image.touch()
        device = '/dev/disk912'
        info = plistlib.dumps({'images': [{'image-path': str(image),
                            'system-entities': [{'dev-entry': device}]}]})
        attempts = []
        def run(command, **kwargs):
            if command[1] == 'info':
                return subprocess.CompletedProcess(command, 0, info, b'')
            attempts.append(command)
            return subprocess.CompletedProcess(command, errno.EBUSY, b'', b'fixture remains busy')
        with patch.object(subprocess, 'run', run), patch.object(time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'status 16: fixture remains busy'):
                cleanup_fixture_image(image, device)
        self.assertEqual(len(attempts), 4)
        primary = AssertionError('original update recovery assertion')
        with patch(__name__ + '.detach_fixture_image', side_effect=RuntimeError('cleanup failed')):
            cleanup_fixture_image(image, device, primary)
        self.assertEqual(str(primary), 'original update recovery assertion')
        self.assertIn('cleanup failed', primary.__notes__[0])

    @unittest.skipUnless(sys.platform == 'darwin', 'real bounded macOS disk image full-disk test')
    def test_real_full_disk_during_update_can_recover_after_space_is_freed(self):
        image = self.root / 'bounded-full-disk.dmg'
        mount = self.root / 'volume'; mount.mkdir()
        subprocess.run(['/usr/bin/hdiutil', 'create', '-size', '32m', '-fs', 'HFS+', '-volname', 'PDFFaultFixture', str(image)],
                       check=True, capture_output=True, timeout=60)
        device = None
        try:
            attachment = subprocess.run(['/usr/bin/hdiutil', 'attach', '-plist', '-nobrowse',
                                         '-mountpoint', str(mount), str(image)],
                                        check=True, capture_output=True, timeout=60)
            entities = plistlib.loads(attachment.stdout)['system-entities']
            devices = [item['dev-entry'] for item in entities
                       if re.fullmatch(r'/dev/disk[0-9]+', item.get('dev-entry', ''))]
            self.assertEqual(len(devices), 1, 'fixture must identify its exact attached disk')
            device = devices[0]
            self.assertTrue(any(Path(item.get('mount-point', '')).resolve() == mount.resolve()
                                for item in entities), 'fixture mount must belong to the attached image')
            (mount / '.metadata_never_index').touch()
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
            if device is not None:
                cleanup_fixture_image(image, device, sys.exc_info()[1])


if __name__ == '__main__':
    unittest.main()
