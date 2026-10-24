"""Use the actual installed qpdf before packaging, then repeat inside the bundle."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'engine')]
from check_runtime import check_qpdf_crypto


@unittest.skipUnless(shutil.which('qpdf'), 'The actual qpdf executable is required.')
class RealQPDFCryptoTests(unittest.TestCase):
    def test_protected_input_upgrade_rejects_wrong_passwords_and_preserves_text(self):
        with tempfile.TemporaryDirectory(prefix='PDF qpdf integration ') as temporary:
            directory = Path(temporary)
            source = directory / 'plain.pdf'
            with fitz.open() as document:
                document.new_page().insert_text((72, 72), 'PDF portable verification')
                document.save(source)
            before = source.read_bytes()
            result = check_qpdf_crypto(directory, source, Path(shutil.which('qpdf')))
            self.assertEqual(result, {'aes128Authenticated': True, 'aes256Verified': True,
                                     'incorrectPasswordsRejected': True, 'independentTextVerified': True})
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual({path.name for path in directory.iterdir()},
                             {'plain.pdf', 'qpdf-aes128.pdf', 'qpdf-aes256.pdf'})


if __name__ == '__main__': unittest.main()
