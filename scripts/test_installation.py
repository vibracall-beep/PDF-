"""Portable installer integrity checks; no macOS behavior is simulated as passed."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

from install_files import identity, move_new

SCRIPTS = Path(__file__).resolve().parent


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf installer ')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def bundle(self, name, content):
        path = self.root / name
        path.mkdir()
        (path / 'content').write_text(content)
        return path

    def test_exclusive_move_preserves_identity_and_content(self):
        source = self.bundle('staged app', 'new app')
        expected = identity(source)
        target = self.root / 'PDF.app'
        self.assertEqual(move_new(source, target, expected), expected)
        self.assertEqual(identity(target), expected)
        self.assertEqual((target / 'content').read_text(), 'new app')
        self.assertFalse(source.exists())

    def test_existing_directory_file_and_symlinks_are_not_replaced(self):
        source = self.bundle('staged', 'new app')
        existing = self.bundle('existing', 'user data')
        plain = self.root / 'file'; plain.write_text('user file')
        link = self.root / 'link'; link.symlink_to(existing, target_is_directory=True)
        dangling = self.root / 'dangling'; dangling.symlink_to(self.root / 'missing')
        for target in (existing, plain, link, dangling):
            with self.subTest(target=target.name), self.assertRaises(OSError):
                move_new(source, target, identity(source))
        self.assertEqual((existing / 'content').read_text(), 'user data')
        self.assertEqual(plain.read_text(), 'user file')
        self.assertTrue(link.is_symlink() and dangling.is_symlink())
        self.assertEqual((source / 'content').read_text(), 'new app')

    def test_changed_source_is_preserved(self):
        source = self.bundle('PDF.app', 'original')
        expected = identity(source)
        source.rename(self.root / 'moved-original')
        replacement = self.bundle('PDF.app', 'replacement')
        with self.assertRaises(ValueError):
            move_new(replacement, self.root / 'backup', expected)
        self.assertEqual((replacement / 'content').read_text(), 'replacement')

    def test_source_symlink_is_rejected(self):
        original = self.bundle('original', 'user data')
        link = self.root / 'symlink'; link.symlink_to(original, target_is_directory=True)
        with self.assertRaises(ValueError):
            move_new(link, self.root / 'target', identity(original))
        self.assertEqual((original / 'content').read_text(), 'user data')

    def test_failed_activation_can_restore_original_without_deleting_new_bundle(self):
        installed = self.bundle('PDF.app', 'old app')
        staged = self.bundle('stage', 'new app')
        old_id, new_id = identity(installed), identity(staged)
        backup, failed = self.root / 'previous.app', self.root / 'failed.app'
        move_new(installed, backup, old_id)
        move_new(staged, installed, new_id)
        move_new(installed, failed, new_id)
        move_new(backup, installed, old_id)
        self.assertEqual((installed / 'content').read_text(), 'old app')
        self.assertEqual((failed / 'content').read_text(), 'new app')


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf source ')
        self.root = Path(self.temporary.name)
        (self.root / 'scripts').mkdir()
        (self.root / 'docs').mkdir()
        (self.root / 'engine').mkdir()
        (self.root / 'diagnostics').mkdir()
        (self.root / '.github/workflows').mkdir(parents=True)
        shutil.copy(SCRIPTS / 'package-source.sh', self.root / 'scripts/package-source.sh')
        (self.root / 'scripts/install-mac.sh').write_text('#!/bin/bash\nexit 0\n')
        (self.root / 'Package.swift').write_text('// source fixture\n')
        (self.root / 'docs/INSTALACAO.md').write_text('Documentação\n')
        (self.root / 'engine/engine.py').write_text('print("PDF")\n')
        (self.root / 'diagnostics/PDFKitDiagnosis.swift').write_text('// independent PDFKit fixture\n')
        (self.root / 'diagnostics/run_pdfkit_diagnostics.py').write_text('print("diagnostic measurement")\n')
        (self.root / '.github/workflows/pdfkit-diagnostics.yml').write_text(
            'run: xcrun swiftc diagnostics/PDFKitDiagnosis.swift\n')
        script = (SCRIPTS / 'install-from-github.sh').read_text()
        self.extractor = script.split("<<'PY'\n", 1)[1].split('\nPY', 1)[0]

    def tearDown(self):
        self.temporary.cleanup()

    def package(self, output):
        return subprocess.run(['bash', str(self.root / 'scripts/package-source.sh'), str(output)], capture_output=True, text=True, timeout=20)

    def extract(self, archive, output):
        return subprocess.run([sys.executable, '-c', self.extractor, str(archive), str(output)], capture_output=True, text=True, timeout=20)

    def archive(self, name, extra=None, special=None):
        files = {'PDF/Package.swift': b'// fixture', 'PDF/scripts/install-mac.sh': b'#!/bin/bash\nexit 0\n'}
        files.update(extra or {})
        manifest = ''.join(hashlib.sha256(content).hexdigest() + '  ' + path[4:] + '\n' for path, content in files.items()).encode()
        files['PDF/SHA256SUMS'] = manifest
        path = self.root / name
        with tarfile.open(path, 'w:gz') as archive:
            for filename, content in files.items():
                info = tarfile.TarInfo(filename); info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            if special is not None:
                archive.addfile(special)
        return path

    def test_archive_is_reproducible_and_manifest_matches_every_file(self):
        one, two = self.root / 'one.tar.gz', self.root / 'two.tar.gz'
        self.assertEqual(self.package(one).returncode, 0)
        self.assertEqual(self.package(two).returncode, 0)
        self.assertEqual(one.read_bytes(), two.read_bytes())
        with tarfile.open(one) as archive:
            names = set(archive.getnames())
            self.assertIn('PDF/docs/INSTALACAO.md', names)
            self.assertIn('PDF/.github/workflows/pdfkit-diagnostics.yml', names)
            self.assertIn('PDF/diagnostics/PDFKitDiagnosis.swift', names)
            self.assertIn('PDF/diagnostics/run_pdfkit_diagnostics.py', names)
            info = json.load(archive.extractfile('PDF/BUILD-INFO.json'))
            self.assertIsNone(info['commit'])
            manifest = archive.extractfile('PDF/SHA256SUMS').read().decode()
            covered = set()
            for line in manifest.splitlines():
                digest, name = line.split('  ', 1)
                covered.add('PDF/' + name)
                self.assertEqual(hashlib.sha256(archive.extractfile('PDF/' + name).read()).hexdigest(), digest)
            self.assertEqual(covered, names - {'PDF/SHA256SUMS'})
        destination = self.root / 'verified'
        result = self.extract(one, destination)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((destination / 'engine/engine.py').read_text(), 'print("PDF")\n')
        self.assertEqual((destination / 'diagnostics/PDFKitDiagnosis.swift').read_text(), '// independent PDFKit fixture\n')
        self.assertEqual((destination / 'diagnostics/run_pdfkit_diagnostics.py').read_text(), 'print("diagnostic measurement")\n')

    def test_existing_output_and_dangling_symlinks_are_preserved(self):
        output = self.root / 'existing.tar.gz'; output.write_bytes(b'user data')
        self.assertNotEqual(self.package(output).returncode, 0)
        self.assertEqual(output.read_bytes(), b'user data')
        link = self.root / 'dangling.tar.gz'; link.symlink_to(self.root / 'missing')
        self.assertNotEqual(self.package(link).returncode, 0)
        self.assertTrue(link.is_symlink())

    def test_secret_filename_patterns_and_caches_are_excluded(self):
        for name in ('.env.private', 'credentials.json', 'Credentials.JSON', 'private.P8', 'id_ed25519', 'vault.kdbx', '.DS_Store'):
            (self.root / 'engine' / name).write_text('excluded fixture')
        cache = self.root / 'engine/__pycache__'; cache.mkdir(); (cache / 'file.pyc').write_bytes(b'cache')
        for name in ('certificate.p12', 'certificate.PFX', '.env.private'):
            (self.root / 'diagnostics' / name).write_text('excluded diagnostic fixture')
        output = self.root / 'sources.tar.gz'
        self.assertEqual(self.package(output).returncode, 0)
        with tarfile.open(output) as archive:
            names = archive.getnames()
            self.assertEqual([name for name in names if name.startswith('PDF/engine/')], ['PDF/engine/engine.py'])
            self.assertEqual([name for name in names if name.startswith('PDF/diagnostics/')],
                             ['PDF/diagnostics/PDFKitDiagnosis.swift', 'PDF/diagnostics/run_pdfkit_diagnostics.py'])

    def test_source_symlink_and_fifo_are_rejected(self):
        link = self.root / 'engine/outside.py'; link.symlink_to(self.root / 'Package.swift')
        self.assertNotEqual(self.package(self.root / 'symlink.tar.gz').returncode, 0)
        link.unlink()
        fifo = self.root / 'engine/blocked.py'; os.mkfifo(fifo)
        self.assertNotEqual(self.package(self.root / 'fifo.tar.gz').returncode, 0)

    def test_extract_rejects_traversal_case_and_file_directory_collisions(self):
        malicious = (
            {'PDF/../../outside': b'x'},
            {'PDF/Case.txt': b'a', 'PDF/case.txt': b'b'},
            {'PDF/docs': b'file', 'PDF/docs/guide.md': b'nested'},
            {'PDF/Folder/one.txt': b'a', 'PDF/folder/two.txt': b'b'},
        )
        for index, extra in enumerate(malicious):
            output = self.root / f'bad-{index}'
            result = self.extract(self.archive(f'bad-{index}.tar.gz', extra), output)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_extract_rejects_symlinks_and_manifest_mismatch(self):
        link = tarfile.TarInfo('PDF/link'); link.type = tarfile.SYMTYPE; link.linkname = '/tmp/outside'
        for index, archive in enumerate((self.archive('link.tar.gz', special=link), self.archive('bad-manifest.tar.gz', {'PDF/SHA256SUMS': b'invalid'}))):
            output = self.root / f'rejected-{index}'
            self.assertNotEqual(self.extract(archive, output).returncode, 0)
            self.assertFalse(output.exists())

    def test_extract_preserves_existing_destination(self):
        output = self.root / 'already-present'; output.mkdir(); (output / 'user-file').write_text('preserve')
        result = self.extract(self.archive('valid.tar.gz'), output)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((output / 'user-file').read_text(), 'preserve')
        self.assertFalse((output / 'Package.swift').exists())


class DeadlineTests(unittest.TestCase):
    def test_exit_status_and_timeout_are_preserved(self):
        helper = [sys.executable, str(SCRIPTS / 'run-with-timeout.py')]
        result = subprocess.run(helper + ['--seconds', '2', '--', sys.executable, '-c', 'raise SystemExit(7)'], capture_output=True)
        self.assertEqual(result.returncode, 7)
        started = time.monotonic()
        result = subprocess.run(helper + ['--seconds', '0.1', '--', sys.executable, '-c', 'import time; time.sleep(30)'], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 124)
        self.assertLess(time.monotonic() - started, 12)


if __name__ == '__main__':
    unittest.main()
