"""Homebrew altinstall discovery links, plus an actual macOS signing regression."""
import ctypes
import os
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest

from package_binary import complete_python_frameworks, sign_if_needed


class PythonFrameworkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='PDF private framework ')
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name).resolve()
        self.framework = self.runtime / 'vendor/python@3.12/Frameworks/Python.framework'
        self.payload = self.framework / 'Versions/3.12'
        (self.payload / 'Resources').mkdir(parents=True)
        (self.payload / 'include/python3.12').mkdir(parents=True)
        (self.payload / 'Headers').symlink_to('include/python3.12')
        self.info = {
            'CFBundleExecutable': 'Python', 'CFBundlePackageType': 'FMWK',
            'CFBundleIdentifier': 'org.python.python', 'CFBundleName': 'Python',
            'CFBundleVersion': '3.12.15', 'CFBundleShortVersionString': '3.12.15',
        }
        self.write_info()
        # Structural fixture only. The macOS test replaces this header with a
        # real arm64 dylib before calling codesign or loading executable code.
        (self.payload / 'Python').write_bytes(struct.pack('<8I', 0xfeedfacf, 0x0100000c, 0, 6, 0, 0, 0, 0))

    def write_info(self):
        (self.payload / 'Resources/Info.plist').write_bytes(plistlib.dumps(self.info))

    def complete(self):
        return complete_python_frameworks(self.runtime, ['python@3.12', 'qpdf'])

    def test_missing_altinstall_links_are_restored_without_changing_payload(self):
        before = {path: path.read_bytes() for path in self.payload.rglob('*') if path.is_file()}
        self.assertEqual(len(self.complete()), 4)
        self.assertEqual(os.readlink(self.framework / 'Versions/Current'), '3.12')
        for name in ('Python', 'Resources', 'Headers'):
            link = self.framework / name
            self.assertEqual(os.readlink(link), 'Versions/Current/' + name)
            self.assertTrue(link.samefile(self.payload / name))
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual(self.complete(), [])

    def test_existing_valid_discovery_links_are_preserved(self):
        (self.framework / 'Versions/Current').symlink_to('3.12')
        (self.framework / 'Resources').symlink_to('Versions/3.12/Resources')
        old_inode = (self.framework / 'Resources').lstat().st_ino
        self.assertEqual(len(self.complete()), 2)
        self.assertEqual((self.framework / 'Resources').lstat().st_ino, old_inode)
        self.assertEqual(os.readlink(self.framework / 'Resources'), 'Versions/3.12/Resources')

    def test_conflicting_entries_and_external_links_are_not_overwritten(self):
        for kind in ('regular', 'wrong-version', 'external', 'fifo'):
            with self.subTest(kind=kind):
                path = self.framework / 'Python'
                if kind == 'regular': path.write_bytes(b'do not overwrite')
                elif kind == 'wrong-version': path.symlink_to('Versions/3.15/Python')
                elif kind == 'external': path.symlink_to('/opt/homebrew/opt/python@3.12/Python')
                else: os.mkfifo(path)
                before = path.lstat()
                with self.assertRaises(ValueError): self.complete()
                self.assertEqual(path.lstat().st_ino, before.st_ino)
                self.assertFalse(os.path.lexists(self.framework / 'Versions/Current'))
                path.unlink()

    def test_wrong_payload_metadata_and_extra_versions_fail_before_adding_links(self):
        for key, value in [('CFBundleExecutable', 'Other'), ('CFBundlePackageType', 'APPL'),
                           ('CFBundleVersion', '3.15.0')]:
            with self.subTest(key=key):
                old = self.info[key]; self.info[key] = value; self.write_info()
                with self.assertRaises(ValueError): self.complete()
                self.assertFalse(os.path.lexists(self.framework / 'Versions/Current'))
                self.info[key] = old; self.write_info()
        (self.framework / 'Versions/3.15').mkdir()
        with self.assertRaises(ValueError): self.complete()
        self.assertFalse(os.path.lexists(self.framework / 'Versions/Current'))

    def test_missing_or_external_payload_and_special_plist_are_refused(self):
        binary = self.payload / 'Python'
        binary.write_bytes(b'not a Mach-O')
        with self.assertRaises(ValueError): self.complete()
        binary.write_bytes(struct.pack('<8I', 0xfeedfacf, 0x0100000c, 0, 6, 0, 0, 0, 0))
        headers = self.payload / 'Headers'; headers.unlink(); headers.symlink_to(self.runtime)
        with self.assertRaises(ValueError): self.complete()
        headers.unlink(); headers.symlink_to('include/python3.12')
        info = self.payload / 'Resources/Info.plist'; info.unlink(); os.mkfifo(info)
        with self.assertRaises(ValueError): self.complete()
        self.assertFalse(os.path.lexists(self.framework / 'Versions/Current'))

    @unittest.skipUnless(sys.platform == 'darwin', 'real framework signing and loading require macOS')
    def test_real_framework_fails_before_repair_then_signs_verifies_and_loads(self):
        binary = self.payload / 'Python'
        subprocess.run(['/usr/bin/xcrun', 'clang', '-arch', 'arm64', '-dynamiclib',
                        '-install_name', '@rpath/Python.framework/Versions/3.12/Python',
                        '-o', str(binary), '-x', 'c', '-'],
                       input='int pdf_framework_fixture(void) { return 42; }\n', text=True,
                       check=True, capture_output=True, timeout=45)
        subprocess.run(['/usr/bin/lipo', str(binary), '-verify_arch', 'arm64'],
                       check=True, capture_output=True, timeout=45)
        incomplete = subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-',
                                     '--timestamp=none', str(self.framework)],
                                    capture_output=True, text=True, timeout=45)
        self.assertNotEqual(incomplete.returncode, 0)
        self.assertIn('bundle format', incomplete.stderr)
        self.assertEqual(len(self.complete()), 4)
        sign_if_needed(binary)
        sign_if_needed(self.framework, deep=True)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(self.framework)],
                       check=True, capture_output=True, timeout=45)
        loaded = ctypes.CDLL(str(self.framework / 'Python'))
        loaded.pdf_framework_fixture.restype = ctypes.c_int
        self.assertEqual(loaded.pdf_framework_fixture(), 42)


if __name__ == '__main__':
    unittest.main()
