"""Exercise the installer's real tar command and exact post-extraction manifest."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import tempfile
import unittest

from binary_update import verify_manifest
from package_binary import archive, write_manifest


class BinaryArchiveExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='PDF binary archive ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'source distribution'
        self.app = self.source / 'PDF.app'
        (self.app / 'Contents/MacOS').mkdir(parents=True)
        (self.app / 'Contents/Resources').mkdir()
        (self.app / 'Contents/Resources/private-directory').mkdir()
        self.directories = {self.source: 0o755, self.app: 0o755,
                            self.app / 'Contents': 0o755, self.app / 'Contents/MacOS': 0o755,
                            self.app / 'Contents/Resources': 0o755,
                            self.app / 'Contents/Resources/private-directory': 0o700}
        for path, mode in self.directories.items(): path.chmod(mode)
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'local.pdf.desktop'}))
        self.executable = self.app / 'Contents/MacOS/PDF'
        self.executable.write_text('#!/bin/sh\nprintf "%s" "synthetic archive executable"\n')
        self.files = {self.app / 'Contents/Info.plist': 0o644, self.executable: 0o755,
                      self.app / 'Contents/Resources/installation.lock': 0o444,
                      self.app / 'Contents/Resources/private-fixture': 0o600}
        for path, mode in self.files.items():
            if not path.exists(): path.touch()
            path.chmod(mode)
        self.link = self.app / 'Contents/Resources/executable-link'
        self.link.symlink_to('../MacOS/PDF')
        write_manifest(self.source, 'b' * 40)
        self.package = self.root / 'archive with spaces.tar.gz'
        archive(self.source, self.package)
        script = Path(__file__).with_name('install-binary.sh').read_text()
        lines = [line for line in script.splitlines() if line.startswith('/usr/bin/tar ') and ' -C ' in line]
        self.assertEqual(len(lines), 1, 'Run the exact installer extraction statement, not a test copy.')
        self.extraction = lines[0]

    def extract(self, name, command=None):
        destination = self.root / name
        destination.mkdir(mode=0o700)
        environment = dict(os.environ, PDF_ARCHIVE=str(self.package), PDF_EXTRACT=str(destination))
        subprocess.run(['/bin/bash', '-c', 'set -euo pipefail\numask 077\n' + (command or self.extraction)],
                       env=environment, check=True, capture_output=True, timeout=15)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
        return destination / 'PDF-distribution'

    def test_authenticated_archive_roundtrip_preserves_modes_links_and_executable(self):
        checksum = self.package.with_suffix('.gz.sha256').read_text().split()[0]
        self.assertEqual(hashlib.sha256(self.package.read_bytes()).hexdigest(), checksum)
        extracted = self.extract('actual extraction')
        result = verify_manifest(extracted)
        self.assertEqual(result, json.loads((self.source / 'manifest.json').read_text()))
        for source, mode in self.files.items():
            path = extracted / source.relative_to(self.source)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
            self.assertEqual(path.read_bytes(), source.read_bytes())
            self.assertEqual(path.stat().st_uid, os.getuid())
        for source, mode in self.directories.items():
            path = extracted / source.relative_to(self.source)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
            self.assertEqual(path.stat().st_uid, os.getuid())
        self.assertEqual(os.readlink(extracted / self.link.relative_to(self.source)), '../MacOS/PDF')
        executable = extracted / self.executable.relative_to(self.source)
        executed = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=5)
        self.assertEqual(executed.stdout, 'synthetic archive executable')

    def test_historical_umask_loss_and_subsequent_mode_tampering_remain_rejected(self):
        previous = self.extract('old extraction', '/usr/bin/tar -xzf "$PDF_ARCHIVE" -C "$PDF_EXTRACT"')
        self.assertEqual(stat.S_IMODE((previous / self.executable.relative_to(self.source)).stat().st_mode), 0o700)
        with self.assertRaisesRegex(ValueError, 'manifesto'): verify_manifest(previous)
        corrected = self.extract('mode tampering')
        verify_manifest(corrected)
        (corrected / self.executable.relative_to(self.source)).chmod(0o700)
        with self.assertRaisesRegex(ValueError, 'manifesto'): verify_manifest(corrected)


if __name__ == '__main__': unittest.main()
