"""Independent validation against the pinned veraPDF engine, valid AND invalid PDFs."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
import pdf_standards as standards


class StandardsTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='pdf standards ')
        self.root=Path(self.temporary.name)
        self.source=self.root/'untagged.pdf'
        with fitz.open() as doc:
            doc.new_page().insert_text((50,70),'Independent PDF standards verification.')
            doc.save(self.source)
        self.original=self.source.read_bytes()

    def tearDown(self): self.temporary.cleanup()

    def test_actual_verapdf_accepts_tagged_pdfua1_and_keeps_human_review(self):
        source=Path(__file__).with_name('fixtures')/'pdfua1-minimal.pdf'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
            'f48a7b685c95bbf731854fee43aa507a569bc718d7ccddd3d54db7f4468fcf09')
        report=standards.validate_pdf(source,self.root/'positive-ua.json',{},standard='pdfua')
        self.assertTrue(report['compliant'],report['findings'])
        self.assertEqual(report['counts']['failedRules'],0)
        self.assertGreater(report['counts']['passedRules'],100)
        self.assertTrue(report['accessibility_preflight']['has_structure_tree'])
        self.assertTrue(report['manual_review_required'])
        self.assertFalse(report['accessibility_certified'])

    def test_actual_verapdf_rejects_untagged_pdfua_with_rules(self):
        report=standards.validate_pdf(self.source,self.root/'ua.json',{},standard='pdfua')
        self.assertFalse(report['compliant'])
        self.assertFalse(report['accessibility_preflight']['has_structure_tree'])
        self.assertFalse(report['accessibility_certified'])
        self.assertTrue(report['manual_review_required'])
        self.assertGreater(report['counts']['failedRules'],0)
        self.assertTrue(any('ISO 14289' in f['rule'] for f in report['findings']))
        self.assertTrue(all(f['severity']=='error' for f in report['findings']))
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_actual_verapdf_rejects_plain_pdfa(self):
        report=standards.validate_pdf(self.source,self.root/'a.json',{},standard='pdfa')
        self.assertFalse(report['compliant'])
        self.assertGreater(report['counts']['failedChecks'],0)
        self.assertEqual(report['input_sha256'],hashlib.sha256(self.original).hexdigest())

    def test_actual_verapdf_accepts_generated_pdfa2b(self):
        converted=self.root/'archive.pdf'
        run('pdfa',[self.source],converted,{'language':'eng'})
        report=standards.validate_pdf(converted,self.root/'valid.json',{'flavour':'2b'},standard='pdfa')
        self.assertTrue(report['compliant'],report['findings'])
        self.assertEqual(report['counts']['failedRules'],0)
        self.assertGreater(report['counts']['passedRules'],100)
        self.assertEqual(report['validator']['version'],'1.30.3')
        self.assertIn('isCompliant="true"',report['validator_xml'])
        self.assertFalse(report['network_access'])

    def test_metadata_or_marked_flag_does_not_create_accessibility(self):
        fake=self.root/'metadata-only.pdf'
        with fitz.open(self.source) as doc:
            doc.xref_set_key(doc.pdf_catalog(),'MarkInfo','<< /Marked true >>')
            doc.xref_set_key(doc.pdf_catalog(),'Lang','(pt-BR)')
            doc.save(fake)
        report=standards.validate_pdf(fake,self.root/'fake.json',{},standard='pdfua')
        self.assertFalse(report['compliant'])
        self.assertTrue(report['accessibility_preflight']['marked'])
        self.assertFalse(report['accessibility_preflight']['has_structure_tree'])

    def test_invalid_flavour_and_validator_checksum_fail_closed(self):
        with self.assertRaises(ValueError): standards.validate_pdf(self.source,self.root/'wrong.json',{'flavour':'ua1'},standard='pdfa')
        wrong=self.root/'wrong.jar';wrong.write_bytes(b'not official veraPDF')
        with patch.dict('os.environ',{'PDF_VERAPDF_JAR':str(wrong)}):
            with self.assertRaisesRegex(RuntimeError,'integridade'): standards.validator_paths()
        self.assertFalse((self.root/'wrong.json').exists())

    def test_empty_or_error_report_cannot_pass(self):
        preflight=standards.accessibility_preflight(self.source)
        for value in ('<report/>','<!DOCTYPE report [<!ENTITY x "unexpected">]><report>&x;</report>'):
            with self.assertRaises(RuntimeError): standards.parse_report(value,'pdfa','2b',preflight)

if __name__=='__main__': unittest.main()
