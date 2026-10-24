"""Pixel-level regressions for glyphs falsely classified as form/table rules."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import fitz
from PIL import Image, ImageOps

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from scan_analysis import analyze
from tests.scan_preprocessing_fixture import scanned_prose


class ScanPreprocessingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
    def tearDown(self): self.temporary.cleanup()

    def analyze_pixels(self, page, dpi=200):
        raster = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
        with Image.frombytes('L',(raster.width,raster.height),raster.samples) as rendered:
            expected = ImageOps.autocontrast(rendered,cutoff=.5)
        captured = []
        def no_words(arguments, **options):
            with Image.open(arguments[1]) as raster: captured.append(raster.copy())
            return subprocess.CompletedProcess(arguments,0,'level\tleft\ttop\twidth\theight\tconf\ttext\n','')
        report = analyze(page,1,dict(language='eng',ocr_dpi=dpi),no_words)
        self.assertEqual(len(captured),1)
        return expected,captured[0],report

    def test_prose_survives_enlarged_physical_page_without_false_empty_fields(self):
        for enlarged in (False,True):
            with self.subTest(enlarged=enlarged):
                source = self.root/f'prose-{enlarged}.pdf'
                scanned_prose(source,enlarged=enlarged)
                original = source.read_bytes()
                with fitz.open(source) as document:
                    self.assertEqual(document[0].get_text(),'')
                    self.assertEqual(document[0].get_drawings(),[])
                    before,after,report = self.analyze_pixels(document[0])
                    with before,after:
                        self.assertTrue(after.tobytes()==before.tobytes(),'OCR preprocessing altered prose pixels.')
                self.assertEqual(report['fields'],[])
                self.assertEqual(report['tables'],[])
                self.assertEqual(source.read_bytes(),original)

    def test_sans_serif_monospace_and_serif_glyphs_keep_every_pixel_at_four_sizes(self):
        # Missing OCR words must not justify deleting hollow glyphs or proposing
        # their interiors as fields. These are real font outlines, not mock boxes.
        for font in ('helv','hebo','tiro','tibo','cour','cobo'):
            for size in (12,24,48,72):
                with self.subTest(font=font,size=size), fitz.open() as drawing, fitz.open() as scanned:
                    page = drawing.new_page(width=1200,height=300)
                    page.insert_text((40,100),'Order form O D Q 0 8 B P R a b d e g o p q',fontname=font,fontsize=size)
                    page.insert_text((40,230),'Label Letters and words surrounding shapes',fontname=font,fontsize=size)
                    pixels = page.get_pixmap(dpi=200).tobytes('png')
                    page = scanned.new_page(width=1200,height=300)
                    page.insert_image(page.rect,stream=pixels)
                    before,after,report = self.analyze_pixels(page)
                    with before,after:
                        self.assertTrue(after.tobytes()==before.tobytes(),'OCR preprocessing altered glyph pixels.')
                    self.assertEqual(report['fields'],[])
                    self.assertEqual(report['tables'],[])

    def test_connected_stroke_is_preserved_while_a_separate_blank_rule_is_removed(self):
        for dpi in (120,200,400):
            with self.subTest(dpi=dpi), fitz.open() as drawing:
                page = drawing.new_page(width=300,height=260)
                # The two horizontal strokes have equal dimensions. Only the
                # upper one is attached to vertical ink, as in an L or T glyph.
                page.draw_line((50,100),(200,100),width=1.5)
                page.draw_line((125,65),(125,100),width=1.5)
                page.draw_line((50,200),(200,200),width=1.5)
                before,after,_ = self.analyze_pixels(page,dpi=dpi)
                scale=dpi/72
                with before,after:
                    connected=(round(40*scale),round(55*scale),round(210*scale),round(110*scale))
                    with before.crop(connected) as original,after.crop(connected) as retained:
                        self.assertTrue(retained.tobytes()==original.tobytes(),'An attached stroke was erased as a blank rule.')
                    blank=(round(60*scale),round(199*scale),round(190*scale),round(201*scale))
                    with before.crop(blank) as original,after.crop(blank) as removed:
                        self.assertLess(original.getextrema()[0],180)
                        self.assertEqual(removed.getextrema(),(255,255))

    def test_heavy_closed_shape_is_not_erased_or_invented_as_a_checkbox(self):
        with fitz.open() as drawing:
            page = drawing.new_page(width=200,height=200)
            page.draw_rect(fitz.Rect(60,60,80,80),width=4)
            before,after,report = self.analyze_pixels(page)
            with before,after:
                self.assertTrue(after.tobytes()==before.tobytes(),'An ambiguous heavy border was erased.')
            self.assertEqual(report['fields'],[])
            self.assertEqual(report['tables'],[])
