"""Real Tesseract on unruled, skewed text and low-contrast image-only pages."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

import fitz

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
from scan_analysis import elements
from tests.scan_text_skew_fixture import scanned_text,LINES


class TextDeskewIntegrationTests(unittest.TestCase):
    def test_low_contrast_text_without_grid_is_recognized_and_conserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for low_contrast,angle in ((False,3.5),(True,-4.2)):
                with self.subTest(low_contrast=low_contrast,angle=angle):
                    source=root/f'original-{angle}.pdf';scanned_text(source,angle=angle,low_contrast=low_contrast)
                    original=source.read_bytes();output=root/f'analysis-{angle}.json'
                    run('form-detect',[source],output,dict(source='ocr',language='eng',ocr_deskew=True))
                    report=json.loads(output.read_text())['pages'][0]
                    self.assertTrue(report['preprocessing']['applied'])
                    self.assertEqual(report['preprocessing']['status'],'text-line-projection-evidence')
                    self.assertAlmostEqual(report['preprocessing']['rotation_degrees'],-angle,delta=.3)
                    self.assertEqual(report['tables'],[]);self.assertEqual(report['fields'],[])
                    recognized=' '.join(re.findall(r'[A-Za-z0-9]+',' '.join(word['text'] for word in report['words'])))
                    for line in LINES:
                        self.assertIn(' '.join(re.findall(r'[A-Za-z0-9]+',line)),recognized)
                    exported=elements(report)
                    self.assertEqual(Counter(word['text'] for word in report['words']),
                        Counter(span['text'].strip() for item in exported for line in item['lines'] for span in line['spans']))
                    self.assertEqual(source.read_bytes(),original)
    def test_protected_review_and_apply_preserve_image_permissions_and_source_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'scan.pdf';scanned_text(source,angle=-3)
            protected=root/'protected.pdf';password='text-deskew-owner'
            run('protect',[source],protected,dict(new_password=password));original=protected.read_bytes()
            review_path=root/'review.json'
            run('ocr-review',[protected],review_path,dict(password=password,language='eng',ocr_deskew=True))
            review=json.loads(review_path.read_text())
            self.assertEqual(review['pages'][0]['preprocessing']['status'],'text-line-projection-evidence')
            target=root/'searchable.pdf'
            run('ocr-apply',[protected],target,dict(password=password,source_sha256=review['source_sha256'],review_path=str(review_path)))
            with fitz.open(protected) as before,fitz.open(target) as after:
                self.assertTrue(after.needs_pass);self.assertTrue(after.authenticate(password));before.authenticate(password)
                self.assertEqual(before.permissions,after.permissions)
                self.assertEqual(before[0].get_pixmap(dpi=144).samples,after[0].get_pixmap(dpi=144).samples)
                text=after[0].get_text();self.assertIn('invoice',text);self.assertIn('36',text)
            review['pages'][0]['preprocessing']['rotation_degrees']=0
            unsigned={key:value for key,value in review.items() if key!='review_sha256'}
            review['review_sha256']=hashlib.sha256(json.dumps(unsigned,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            refused=root/'forged.pdf'
            with self.assertRaises(ValueError):
                run('ocr-apply',[protected],refused,dict(password=password,source_sha256=review['source_sha256'],review=review))
            self.assertFalse(refused.exists());self.assertEqual(protected.read_bytes(),original)


if __name__=='__main__':unittest.main()
