"""Real Tesseract review/apply on scans, with adversarial source/geometry checks."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import fitz

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
from tests.scan_fixture import scanned_form


class OCRReviewIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.source=cls.root/'scan.pdf';scanned_form(cls.source)
        cls.original=cls.source.read_bytes()
        report=cls.root/'review.json'
        run('ocr-review',[cls.source],report,{'language':'eng'})
        cls.review=json.loads(report.read_text())

    @classmethod
    def tearDownClass(cls):
        assert cls.source.read_bytes()==cls.original
        cls.temp.cleanup()

    def output(self,name): return self.root/(self._testMethodName+name)

    def apply(self,review=None,corrections=None,**options):
        target=self.output('.pdf')
        run('ocr-apply',[self.source],target,dict(source_sha256=self.review['source_sha256'],review=review or self.review,corrections=corrections or [],**options))
        return target

    def test_real_words_have_source_geometry_and_confidence(self):
        self.assertEqual(self.review['page_count'],1)
        self.assertEqual(self.review['backend'],'tesseract')
        self.assertEqual(self.review['source_sha256'],hashlib.sha256(self.original).hexdigest())
        words={word['text']:word for word in self.review['words']}
        self.assertTrue({'Product','Amount','Apples','Oranges','12','34'}.issubset(words))
        for word in words.values():
            self.assertTrue(0<=word['confidence']<=1)
            self.assertTrue(fitz.Rect(0,0,500,650).contains(fitz.Rect(word['rect'])))
        self.assertTrue(fitz.Rect(40,110,220,150).contains(fitz.Rect(words['Apples']['rect'])))

    def test_corrected_layer_searches_without_changing_original_pixels(self):
        word=next(word for word in self.review['words'] if word['text']=='Apples')
        output=self.apply(corrections=[dict(id=word['id'],text='Pears')])
        with fitz.open(output) as after,fitz.open(self.source) as before:
            self.assertIn('Pears',after[0].get_text());self.assertNotIn('Apples',after[0].get_text())
            self.assertEqual(after[0].get_pixmap(dpi=144).samples,before[0].get_pixmap(dpi=144).samples)
            self.assertEqual(after[0].get_image_info()[0]['bbox'],before[0].get_image_info()[0]['bbox'])

    def test_private_review_file_applies_without_reencoding_in_the_client(self):
        output=self.output('.pdf')
        run('ocr-apply',[self.source],output,{'source_sha256':self.review['source_sha256'],'review_path':str(self.root/'review.json')})
        with fitz.open(output) as doc: self.assertIn('Oranges',doc[0].get_text())

    def test_forged_rectangle_and_rehashed_review_are_refused(self):
        review=copy.deepcopy(self.review);review['words'][0]['rect']=[0,0,100,100]
        unsigned={key:value for key,value in review.items() if key!='review_sha256'}
        review['review_sha256']=hashlib.sha256(json.dumps(unsigned,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError,'geometria'): self.apply(review=review)
        self.assertFalse(self.output('.pdf').exists())

    def test_duplicate_correction_and_geometry_injection_are_refused(self):
        word=self.review['words'][0];correction=dict(id=word['id'],text='Changed')
        for corrections in ([correction,correction],[dict(**correction,rect=[0,0,100,100])],[dict(id='unknown',text='Changed')]):
            with self.subTest(corrections=corrections),self.assertRaises(ValueError): self.apply(corrections=corrections)
            self.assertFalse(self.output('.pdf').exists())

    def test_missing_language_refuses_instead_of_silent_fallback(self):
        with self.assertRaisesRegex(ValueError,'idiomas'):
            run('ocr-review',[self.source],self.output('.json'),{'language':'eng+uninstalled_audit_language'})
        self.assertFalse(self.output('.json').exists())

    def test_searchable_source_is_not_given_a_duplicate_layer(self):
        searchable=self.apply()
        with self.assertRaisesRegex(ValueError,'duplicadas'):
            run('ocr-review',[searchable],self.output('.json'),{'language':'eng'})
        self.assertFalse(self.output('.json').exists())

    def test_encrypted_ocr_retains_protection_and_pixels(self):
        protected=self.output('-protected.pdf');password='OCR-review-audit'
        with fitz.open(self.source) as doc:
            doc.save(protected,encryption=fitz.PDF_ENCRYPT_AES_256,user_pw=password,owner_pw='OCR-owner-audit',permissions=fitz.PDF_PERM_PRINT|fitz.PDF_PERM_ACCESSIBILITY)
        report=self.output('.json');run('ocr-review',[protected],report,{'password':password,'language':'eng'})
        review=json.loads(report.read_text());output=self.output('.pdf')
        run('ocr-apply',[protected],output,{'password':password,'source_sha256':review['source_sha256'],'review_path':str(report)})
        with fitz.open(output) as after,fitz.open(protected) as before:
            self.assertTrue(after.needs_pass);self.assertTrue(after.authenticate(password));before.authenticate(password)
            self.assertEqual(after.permissions,before.permissions)
            self.assertEqual(after[0].get_pixmap().samples,before[0].get_pixmap().samples)
            self.assertIn('Product',after[0].get_text())

    def test_selected_rotated_page_keeps_crop_geometry_and_other_page(self):
        source=self.output('-source.pdf')
        with fitz.open(self.source) as doc:
            doc[0].set_rotation(90);doc.new_page(width=500,height=650).insert_text((30,40),'Unselected searchable page');doc.save(source)
        report=self.output('.json');run('ocr-review',[source],report,{'pages':'1','language':'eng'})
        review=json.loads(report.read_text());self.assertEqual(review['pages'][0]['width'],500);self.assertEqual(review['pages'][0]['height'],650)
        output=self.output('.pdf');run('ocr-apply',[source],output,{'source_sha256':review['source_sha256'],'review':review})
        with fitz.open(output) as after,fitz.open(source) as before:
            self.assertEqual(after[0].rotation,90)
            self.assertEqual(after[0].get_pixmap().samples,before[0].get_pixmap().samples)
            self.assertEqual(after[1].get_pixmap().samples,before[1].get_pixmap().samples)

