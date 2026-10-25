"""Direct tool routes, rendered alpha, numbering geometry and protected outputs."""
from pathlib import Path
import sys
import tempfile
import unittest

import fitz
from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run


class VisualSignatureNumberingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.pdf'
        with fitz.open() as document:
            for number in range(3):
                page = document.new_page(width=400, height=550)
                page.insert_text((35, 80), f'Original page {number + 1}', fontsize=14)
                page.draw_rect((20, 160, 220, 300), color=None, fill=(.2, .4, .7))
            document.save(self.source)
        self.original = self.source.read_bytes()
        self.signature = self.root / 'signature.png'
        with Image.new('RGBA', (40, 20), (255, 255, 255, 0)) as image:
            ImageDraw.Draw(image).rectangle((4, 8, 35, 11), fill=(220, 20, 60, 255))
            image.save(self.signature)
        self.original_image = self.signature.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.signature.read_bytes(), self.original_image)
        self.assertEqual(list(self.root.glob('.pdf-output-*')), [])
        self.temporary.cleanup()

    def test_visual_signature_preserves_transparency_page_selection_and_other_pages(self):
        output = self.root / 'signed.pdf'
        run('signature', [self.source], output, {'image': str(self.signature), 'pages': '2', 'rect': [50, 200, 170, 260], 'opacity': .5})
        with fitz.open(self.source) as before, fitz.open(output) as after:
            self.assertEqual(len(after), 3)
            for index in (0, 2):
                self.assertEqual(before[index].get_pixmap().samples, after[index].get_pixmap().samples)
            self.assertEqual(before[1].get_text(), after[1].get_text())
            images = after[1].get_image_info()
            self.assertEqual(len(images), 1)
            self.assertEqual(tuple(images[0]['bbox']), (50, 200, 170, 260))
            self.assertEqual(list(after[1].widgets() or []), [], 'A visual mark must not claim a certificate.')
            old, new = before[1].get_pixmap(), after[1].get_pixmap()
            self.assertEqual(old.pixel(52, 202), new.pixel(52, 202), 'Transparent signature margins changed the PDF.')
            self.assertNotEqual(old.pixel(90, 230), new.pixel(90, 230))
            for actual, expected in zip(new.pixel(90, 230), (135, 61, 119)):
                self.assertLessEqual(abs(actual - expected), 3)

    def test_visual_signature_on_protected_cropped_rotated_page_preserves_permissions(self):
        protected = self.root / 'protected.pdf'
        with fitz.open(self.source) as document:
            document[0].set_cropbox(fitz.Rect(10, 10, 390, 540))
            document[0].set_rotation(90)
            document.save(protected, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='visual-reader', owner_pw='visual-owner',
                          permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_ACCESSIBILITY)
        original = protected.read_bytes()
        output = self.root / 'protected-signed.pdf'
        run('signature', [protected], output, {'password': 'visual-reader', 'image': str(self.signature), 'pages': '1', 'rect': [40, 180, 160, 240]})
        with fitz.open(protected) as before, fitz.open(output) as after:
            self.assertTrue(after.needs_pass)
            self.assertFalse(after.authenticate('wrong'))
            self.assertTrue(after.authenticate('visual-reader')); before.authenticate('visual-reader')
            self.assertEqual(after.permissions, before.permissions)
            self.assertEqual(after[0].rotation, 90); self.assertEqual(after[0].cropbox, before[0].cropbox)
            self.assertEqual(len(after[0].get_image_info()), 1)
            for index in (1, 2): self.assertEqual(after[index].get_pixmap().samples, before[index].get_pixmap().samples)
        self.assertEqual(protected.read_bytes(), original)

    def test_image_watermark_uses_its_default_opacity_and_explicit_layer(self):
        for overlay in (True, False):
            target = self.root / f'watermark-{overlay}.pdf'
            run('watermark', [self.source], target, {'image': str(self.signature), 'rect': [50, 200, 170, 260], 'pages': '1', 'overlay': overlay})
            with fitz.open(self.source) as before, fitz.open(target) as after:
                old, new = before[0].get_pixmap(), after[0].get_pixmap()
                self.assertEqual(old.pixel(52, 202), new.pixel(52, 202))
                if overlay:
                    for actual, expected in zip(new.pixel(90, 230), (110, 73, 136)):
                        self.assertLessEqual(abs(actual - expected), 3)
                else:
                    area = fitz.Rect(50, 200, 170, 260)
                    self.assertEqual(before[0].get_pixmap(clip=area).samples, after[0].get_pixmap(clip=area).samples,
                                     'A watermark behind an opaque rectangle must remain behind it.')
                    # Introducing an alpha image can change RGB quantization of
                    # existing antialiased glyph edges by one level in MuPDF.
                    # Preserve that measured bound, while requiring exact
                    # equality in the opaque rectangle hiding the watermark.
                    a = Image.frombytes('RGB', (old.width, old.height), old.samples)
                    b = Image.frombytes('RGB', (new.width, new.height), new.samples)
                    with ImageChops.difference(a, b) as difference:
                        self.assertTrue(all(high <= 1 for _, high in difference.getextrema()))
                    a.close(); b.close()
                self.assertEqual(after[0].get_text(), before[0].get_text())

    def test_number_format_follows_selected_order_and_keeps_typography_and_position(self):
        output = self.root / 'numbered.pdf'
        run('numbers', [self.source], output, {'pages': '3,1', 'start': 7, 'format': 'Folha {n} / {total}',
            'position': 'bottom-right', 'margin': 25, 'font': 'cobo', 'font_size': 16, 'color': '#A02060'})
        with fitz.open(self.source) as before, fitz.open(output) as after:
            self.assertEqual(before[1].get_pixmap().samples, after[1].get_pixmap().samples)
            for index, expected in ((2, 'Folha 7 / 2'), (0, 'Folha 8 / 2')):
                spans = [span for block in after[index].get_text('dict')['blocks'] if block['type'] == 0
                         for line in block['lines'] for span in line['spans'] if span['text'] == expected]
                self.assertEqual(len(spans), 1)
                span = spans[0]
                self.assertEqual(span['font'], 'Courier-Bold'); self.assertAlmostEqual(span['size'], 16)
                self.assertEqual(span['color'], 0xA02060)
                self.assertAlmostEqual(span['origin'][1], 525)
                self.assertAlmostEqual(span['bbox'][2], 375, delta=.02)
                self.assertTrue(after[index].rect.contains(span['bbox']))
                self.assertIn(f'Original page {index + 1}', after[index].get_text())

    def test_numbering_top_center_and_overflow_rejection(self):
        target = self.root / 'center.pdf'
        run('numbers', [self.source], target, {'pages': '2', 'start': 0, 'format': '[{n}]', 'position': 'top-center', 'font_size': 18})
        with fitz.open(target) as document:
            area = document[1].search_for('[0]')[0]
            self.assertAlmostEqual((area.x0 + area.x1) / 2, 200, delta=.02)
            self.assertLess(area.y1, 70)
        for format_value in ('', ' ', 123, True, {'n': 1}, 'A' * 1000):
            with self.subTest(format=format_value), self.assertRaises(ValueError):
                run('numbers', [self.source], self.root / 'refused.pdf', {'format': format_value})
            self.assertFalse((self.root / 'refused.pdf').exists())

    def test_invalid_signature_does_not_publish_or_overwrite(self):
        target = self.root / 'refused.pdf'
        for options in ({}, {'image': str(self.signature), 'rect': [390, 200, 450, 260]},
                        {'image': str(self.signature), 'rect': [40, 200, 160, 260], 'opacity': -1}):
            with self.subTest(options=options), self.assertRaises(ValueError): run('signature', [self.source], target, options)
            self.assertFalse(target.exists())
        target.write_bytes(b'existing destination')
        with self.assertRaises((ValueError, FileExistsError)):
            run('signature', [self.source], target, {'image': str(self.signature), 'rect': [50, 200, 170, 260]})
        self.assertEqual(target.read_bytes(), b'existing destination')
