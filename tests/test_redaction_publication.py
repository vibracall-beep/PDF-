"""Redaction publication boundaries exercised with actual staged PDFs."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

import fitz
from PIL import ImageCms

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import pdf_engine
from pdf_redaction import _icc_privacy_plan

SECRET = 'PRIVATE-68291'


def add_object(document, value, data=None):
    xref = document.get_new_xref(); document.update_object(xref, value)
    if data is not None: document.update_stream(xref, data, compress=False)
    return xref


def profile():
    data = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    for position in range(132, 132 + 12 * int.from_bytes(data[128:132], 'big'), 12):
        if data[position:position + 4] != b'desc': continue
        offset = int.from_bytes(data[position + 4:position + 8], 'big')
        length = int.from_bytes(data[offset + 20:offset + 24], 'big')
        start = offset + int.from_bytes(data[offset + 24:offset + 28], 'big')
        data[start:start + length] = (SECRET + ' ' * (length // 2 - len(SECRET))).encode('utf-16be')
    return bytes(data)


class RedactionPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='PDF redact publication ')
        self.root = Path(self.temporary.name); self.source = self.root / 'source.pdf'; self.target = self.root / 'target.pdf'

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('.pdf-output-*')))
        self.temporary.cleanup()

    def fixture(self, configure=None):
        with fitz.open() as document:
            page = document.new_page(); page.insert_text((40, 50), SECRET); page.insert_text((40, 180), 'PUBLIC-CONTENT')
            if configure: configure(document, page)
            document.save(self.source)
        self.original = self.source.read_bytes()

    def redact(self):
        pdf_engine.run('redact', [self.source], self.target, {'text': SECRET})

    def test_output_intent_and_indirect_filter_parameters_are_sanitized(self):
        def configure(document, page):
            parameters = add_object(document, '<< /Predictor 1 >>')
            filters = add_object(document, '[/ASCIIHexDecode /FlateDecode]')
            profile_xref = add_object(document, '<< /N 3 >>', zlib.compress(profile()).hex().encode() + b'>')
            document.xref_set_key(profile_xref, 'Filter', f'{filters} 0 R')
            document.xref_set_key(profile_xref, 'DecodeParms', f'[null {parameters} 0 R]')
            # /Type is optional: infer OutputIntent identity from the catalog,
            # also through an indirect array, not only from the type marker.
            output_intent = add_object(document, f'<< /S /GTS_PDFX /DestOutputProfile {profile_xref} 0 R /OutputConditionIdentifier ({SECRET}) /Info ({SECRET}) >>')
            intents = add_object(document, f'[{output_intent} 0 R]')
            document.xref_set_key(document.pdf_catalog(), 'OutputIntents', f'{intents} 0 R')
            resource = int(document.xref_get_key(page.xref, 'Resources')[1].split()[0])
            document.xref_set_key(resource, 'ColorSpace', f'<< /Profile [/ICCBased {profile_xref} 0 R] >>')
        self.fixture(configure); self.redact()
        with fitz.open(self.target) as document:
            self.assertEqual(_icc_privacy_plan(document), {})
            self.assertIn('PUBLIC-CONTENT', document[0].get_text())
            for xref in range(1, document.xref_length()):
                values = [document.xref_object(xref).encode()]
                if document.xref_is_stream(xref): values += [document.xref_stream(xref), document.xref_stream_raw(xref)]
                for value in values:
                    self.assertNotIn(SECRET.encode(), value); self.assertNotIn(SECRET.encode('utf-16be'), value)

    def test_expansive_icc_refused_before_rendering(self):
        def configure(document, page):
            profile_xref = add_object(document, '<< /N 3 >>', zlib.compress(b'x' * (17 * 1024**2)))
            document.xref_set_key(profile_xref, 'Filter', '/FlateDecode')
            document.xref_set_key(document.pdf_catalog(), 'OutputIntents', f'[<< /Type /OutputIntent /DestOutputProfile {profile_xref} 0 R >>]')
        self.fixture(configure)
        with patch('pdf_redaction._check_supported', side_effect=AssertionError('Renderer inspection must not run')) as render:
            with self.assertRaisesRegex(ValueError, 'ICC'): self.redact()
            render.assert_not_called()
        self.assertFalse(self.target.exists())

    def test_post_save_metadata_regression_is_not_published(self):
        self.fixture(); original_save = pdf_engine.save
        def inject_metadata(document, output, **kwargs):
            original_save(document, output, **kwargs)
            with fitz.open(output) as staged:
                staged.set_metadata({'subject': SECRET}); staged.saveIncr()
        with patch('pdf_engine.save', side_effect=inject_metadata):
            with self.assertRaisesRegex(ValueError, 'metadados'): self.redact()
        self.assertFalse(self.target.exists())

    def test_degenerate_hidden_text_refused_without_visual_resurrection(self):
        def configure(document, page):
            content = add_object(document, '<< >>', b'q 0 0 0 0 350 450 cm BT /helv 12 Tf (INVISIBLE-PRIVATE) Tj ET Q')
            document.xref_set_key(page.xref, 'Contents', '[' + ' '.join(f'{xref} 0 R' for xref in page.get_contents() + [content]) + ']')
        self.fixture(configure)
        with self.assertRaisesRegex(ValueError, 'degenerada'): self.redact()
        self.assertFalse(self.target.exists())


if __name__ == '__main__': unittest.main()
