"""Exercise the real Ghostscript PDF/X path with a CMYK output profile."""
from pathlib import Path
import hashlib
import shutil
import sys
import tempfile
import unittest
import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run


class PrintIntegration(unittest.TestCase):
    def test_pdfx_embeds_supplied_icc_and_preserves_page_text(self):
        executable = shutil.which('gs')
        self.assertIsNotNone(executable, 'Ghostscript is required for this integration suite')
        candidates = [Path('/usr/share/color/icc/ghostscript/default_cmyk.icc')]
        # Homebrew keeps profiles inside the versioned keg, including portable
        # copies whose wrapper location differs from the executable itself.
        if executable:
            base = Path(executable).resolve().parent.parent
            candidates += list((base / 'share/ghostscript').glob('*/iccprofiles/default_cmyk.icc'))
        candidates += list(Path('/opt/homebrew/share/ghostscript').glob('*/iccprofiles/default_cmyk.icc'))
        profile = next((path for path in candidates if path.is_file()), None)
        self.assertIsNotNone(profile, 'A real Ghostscript CMYK profile is required')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'source.pdf'; output = root / 'pdfx.pdf'
            with fitz.open() as document:
                document.new_page(width=400, height=500).insert_text((50, 80), 'Print integration retained text')
                document.save(source)
            original = source.read_bytes()
            run('pdfx', [source], output, {'icc_profile': str(profile)})
            with fitz.open(output) as document:
                self.assertEqual(len(document), 1)
                self.assertIn('Print integration retained text', document[0].get_text())
                info = document.xref_get_key(-1, 'Info')
                self.assertIn('PDF/X-3:2002', document.xref_object(int(info[1].split()[0])))
                intents = document.xref_get_key(document.pdf_catalog(), 'OutputIntents')
                intent = int(intents[1].strip('[]').split()[0])
                reference = document.xref_get_key(intent, 'DestOutputProfile')
                embedded = document.xref_stream(int(reference[1].split()[0]))
                self.assertEqual(hashlib.sha256(embedded).digest(), hashlib.sha256(profile.read_bytes()).digest())
            self.assertEqual(source.read_bytes(), original)
