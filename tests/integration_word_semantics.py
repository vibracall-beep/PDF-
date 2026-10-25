"""PDF→editable Word→LibreOffice PDF, inspecting actual rendered page content."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

import fitz
from docx import Document

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run


class WordSemanticsIntegrationTests(unittest.TestCase):
    def test_recurring_margins_and_multiline_body_survive_real_office_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source.pdf';word=root/'converted.docx';result=root/'roundtrip.pdf'
            with fitz.open() as doc:
                for index in range(3):
                    page=doc.new_page(width=612,height=792)
                    if index<2: page.insert_text((40,35),'Running report header',fontsize=10,fontname='hebo')
                    page.insert_text((40,140),f'Body for page {index+1}.\nSecond sentence retained.',fontsize=12)
                    page.insert_text((230,770),f'Page {index+1} of 3',fontsize=10)
                doc.save(source)
            original=source.read_bytes();run('word',[source],word);run('office',[word],result)
            with fitz.open(result) as doc:
                self.assertEqual(len(doc),3)
                for index,page in enumerate(doc):
                    text=page.get_text()
                    self.assertEqual(text.count(f'Body for page {index+1}.'),1)
                    self.assertEqual(text.count('Second sentence retained.'),1)
                    self.assertEqual(text.count(f'Page {index+1} of 3'),1)
                    self.assertEqual(text.count('Running report header'),1 if index<2 else 0)
                    self.assertAlmostEqual(page.rect.width,612,delta=0.1);self.assertAlmostEqual(page.rect.height,792,delta=0.1)
                    self.assertTrue(all(page.rect.contains(fitz.Rect(word[:4])) for word in page.get_text('words')))
            self.assertEqual(source.read_bytes(),original)
            self.assertFalse(list(root.glob('.pdf-output-*')))

    def test_custom_page_size_remains_exact_in_word_and_roundtrip_difference_is_reported(self):
        # LibreOffice's import of 500 pt wide pages can snap to ISO B5's
        # 176 mm width (~498.8976 pt). The Office XML must stay exact and the
        # real roundtrip must report, rather than hide, that renderer change.
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'custom.pdf';word=root/'custom.docx';output=root/'audit'
            with fitz.open() as doc:
                page=doc.new_page(width=500,height=700);page.insert_text((40,140),'Custom paper retains original content.')
                doc.save(source)
            run('word',[source],word)
            section=Document(word).sections[0]
            self.assertEqual(section.page_width.pt,500);self.assertEqual(section.page_height.pt,700)
            run('conversion-audit',[source,word],output)
            report=json.loads((output/'report.json').read_text());metric=report['metrics'];page=metric['pages'][0]
            with fitz.open(output/'roundtrip.pdf') as actual:
                size=[actual[0].rect.width,actual[0].rect.height]
                self.assertEqual(page['source_size'],[500,700]);self.assertEqual(page['converted_size'],size)
                deltas=[round(value-original,6) for value,original in zip(size,[500,700])]
                self.assertEqual(page['size_difference_pt'],deltas)
                matches=all(abs(delta)<=0.1 for delta in deltas)
                self.assertEqual(page['page_geometry_matches'],matches);self.assertEqual(metric['page_geometry_matches'],matches)
            self.assertEqual(metric['geometry_tolerance_pt'],0.1)
            self.assertEqual(metric['source_word_recall'],1)
            self.assertFalse(report['conformance_claim']);self.assertTrue(report['review_required'])
