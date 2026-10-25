"""Authenticated storage estimates and the installer's actual native shell gate."""
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest

from binary_update import verify_manifest
from package_binary import archive, write_manifest
from test_binary_update import fixture_app, cleanup_fixture_image


class BinaryStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='PDF storage audit ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.distribution = self.root / 'distribution'; self.distribution.mkdir()
        fixture_app(self.distribution / 'PDF.app', 'new')
        (self.distribution / 'extra').write_bytes(b'outside app')
        (self.distribution / 'empty-directory').mkdir()
        (self.distribution / 'app-link').symlink_to('PDF.app')
        write_manifest(self.distribution, 'c' * 40)
        self.path = self.distribution / 'manifest.json'
        self.manifest = json.loads(self.path.read_text())

    def test_totals_cover_files_empty_directories_and_symlinks_without_following(self):
        # Count the actual fixture independently of the packager's walk. The
        # link and empty directory consume entries, but no duplicate app bytes.
        files = [self.distribution / 'extra',
                 self.distribution / 'PDF.app/Contents/MacOS/PDF',
                 self.distribution / 'PDF.app/Contents/Info.plist',
                 self.distribution / 'PDF.app/Contents/Resources/installation.lock']
        bundle_bytes = sum(path.stat().st_size for path in files[1:])
        self.assertEqual(self.manifest['storageRequirements'], {
            'schemaVersion': 1, 'distributionBytes': bundle_bytes + len(b'outside app'),
            'bundleBytes': bundle_bytes, 'distributionEntries': 11, 'bundleEntries': 7})
        self.assertEqual(verify_manifest(self.distribution), self.manifest)
        target = self.root / 'actual.tar.gz'; archive(self.distribution, target)
        with tarfile.open(target) as package:
            self.assertEqual(package.next().name, 'PDF-distribution')
            metadata = package.next()
            self.assertEqual(metadata.name, 'PDF-distribution/manifest.json')
            self.assertTrue(metadata.isfile())
            self.assertEqual(package.extractfile(metadata).read(), self.path.read_bytes())

    def test_legacy_manifest_remains_compatible_but_wrong_present_totals_are_rejected(self):
        legacy = dict(self.manifest); legacy.pop('storageRequirements')
        self.path.write_text(json.dumps(legacy))
        self.assertEqual(verify_manifest(self.distribution), legacy)
        variants = [None, [], {}, True, {'schemaVersion': 1}]
        for key, value in self.manifest['storageRequirements'].items():
            variants.append(dict(self.manifest['storageRequirements'], **{key: value + 1}))
            variants.append(dict(self.manifest['storageRequirements'], **{key: True}))
            variants.append(dict(self.manifest['storageRequirements'], **{key: str(value)}))
        for storage in variants:
            with self.subTest(storage=storage):
                self.path.write_text(json.dumps(dict(self.manifest, storageRequirements=storage)))
                with self.assertRaisesRegex(ValueError, 'estimativa de espaço'):
                    verify_manifest(self.distribution)

    @unittest.skipUnless(sys.platform == 'darwin', 'native macOS plutil/stat/bsdtar disk-space gate')
    def test_actual_native_preflight_accepts_valid_legacy_and_rejects_invalid_metadata(self):
        parent = self.root / 'Applications'; parent.mkdir()
        result = self.preflight(parent, self.manifest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Espaço verificado:', result.stdout)
        legacy = dict(self.manifest); legacy.pop('storageRequirements')
        result = self.preflight(parent, legacy, legacy_order=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Pacote anterior', result.stdout)
        # A missing optional estimate is permitted only in a valid schema-1
        # manifest; malformed roots must not take the compatibility branch.
        for invalid in (None, [], 'invalid', {}, {'schemaVersion': True},
                        dict(legacy, schemaVersion=1.0), dict(legacy, schemaVersion=2)):
            result = self.preflight(parent, invalid)
            self.assertNotEqual(result.returncode, 0, invalid)
            self.assertNotIn('Pacote anterior', result.stdout)
        for value in (None, [], 'invalid', True,
                      dict(self.manifest['storageRequirements'], distributionBytes=-1),
                      dict(self.manifest['storageRequirements'], bundleBytes=True),
                      dict(self.manifest['storageRequirements'], distributionEntries='12'),
                      dict(self.manifest['storageRequirements'], schemaVersion=1.0),
                      dict(self.manifest['storageRequirements'], bundleBytes=1e3),
                      dict(self.manifest['storageRequirements'], distributionBytes=12884901889)):
            result = self.preflight(parent, dict(self.manifest, storageRequirements=value))
            self.assertNotEqual(result.returncode, 0, value)
            self.assertNotIn('Pacote anterior', result.stdout)

    @unittest.skipUnless(sys.platform == 'darwin', 'native BSD stat symlink behavior')
    def test_native_archive_size_measures_the_copied_target_of_a_symlink(self):
        payload = self.root / 'local payload.tar.gz'; payload.write_bytes(b'fixture-data-' * 1024)
        link = self.root / 'linked package'; link.symlink_to(payload.name)
        script = Path(__file__).with_name('install-binary.sh').read_text()
        functions = script.split('# PDF_SPACE_FUNCTIONS_BEGIN\n', 1)[1].split('# PDF_SPACE_FUNCTIONS_END', 1)[0]
        command = 'set -euo pipefail\nfail() { printf "%s\\n" "$*" >&2; exit 1; }\n' + functions + '\npdf_archive_bytes "$PDF_TEST_SOURCE"\n'
        for source in (payload, link):
            result = subprocess.run(['/bin/bash', '-c', command], env=dict(os.environ, PDF_TEST_SOURCE=str(source)),
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(int(result.stdout), payload.stat().st_size)
        # Size rejection uses the true target too; a sparse fixture allocates
        # no multi-GB payload and the installer never copies it.
        with payload.open('wb') as stream: stream.truncate(12884901889)
        result = subprocess.run(['/bin/bash', '-c', command], env=dict(os.environ, PDF_TEST_SOURCE=str(link)),
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('12 GiB', result.stderr)

    @unittest.skipUnless(sys.platform == 'darwin', 'bounded HFS image supplies real low-space destination')
    def test_actual_native_preflight_refuses_real_low_space_without_changing_existing_app(self):
        image = self.root / 'bounded-space.dmg'
        mount = self.root / 'volume'; mount.mkdir()
        subprocess.run(['/usr/bin/hdiutil', 'create', '-size', '32m', '-fs', 'HFS+', '-volname', 'PDFSpaceFixture', str(image)],
                       check=True, capture_output=True, timeout=60)
        device = None
        try:
            result = subprocess.run(['/usr/bin/hdiutil', 'attach', '-plist', '-nobrowse', '-mountpoint', str(mount), str(image)],
                                    check=True, capture_output=True, timeout=60)
            entities = plistlib.loads(result.stdout)['system-entities']
            devices = [item['dev-entry'] for item in entities if re.fullmatch(r'/dev/disk[0-9]+', item.get('dev-entry', ''))]
            self.assertEqual(len(devices), 1); device = devices[0]
            self.assertTrue(any(Path(item.get('mount-point', '')).resolve() == mount.resolve() for item in entities))
            (mount / '.metadata_never_index').touch()
            parent = mount / 'Applications'; parent.mkdir(); fixture_app(parent / 'PDF.app', 'existing')
            before = {path.relative_to(parent).as_posix(): path.read_bytes() for path in parent.rglob('*') if path.is_file()}
            result = self.preflight(parent, self.manifest)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Espaço insuficiente', result.stderr)
            after = {path.relative_to(parent).as_posix(): path.read_bytes() for path in parent.rglob('*') if path.is_file()}
            self.assertEqual(before, after)
            self.assertFalse(list(parent.glob('.pdf-incoming.*')))
            self.assertFalse(list(parent.glob('PDF.previous.*')))
        finally:
            if device is not None: cleanup_fixture_image(image, device, sys.exc_info()[1])

    def preflight(self, parent, manifest, legacy_order=False):
        # Exercise the production functions/gate verbatim, with real native
        # plutil, bsdtar, stat and df; no host Python or mocked free-space value.
        attempt = self.root / ('attempt-' + str(len(list(self.root.glob('attempt-*'))))); attempt.mkdir()
        self.path.write_text(json.dumps(manifest))
        package = attempt / 'package.tar.gz'
        if legacy_order:
            # Match the delivered 0.6 writer: recursion sorts the app before
            # manifest.json, so --fast-read must still locate late metadata.
            with tarfile.open(package, 'w:gz', dereference=False) as old:
                old.add(self.distribution, arcname='PDF-distribution', recursive=True)
            with tarfile.open(package) as old:
                members = old.getnames()
                self.assertGreater(members.index('PDF-distribution/manifest.json'), members.index('PDF-distribution/PDF.app/Contents/MacOS/PDF'))
        else:
            archive(self.distribution, package)
        script = Path(__file__).with_name('install-binary.sh').read_text()
        functions = script.split('# PDF_SPACE_FUNCTIONS_BEGIN\n', 1)[1].split('# PDF_SPACE_FUNCTIONS_END', 1)[0]
        gate = script.split('# PDF_STORAGE_CHECK_BEGIN\n', 1)[1].split('# PDF_STORAGE_CHECK_END', 1)[0]
        command = 'set -euo pipefail\numask 077\nfail() { printf "%s\\n" "$*" >&2; exit 1; }\n' + functions + gate
        environment = dict(os.environ, PDF_PARENT=str(parent), PDF_EXTRACT=str(attempt), PDF_ARCHIVE=str(package))
        return subprocess.run(['/bin/bash', '-c', command], env=environment, capture_output=True, text=True, timeout=20)


if __name__ == '__main__': unittest.main()
