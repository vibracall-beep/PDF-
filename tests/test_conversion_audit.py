"""Refuse malformed comparison inputs and measure real PDF differences."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import fitz
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
from document_layout import _comparison_metrics


class ConversionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'original.pdf'
        with fitz.open() as doc: doc.new_page(width=300,height=400).insert_text((30,50),'Original source text');doc.save(self.source)
        self.original=self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertFalse(list(self.root.glob('.pdf-output-*')));self.temp.cleanup()

    def test_malformed_office_xml_refuses_before_converter_or_publication(self):
        office=self.root/'bad.docx'
        with zipfile.ZipFile(office,'w') as archive: archive.writestr('word/document.xml','<document>PRIVATE_FRAGMENT')
        with patch('pdf_engine._external') as external,self.assertRaisesRegex(ValueError,'estrutura válida') as error:
            run('conversion-audit',[self.source,office],self.root/'audit')
        external.assert_not_called();self.assertNotIn('PRIVATE_FRAGMENT',str(error.exception));self.assertFalse((self.root/'audit').exists())

    def test_duplicate_zip_entries_and_entity_declarations_are_refused(self):
        for mode in ('duplicate','utf8-entity','utf16-entity'):
            duplicate=mode=='duplicate';office=self.root/('bad-'+mode+'.docx')
            with zipfile.ZipFile(office,'w') as archive,warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                value='<document/>' if duplicate else '<!DOCTYPE document [<!ENTITY e "private">]><document>&e;</document>'
                archive.writestr('word/document.xml',value.encode('utf-16' if mode=='utf16-entity' else 'utf-8'))
                if duplicate: archive.writestr('word/document.xml','<different/>')
            with self.subTest(mode=mode),patch('pdf_engine._external') as external,self.assertRaises(ValueError):
                run('conversion-audit',[self.source,office],self.root/'audit')
            external.assert_not_called();self.assertFalse((self.root/'audit').exists())

    def test_output_collision_keeps_directory_owner_and_source_unchanged(self):
        output=self.root/'audit';output.mkdir();marker=output/'marker';marker.write_text('concurrent owner')
        with self.assertRaises(ValueError): run('conversion-audit',[self.source,self.root/'none.docx'],output)
        self.assertEqual(marker.read_text(),'concurrent owner')

    def test_metrics_record_missing_pages_font_changes_and_off_page_text(self):
        with fitz.open() as original,fitz.open() as converted:
            original.new_page(width=300,height=400).insert_text((30,50),'Original source text',fontname='helv')
            original.new_page(width=300,height=400)
            page=converted.new_page(width=300,height=400);page.insert_text((30,50),'Original source text',fontname='cour')
            page.insert_text((30,450),'Overflow outside page',fontname='cour')
            metrics=_comparison_metrics(original,converted)
        self.assertEqual(metrics['source_pages'],2);self.assertEqual(metrics['converted_pages'],1)
        self.assertFalse(metrics['pages'][1]['converted_present'])
        self.assertGreater(metrics['pages'][0]['text_words_outside_page'],0)
        self.assertIn('Helvetica',metrics['font_name_differences']['only_source'])
        self.assertIn('Courier',metrics['font_name_differences']['only_converted'])
