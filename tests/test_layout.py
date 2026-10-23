"""Document-layout, extraction and form-detection workflows."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import fitz
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.image = self.root / 'image.png'
        Image.new('RGB', (80, 40), (12, 180, 40)).save(self.image)
        self.source = self.root / 'source.pdf'
        with fitz.open() as doc:
            for index in range(4):
                page = doc.new_page(width=400, height=500)
                page.insert_text((40, 80), f'Original heading {index + 1}', fontsize=16)
                page.insert_image(fitz.Rect(220, 250, 340, 310), filename=str(self.image))
                page.draw_rect(fitz.Rect(40, 350, 200, 390), color=(0, 0, 1))
            doc.save(self.source)
        self.original = self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.tmp.cleanup()

    def test_split_selected_ranges_into_groups(self):
        directory = self.root / 'parts'
        run('split', [self.source], directory, {'groups': ['1-2', '4,3']})
        parts = sorted(directory.glob('*.pdf'))
        self.assertEqual(len(parts), 2)
        with fitz.open(parts[0]) as doc:
            self.assertEqual(len(doc), 2)
            self.assertIn('heading 1', doc[0].get_text())
            self.assertIn('heading 2', doc[1].get_text())
        with fitz.open(parts[1]) as doc:
            self.assertEqual(len(doc), 2)
            self.assertIn('heading 4', doc[0].get_text())
            self.assertIn('heading 3', doc[1].get_text())

    def test_embedded_image_extraction_preserves_image_dimensions(self):
        directory = self.root / 'embedded'
        run('jpg', [self.source], directory, {'mode': 'embedded'})
        images = sorted(directory.glob('*.jpg'))
        self.assertEqual(len(images), 1, 'The shared embedded image should be extracted once.')
        with Image.open(images[0]) as image:
            self.assertEqual(image.size, (80, 40))
            red, green, blue = image.getpixel((40, 20))
            self.assertGreater(green, red + 100)
            self.assertGreater(green, blue + 100)

    def test_image_pdf_obeys_paper_orientation_and_margin(self):
        target = self.root / 'landscape.pdf'
        run('images', [self.image], target, {'paper': 'a4', 'orientation': 'landscape', 'margin': 40})
        with fitz.open(target) as doc:
            page = doc[0]
            self.assertEqual((page.rect.width, page.rect.height), (842, 595))
            boxes = page.get_image_rects(page.get_images()[0][0])
            self.assertEqual(len(boxes), 1)
            rect = boxes[0]
            self.assertGreaterEqual(rect.x0, 39.9)
            self.assertGreaterEqual(rect.y0, 39.9)
            self.assertLessEqual(rect.x1, page.rect.width - 39.9)
            self.assertLessEqual(rect.y1, page.rect.height - 39.9)

    def test_detected_blank_fields_can_be_reviewed_then_created(self):
        report = self.root / 'detected.json'
        run('form-detect', [self.source], report, {'pages': '1'})
        detected = json.loads(report.read_text())
        self.assertTrue(detected['heuristic'])
        self.assertTrue(detected['review_required'])
        self.assertEqual(len(detected['fields']), 1)
        field = detected['fields'][0]
        self.assertEqual(field['page'], 1)
        self.assertEqual(field['type'], 'text')
        self.assertEqual(field['rect'], [40, 350, 200, 390])
        target = self.root / 'form.pdf'
        run('form-create', [self.source], target, {'fields': detected['fields']})
        with fitz.open(target) as doc:
            widgets = list(doc[0].widgets())
            self.assertEqual(len(widgets), 1)
            self.assertEqual(widgets[0].field_name, field['name'])

    def extract_blocks(self):
        report = self.root / 'layout.json'
        run('layout-extract', [self.source], report, {'pages': '1'})
        blocks = json.loads(report.read_text())
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['page'], 1)
        self.assertEqual(blocks[0]['text'], 'Original heading 1')
        return blocks

    def test_layout_translation_retains_images_vectors_and_unselected_pages(self):
        block = self.extract_blocks()[0]
        target = self.root / 'translated.pdf'
        edit = {**block, 'source_text': block['text'], 'text': 'Texto traduzido'}
        run('translate-layout', [self.source], target, {'edits': [edit]})
        with fitz.open(target) as doc:
            self.assertIn('Texto traduzido', doc[0].get_text())
            self.assertNotIn('Original heading 1', doc[0].get_text())
            self.assertIn('Original heading 2', doc[1].get_text())
            self.assertEqual(len(doc[0].get_images()), 1)
            self.assertTrue(any(drawing['rect'] == fitz.Rect(40, 350, 200, 390) for drawing in doc[0].get_drawings()))
            with fitz.open(self.source) as source:
                bounds = fitz.Rect(200, 240, 350, 320)
                self.assertEqual(doc[0].get_pixmap(clip=bounds).samples, source[0].get_pixmap(clip=bounds).samples)

    def test_layout_translation_rejects_overlapping_replacements(self):
        block = self.extract_blocks()[0]
        target = self.root / 'overlapping.pdf'
        first = {**block, 'source_text': block['text'], 'text': 'Primeira tradução'}
        second = {**block, 'source_text': block['text'], 'text': 'Segunda tradução'}
        with self.assertRaises(ValueError):
            run('translate-layout', [self.source], target, {'edits': [first, second]})
        self.assertFalse(target.exists())

    def test_layout_translation_refuses_changed_source(self):
        block = self.extract_blocks()[0]
        target = self.root / 'stale.pdf'
        with self.assertRaises(ValueError):
            run('translate-layout', [self.source], target, {'edits': [{**block, 'source_text': 'Another document', 'text': 'Tradução'}]})
        self.assertFalse(target.exists())

    def test_layout_translation_refuses_overflow(self):
        block = self.extract_blocks()[0]
        target = self.root / 'overflow.pdf'
        with self.assertRaises(ValueError):
            run('translate-layout', [self.source], target, {'edits': [{**block, 'source_text': block['text'], 'text': 'Texto traduzido muito longo ' * 100}]})
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
