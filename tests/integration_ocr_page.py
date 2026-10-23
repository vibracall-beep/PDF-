"""Actual Tesseract recognition; unavailable engines/languages are not skipped."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run


class OCRPageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'image.png'
        with fitz.open() as document:
            page=document.new_page(width=600,height=400)
            page.insert_text((60,100),'LOCAL OCR VERIFICATION',fontsize=30)
            page.insert_text((60,250),'Second line 12345',fontsize=24)
            page.get_pixmap(dpi=144).save(self.source)
            page.get_pixmap(dpi=144,alpha=True).save(self.root/'transparent.png')
        self.original=self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual(list(self.root.glob('.pdf-output-*')),[])
        self.tmp.cleanup()

    def test_real_words_coordinates_language_and_backend_match_the_image(self):
        target=self.root/'words.json';run('ocr-page',[self.source],target,{'language':'en'})
        result=json.loads(target.read_text());words={word['string']:word for word in result['observations']}
        self.assertEqual((result['version'],result['backend'],result['language'],result['width'],result['height']),(1,'tesseract','en',1200,800))
        for text in ('LOCAL','OCR','VERIFICATION','Second','line','12345'):self.assertIn(text,words)
        for word in result['observations']:
            box=word['boundingBox'];origin=box['origin'];size=box['size']
            self.assertTrue(0<=word['confidence']<=1)
            self.assertTrue(0<=origin['x']<origin['x']+size['width']<=1)
            self.assertTrue(0<=origin['y']<origin['y']+size['height']<=1)
        first=words['LOCAL']['boundingBox']['origin'];second=words['Second']['boundingBox']['origin']
        self.assertAlmostEqual(first['x'],0.1,delta=0.02)
        self.assertAlmostEqual(first['y'],0.75,delta=0.03)
        self.assertAlmostEqual(second['y'],0.375,delta=0.03)
        self.assertGreater(first['y'],second['y'],'Native text coordinates must start at the bottom, not at the image top.')

    def test_transparent_png_is_recognized_against_white(self):
        source=self.root/'transparent.png'
        with Image.open(source) as image:self.assertEqual(image.getpixel((0,0))[3],0)
        target=self.root/'transparent.json';run('ocr-page',[source],target,{'language':'en'})
        self.assertIn('VERIFICATION',[word['string'] for word in json.loads(target.read_text())['observations']])

    def test_real_blank_page_has_no_invented_text(self):
        source=self.root/'blank.png';Image.new('RGB',(600,400),'white').save(source)
        target=self.root/'blank.json';run('ocr-page',[source],target,{'language':'en'})
        result=json.loads(target.read_text())
        self.assertEqual(result['backend'],'tesseract');self.assertEqual(result['observations'],[])

    def test_missing_language_data_is_an_error_without_publication(self):
        empty=self.root/'empty-languages';empty.mkdir();target=self.root/'missing.json'
        with patch.dict(os.environ,{'TESSDATA_PREFIX':str(empty)}),self.assertRaisesRegex(RuntimeError,'Tesseract'):
            run('ocr-page',[self.source],target,{'language':'en'})
        self.assertFalse(target.exists())

    def test_cli_keeps_recognized_text_out_of_stdout_and_stderr(self):
        target=self.root/'private.json'
        environment=os.environ.copy();environment['PDF_OPTIONS_STDIN']='1'
        engine=Path(__file__).resolve().parents[1]/'engine'/'pdf_engine.py'
        process=subprocess.run([sys.executable,str(engine),'ocr-page',str(self.source),'--output',str(target)],
                               input=json.dumps({'language':'en'}),capture_output=True,text=True,env=environment,timeout=65)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertTrue(json.loads(process.stdout)['ok']);self.assertEqual(process.stderr,'')
        self.assertNotIn('VERIFICATION',process.stdout)
        self.assertIn('VERIFICATION',target.read_text())

    def test_portuguese_does_not_silently_fall_back_to_english_only(self):
        listed=subprocess.run(['tesseract','--list-langs'],capture_output=True,text=True,check=True,timeout=10)
        target=self.root/'portuguese.json'
        if 'por' in listed.stdout.splitlines():
            run('ocr-page',[self.source],target,{'language':'pt'})
            result=json.loads(target.read_text());self.assertEqual(result['language'],'pt')
            self.assertIn('VERIFICATION',[word['string'] for word in result['observations']])
        else:
            with self.assertRaisesRegex(RuntimeError,'por'):run('ocr-page',[self.source],target,{'language':'pt'})
            self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
