"""Real OCR after conservative rule classification on enlarged raster text."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

import fitz

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
from tests.scan_preprocessing_fixture import scanned_prose
from tests.scan_fixture import scanned_form
from tests.scan_table_fixture import scanned_table


class ScanPreprocessingIntegrationTests(unittest.TestCase):
    def test_automatic_and_sparse_modes_preserve_real_table_and_three_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'form.pdf';scanned_form(source)
            original=source.read_bytes()
            for mode in (3,11):
                with self.subTest(segmentation=mode):
                    output=root/f'report-{mode}.json'
                    run('form-detect',[source],output,dict(source='ocr',language='eng',ocr_psm=mode))
                    report=json.loads(output.read_text())['pages'][0]
                    self.assertEqual([table['rows'] for table in report['tables']],
                                     [[['Product','Amount'],['Apples','12'],['Oranges','34']]])
                    self.assertEqual({field['label']:field['type'] for field in report['fields']},
                                     {'Name:':'text','Accept terms':'checkbox','Date:':'text'})
            self.assertEqual(source.read_bytes(),original)

    def test_automatic_and_sparse_modes_preserve_merged_cells_with_and_without_deskew(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for angle in (0,3.5):
                source=root/f'merged-{angle}.pdf';scanned_table(source,skew=angle)
                original=source.read_bytes()
                for mode in (3,11):
                    with self.subTest(segmentation=mode,angle=angle):
                        output=root/f'report-{angle}-{mode}.json'
                        run('form-detect',[source],output,dict(source='ocr',language='eng',ocr_psm=mode,ocr_deskew=bool(angle)))
                        report=json.loads(output.read_text())['pages'][0]
                        self.assertEqual(report['preprocessing']['applied'],bool(angle))
                        self.assertEqual(len(report['tables']),1)
                        table=report['tables'][0]
                        self.assertEqual(table['rows'],[['Merged header',None,'Units'],['Group','Apple','10'],[None,'Orange','20']])
                        self.assertEqual({(cell['row'],cell['column'],cell['row_span'],cell['column_span']) for cell in table['merges']},
                                         {(0,0,1,2),(1,0,2,1)})
                        self.assertEqual(report['fields'],[])
                        words={word['text'] for word in report['words']}
                        self.assertTrue({'Inventory','report','Review','every','value'}.issubset(words))
                self.assertEqual(source.read_bytes(),original)

    def test_enlarged_raster_prose_has_exact_body_words_and_no_invented_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'large-prose.pdf'
            lines=scanned_prose(source);original=source.read_bytes()
            for mode in (3,6,11):
                with self.subTest(segmentation=mode):
                    report_path=root/f'review-{mode}.json'
                    run('form-detect',[source],report_path,dict(source='ocr',language='eng',ocr_psm=mode))
                    report=json.loads(report_path.read_text())['pages'][0]
                    self.assertEqual(report['fields'],[])
                    self.assertEqual(report['tables'],[])
                    words=[word['text'] for word in report['words']]
                    # PSM6 assumes a uniform text block and may segment a large
                    # heading differently; all body text must still be retained.
                    # Sparse-text segmentation can omit a sentence's full stop;
                    # compare complete word tokens, never prefixes/substrings.
                    recognized=' '.join(re.findall(r'[A-Za-z0-9]+',' '.join(words)))
                    for line in lines:
                        expected=' '.join(re.findall(r'[A-Za-z0-9]+',line))
                        self.assertIn(' '+expected+' ',' '+recognized+' ')
                    if mode in (3,11): self.assertIn(' A reference for comparison ',' '+recognized+' ')
                    for word in report['words']:
                        self.assertTrue(fitz.Rect(0,0,1131,1600).contains(fitz.Rect(word['rect'])))
            self.assertEqual(source.read_bytes(),original)
