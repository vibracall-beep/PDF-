"""Explicit optional integration suite; requires external engines, never silently skips."""
from pathlib import Path
import sys
import tempfile
import unittest
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_html_render(self):
        source = self.root/'source.html'; source.write_text('<html><body><h1>PDF integration</h1></body></html>')
        out = self.root/'html.pdf'; run('html',[str(source)],out)
        with fitz.open(out) as doc: self.assertIn('PDF integration',doc[0].get_text())
    def test_office(self):
        from docx import Document
        source = self.root/'source.docx'; doc = Document(); doc.add_paragraph('Office integration'); doc.save(source)
        out = self.root/'office.pdf'; run('office',[str(source)],out)
        with fitz.open(out) as doc: self.assertIn('Office integration',doc[0].get_text())
    def test_excel_to_pdf(self):
        from openpyxl import Workbook
        source = self.root / 'source.xlsx'
        book = Workbook()
        book.active.append(['Product', 'Quantity'] + [f'Column {i}' for i in range(3, 31)])
        book.active.append(['Oranges', 42] + ['Test value'] * 27 + ['LastColumnValue'])
        book.save(source)
        book.close()
        out = self.root / 'excel.pdf'
        original = source.read_bytes()
        run('office', [str(source)], out, {'fit_width': True, 'landscape': True})
        self.assertEqual(source.read_bytes(), original)
        with fitz.open(out) as doc:
            self.assertEqual(len(doc), 1)
            self.assertGreater(doc[0].rect.width, doc[0].rect.height)
            text = ''.join(page.get_text() for page in doc)
            self.assertIn('LastColumnValue', text)
            self.assertIn('Oranges', text)
            self.assertIn('42', text)

    def test_powerpoint_to_pdf(self):
        from pptx import Presentation
        source = self.root / 'source.pptx'
        slides = Presentation()
        slide = slides.slides.add_slide(slides.slide_layouts[0])
        slide.shapes.title.text = 'Presentation integration'
        slides.save(source)
        out = self.root / 'powerpoint.pdf'
        run('office', [str(source)], out)
        with fitz.open(out) as doc:
            self.assertEqual(len(doc), 1)
            self.assertIn('Presentation integration', doc[0].get_text())

    def test_ocr_and_pdfa(self):
        source = self.root/'scan.pdf'
        with fitz.open() as doc:
            page = doc.new_page(); page.insert_text((72,100),'HELLO DOCUMENT RECOGNITION',fontsize=24)
            image = page.get_pixmap(dpi=180)
        with fitz.open() as doc:
            page = doc.new_page(); page.insert_image(page.rect,stream=image.tobytes('png')); doc.save(source)
        for operation in ['ocr','pdfa']:
            out = self.root/(operation+'.pdf'); run(operation,[str(source)],out,{'language':'eng'})
            with fitz.open(out) as doc:
                self.assertIn('HELLO',doc[0].get_text())
                if operation == 'pdfa': self.assertIn('pdfaid:part',doc.get_xml_metadata())
if __name__=='__main__': unittest.main()
