"""Deterministic geometry/validation checks independent of installed OCR binaries."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
from scan_analysis import _segments, _read_words, source_mode
from scan_fixture import scanned_form


class ScanGeometryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.source=self.root/'scan.pdf';scanned_form(self.source)
        self.original=self.source.read_bytes()
    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original);self.tmp.cleanup()

    def test_fixture_is_actually_raster_not_hidden_text_or_vector_rules(self):
        with fitz.open(self.source) as doc:
            self.assertEqual(doc[0].get_text(),'');self.assertEqual(doc[0].get_drawings(),[])
            self.assertEqual(source_mode(doc[0],{}),'ocr')
            self.assertEqual(source_mode(doc[0],{'source':'vector'}),'vector')

    def test_rule_thickness_is_coalesced_without_unbounded_active_duplicates(self):
        image=Image.new('L',(700,900),255);drawing=ImageDraw.Draw(image)
        drawing.line((20,30,650,30),fill=0,width=5)
        drawing.line((20,800,650,800),fill=0,width=5)
        drawing.line((20,30,20,800),fill=0,width=5)
        drawing.line((650,30,650,800),fill=0,width=5)
        horizontal=_segments(image,2);vertical=_segments(image,2,vertical=True)
        self.assertEqual(len(horizontal),2);self.assertEqual(len(vertical),2)
        self.assertTrue(all(line['thickness']==5 for line in horizontal+vertical))

    def test_low_confidence_words_are_retained_for_review(self):
        tsv='level\tleft\ttop\twidth\theight\tconf\ttext\n5\t10\t20\t80\t15\t8.5\tUncertain\n'
        words=_read_words(tsv,500,600)
        self.assertEqual(words[0]['text'],'Uncertain');self.assertEqual(words[0]['confidence'],0.085)

    def test_malformed_tsv_is_refused_instead_of_creating_invented_coordinates(self):
        for source in ['not TSV','level\tleft\ttop\twidth\theight\tconf\ttext\n5\t10\n','level\tleft\ttop\twidth\theight\tconf\ttext\n5\tnan\t20\t80\t15\t70\tBad\n','level\tleft\ttop\twidth\theight\tconf\ttext\n5\t2000\t20\t80\t15\t70\tOutside\n']:
            with self.subTest(source=source),self.assertRaises(RuntimeError):_read_words(source,500,600)

    def test_invalid_options_fail_before_external_execution_or_publication(self):
        for index,options in enumerate([{'source':'invented'},{'ocr_dpi':0},{'ocr_dpi':True},{'min_confidence':101},{'language':'eng --evil'},{'ocr_psm':6.5}]):
            target=self.root/f'invalid-{index}.json'
            with patch('pdf_engine._external') as external,self.assertRaises(ValueError):run('form-detect',[self.source],target,options)
            external.assert_not_called();self.assertFalse(target.exists())

    def test_external_failure_is_atomic(self):
        target=self.root/'error.json'
        with patch('pdf_engine._external',side_effect=RuntimeError('OCR failed')),self.assertRaises(RuntimeError):run('form-detect',[self.source],target)
        self.assertFalse(target.exists());self.assertEqual(list(self.root.glob('.pdf-output-*')),[])

    def test_malformed_ocr_response_is_atomic(self):
        target=self.root/'bad-tsv.json'
        response=subprocess.CompletedProcess([],0,'not TSV','')
        with patch('pdf_engine._external',return_value=response),self.assertRaises(RuntimeError):run('form-detect',[self.source],target)
        self.assertFalse(target.exists())

    def test_missing_ocr_words_do_not_turn_printed_cells_into_blank_fields(self):
        target=self.root/'no-words.json'
        response=subprocess.CompletedProcess([],0,'level\tleft\ttop\twidth\theight\tconf\ttext\n','')
        with patch('pdf_engine._external',return_value=response):run('form-detect',[self.source],target)
        result=json.loads(target.read_text())
        self.assertEqual(len(result['fields']),2,'Only the blank Name box and checkbox remain; an unlabeled line is not inferred.')
        self.assertTrue(all(field['rect'][1]>200 for field in result['fields']))

    def test_vector_override_does_not_invoke_ocr(self):
        target=self.root/'vector.json'
        with patch('pdf_engine._external') as external:run('form-detect',[self.source],target,{'source':'vector'})
        external.assert_not_called()
        result=json.loads(target.read_text());self.assertEqual(result['fields'],[]);self.assertEqual(result['pages'][0]['source'],'vector')

if __name__=='__main__':unittest.main()
