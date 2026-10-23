import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io

spec=importlib.util.spec_from_file_location('install_verapdf',Path(__file__).with_name('install-verapdf.py'))
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


class ValidatorInstallTests(unittest.TestCase):
    def test_wrong_download_checksum_never_publishes(self):
        class Response(io.BytesIO): url=installer.URL
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(installer.urllib.request,'urlopen',return_value=Response(b'untrusted bytes')):
                with self.assertRaisesRegex(ValueError,'Checksum'): installer.install(temporary)
            self.assertEqual(list(Path(temporary).iterdir()),[])

    def test_existing_wrong_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/f'cli-{installer.VERSION}.jar';target.write_bytes(b'existing')
            with patch.object(installer.urllib.request,'urlopen',side_effect=AssertionError('No download expected')):
                with self.assertRaisesRegex(ValueError,'checksum'): installer.install(temporary)
            self.assertEqual(target.read_bytes(),b'existing')

    def test_existing_symlink_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/f'cli-{installer.VERSION}.jar';target.symlink_to('missing')
            with self.assertRaises(ValueError): installer.install(temporary)
            self.assertTrue(target.is_symlink())

if __name__=='__main__': unittest.main()
