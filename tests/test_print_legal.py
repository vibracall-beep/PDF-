from pathlib import Path
import hashlib
import json
import shutil
import sys
import tempfile
import unittest

import fitz
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.pdf'
        with fitz.open() as document:
            page = document.new_page(width=400, height=500)
            page.insert_text((40, 60), 'Preserved original paragraph')
            annotation = page.add_text_annot((250, 100), 'Retain this note')
            annotation.update()
            widget = fitz.Widget(); widget.field_name = 'Name'; widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.field_value = 'Original'; widget.rect = fitz.Rect(40, 180, 200, 220)
            page.add_widget(widget)
            document.save(self.source)
        self.original = self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('.pdf-output-*')))
        self.temporary.cleanup()

    def output(self, name):
        return self.root / name

    def test_bates_unique_labels_preserve_content_and_fields(self):
        second = self.output('two.pdf')
        run('organize', [self.source], second, {'pages': '1,1'})
        target = self.output('bates.pdf')
        run('bates', [second], target, {'prefix': 'AÇÃO-', 'start': 97, 'digits': 4})
        with fitz.open(target) as result:
            self.assertIn('AÇÃO-0097', result[0].get_text())
            self.assertIn('AÇÃO-0098', result[1].get_text())
            for page in result:
                self.assertIn('Preserved original paragraph', page.get_text())
                self.assertEqual(next(page.widgets()).field_value, 'Original')
                self.assertEqual(next(page.annots()).info['content'], 'Retain this note')

    def test_stamp_preserves_original_and_refuses_overflow(self):
        target = self.output('stamp.pdf')
        run('stamp', [self.source], target, {'text': 'REVISÃO Ω', 'rect': [40, 280, 300, 340]})
        with fitz.open(target) as result:
            self.assertIn('REVISÃO', result[0].get_text())
            self.assertIn('Original', result[0].get_text())
        failed = self.output('overflow.pdf')
        with self.assertRaises(ValueError):
            run('stamp', [self.source], failed, {'text': 'LONG ' * 30, 'rect': [40, 280, 60, 300], 'font_size': 30})
        self.assertFalse(failed.exists())

    def test_print_boxes_marks_leave_widgets_notes_and_text(self):
        target = self.output('print.pdf')
        run('print-prepare', [self.source], target, {'trim_inset': 24, 'bleed': 9})
        with fitz.open(target) as result:
            page = result[0]
            self.assertEqual(list(page.trimbox), [24, 24, 376, 476])
            self.assertEqual(list(page.bleedbox), [15, 15, 385, 485])
            self.assertIn('Preserved original paragraph', page.get_text())
            self.assertEqual(next(page.widgets()).field_value, 'Original')
            self.assertEqual(len(list(page.annots())), 1)
            self.assertGreaterEqual(len(page.get_drawings()), 8)

    def test_invalid_print_geometry_publishes_nothing(self):
        for options in ({'bleed': 30, 'trim_inset': 5}, {'trim_inset': True}, {'crop_marks': 'false'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                run('print-prepare', [self.source], self.output('invalid.pdf'), options)
        self.assertFalse(self.output('invalid.pdf').exists())

    def test_preflight_measures_placed_image_resolution(self):
        raster = self.output('raster.png'); Image.new('RGB', (100, 200), 'blue').save(raster)
        source = self.output('image.pdf')
        with fitz.open(self.source) as document:
            document[0].insert_image(fitz.Rect(40, 250, 140, 450), filename=str(raster))
            document.save(source)
        target = self.output('preflight.json')
        run('print-preflight', [source], target, {})
        report = json.loads(target.read_text())
        self.assertFalse(report['independently_certified'])
        self.assertEqual(report['source_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(report['pages'][0]['images'][0]['dpi_x'], 72)
        self.assertIn('low-image-resolution', [item['code'] for item in report['findings']])

    def test_measurement_scale_and_area(self):
        target = self.output('measure.json')
        run('measure', [self.source], target, {'points': [[10, 10], [82, 10], [82, 82], [10, 82]], 'closed': True, 'scale': 100, 'unit': 'm'})
        report = json.loads(target.read_text())
        self.assertAlmostEqual(report['distance'], 4 * 2.54)
        self.assertAlmostEqual(report['area'], 2.54**2)

    def test_measurement_rejects_nonfinite_or_out_of_bounds(self):
        for point in ([float('nan'), 2], [401, 1], [True, 1]):
            with self.subTest(point=point), self.assertRaises(ValueError):
                run('measure', [self.source], self.output('invalid.json'), {'points': [[0, 0], point]})
        self.assertFalse(self.output('invalid.json').exists())

    def test_dossier_links_and_outlines_are_correct_and_inputs_unchanged(self):
        target = self.output('set.pdf')
        run('dossier', [self.source, self.source], target, {'titles': ['Primeiro', 'Segundo']})
        with fitz.open(target) as result:
            self.assertEqual(len(result), 3)
            self.assertEqual([row[2] for row in result.get_toc()], [2, 3])
            self.assertEqual([link['page'] for link in result[0].get_links()], [1, 2])
            self.assertEqual(next(result[1].widgets()).field_value, 'Original')
            self.assertEqual(next(result[2].widgets()).field_value, 'Original')

    def test_repeated_pages_preserve_internal_links_and_independent_fields(self):
        source = self.output('links.pdf')
        with fitz.open(self.source) as document:
            document.new_page(width=400, height=500)
            document[0].insert_link({'kind': fitz.LINK_GOTO, 'from': fitz.Rect(40, 100, 150, 120), 'page': 1})
            document.save(source)
        for operation in ('organize', 'extract-pages'):
            with self.subTest(operation=operation):
                target = self.output(operation + '-links.pdf')
                run(operation, [source], target, {'pages': '1,1,2'})
                with fitz.open(target) as result:
                    for index in (0, 1):
                        self.assertEqual(result[index].get_links()[0]['page'], 2)
                        self.assertEqual(next(result[index].widgets()).field_value, 'Original')
                    self.assertNotEqual(result[0].xref, result[1].xref)

    def test_protection_survives_legal_production(self):
        source = self.output('protected.pdf')
        with fitz.open(self.source) as document:
            document.save(source, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='secret', owner_pw='owner', permissions=fitz.PDF_PERM_PRINT)
        for operation, options in [('bates', {}), ('print-prepare', {}), ('dossier', {})]:
            with self.subTest(operation=operation):
                target = self.output(operation + '.pdf')
                run(operation, [source], target, {'password': 'secret', **options})
                with fitz.open(target) as result:
                    self.assertTrue(result.needs_pass)
                    self.assertFalse(result.authenticate('wrong'))
                    self.assertTrue(result.authenticate('secret'))
                    self.assertFalse(result.permissions & fitz.PDF_PERM_COPY)

    def test_pdfx_rejects_invalid_icc_and_encrypted_input(self):
        profile = self.output('fake.icc'); profile.write_bytes(b'x' * 128)
        with self.assertRaises(ValueError):
            run('pdfx', [self.source], self.output('invalid-x.pdf'), {'icc_profile': str(profile)})
        self.assertFalse(self.output('invalid-x.pdf').exists())


if __name__ == '__main__':
    unittest.main()
