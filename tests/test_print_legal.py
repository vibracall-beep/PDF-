from pathlib import Path
import hashlib
import json
import re
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

    def alias_source(self, name='aliases.pdf', valid_form=True):
        source = self.output(name)
        with fitz.open(self.source) as document:
            document.new_page(width=400, height=500).insert_text((40, 60), 'Link destination')
            document[0].insert_link({'kind': fitz.LINK_GOTO, 'from': fitz.Rect(40, 100, 150, 120), 'page': 1})
            form_kind, form_value = document.xref_get_key(document.pdf_catalog(), 'AcroForm')
            self.assertIn(form_kind, ('dict', 'xref'))
            document.select([0, 0, 1])
            # select() removes AcroForm although the page widgets remain.
            # Keep a valid form tree in the external aliased-page fixture.
            if valid_form:
                document.xref_set_key(document.pdf_catalog(), 'AcroForm', form_value)
            document.set_toc([[1, 'Second occurrence', 2], [2, 'Nested branch', 2],
                              [3, 'Nested destination', 3], [1, 'Destination', 3]], collapse=0)
            document.save(source)
        with fitz.open(source) as document:
            self.assertEqual(document[0].xref, document[1].xref)
            self.assertEqual([link['page'] for link in document[0].get_links()], [2])
            for index in (0, 1):
                self.assertEqual(next(document[index].widgets()).field_value, 'Original')
        return source

    def assert_alias_structure(self, document, outline):
        self.assertEqual(len(document), 3)
        self.assertNotEqual(document[0].xref, document[1].xref)
        self.assertEqual(document.get_toc(), outline)
        self.assertFalse(any(entry[3].get('collapse', False) for entry in document.get_toc(simple=False)))
        widget_refs = []
        for index in (0, 1):
            page = document[index]
            self.assertIn('Preserved original paragraph', page.get_text())
            self.assertEqual([link['page'] for link in page.get_links() if link['kind'] == fitz.LINK_GOTO], [2])
            self.assertEqual([note.info['content'] for note in page.annots()], ['Retain this note'])
            widgets = list(page.widgets())
            self.assertEqual(len(widgets), 1)
            self.assertEqual(widgets[0].field_value, 'Original')
            widget_refs.append(widgets[0].xref)
        self.assertNotEqual(*widget_refs)
        kind, fields = document.xref_get_key(document.pdf_catalog(), 'AcroForm/Fields')
        self.assertEqual(kind, 'array')
        field_refs = {int(reference) for reference in re.findall(r'(\d+)\s+\d+\s+R', fields)}
        self.assertEqual(field_refs, set(widget_refs))

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
            line = page.get_drawings()[0]['items'][0]
            self.assertEqual(line[0], 'l')
            self.assertEqual(tuple(line[1]), (13, 24))
            self.assertEqual(tuple(line[2]), (4, 24))

    def test_print_preparation_refuses_cropped_selected_page_without_revealing_content(self):
        source = self.output('cropped.pdf')
        with fitz.open() as document:
            page = document.new_page(width=500, height=600)
            page.insert_text((10, 30), 'Hidden outside crop')
            page.insert_text((90, 120), 'Visible inside crop')
            page.set_cropbox(fitz.Rect(50, 60, 450, 550))
            document.new_page(width=500, height=600).insert_text((90, 120), 'Second visible page')
            document.save(source)
        original = source.read_bytes()
        with fitz.open(source) as baseline:
            cropped_pixels = baseline[0].get_pixmap().samples
            self.assertNotIn('Hidden outside crop', baseline[0].get_text())
        for marks in (True, False):
            target = self.output('cropped-refused-' + str(marks) + '.pdf')
            with self.subTest(marks=marks), self.assertRaisesRegex(ValueError, 'CropBox.*MediaBox'):
                run('print-prepare', [source], target, {'pages': '1', 'trim_inset': 24, 'bleed': 9, 'crop_marks': marks})
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), original)
        target = self.output('only-uncropped-page.pdf')
        run('print-prepare', [source], target, {'pages': '2', 'trim_inset': 24, 'bleed': 9})
        with fitz.open(target) as result:
            self.assertEqual(list(result[0].cropbox), [50, 60, 450, 550])
            self.assertEqual(result[0].get_pixmap().samples, cropped_pixels)
            self.assertNotIn('Hidden outside crop', result[0].get_text())
            self.assertEqual(list(result[1].trimbox), [24, 24, 476, 576])
        self.assertEqual(source.read_bytes(), original)

    def test_production_edits_only_selected_occurrence_of_an_aliased_page(self):
        source = self.alias_source()
        original = source.read_bytes()
        with fitz.open(source) as baseline:
            outline = baseline.get_toc()
            pixels = [page.get_pixmap().samples for page in baseline]
            boxes = [(list(page.trimbox), list(page.bleedbox)) for page in baseline]
        operations = (
            ('bates', {'prefix': 'AUDIT-', 'start': 1}, 'AUDIT-000001'),
            ('stamp', {'text': 'SELECTED', 'rect': [40, 280, 300, 340]}, 'SELECTED'),
            ('print-prepare', {'trim_inset': 24, 'bleed': 9}, None),
        )
        for operation, options, label in operations:
            for selected in (0, 1):
                with self.subTest(operation=operation, selected=selected + 1):
                    target = self.output(f'{operation}-alias-{selected}.pdf')
                    run(operation, [source], target, {'pages': str(selected + 1), **options})
                    with fitz.open(target) as result:
                        self.assert_alias_structure(result, outline)
                        for index in range(3):
                            if index == selected:
                                self.assertNotEqual(result[index].get_pixmap().samples, pixels[index])
                                if label:
                                    self.assertIn(label, result[index].get_text())
                                else:
                                    self.assertEqual(list(result[index].trimbox), [24, 24, 376, 476])
                            else:
                                self.assertEqual(result[index].get_pixmap().samples, pixels[index])
                                self.assertEqual((list(result[index].trimbox), list(result[index].bleedbox)), boxes[index])
                                if label:
                                    self.assertNotIn(label, result[index].get_text())
                    self.assertEqual(source.read_bytes(), original)

    def test_bates_aliases_receive_independent_numbers_on_all_pages(self):
        source = self.alias_source('bates-aliases.pdf')
        with fitz.open(source) as baseline:
            outline = baseline.get_toc()
        target = self.output('bates-all-aliases.pdf')
        run('bates', [source], target, {'prefix': 'ALL-', 'start': 7, 'digits': 3})
        with fitz.open(target) as result:
            self.assert_alias_structure(result, outline)
            for index, page in enumerate(result):
                self.assertIn(f'ALL-{index + 7:03}', page.get_text())
                for other in range(3):
                    if other != index:
                        self.assertNotIn(f'ALL-{other + 7:03}', page.get_text())

    def test_shared_normalization_preserves_alias_structure_for_existing_operations(self):
        source = self.alias_source('existing-operation-aliases.pdf')
        with fitz.open(source) as baseline:
            outline = baseline.get_toc()
            unselected_pixels = baseline[1].get_pixmap().samples
        for operation, options in (('rotate', {'degrees': 90}), ('crop', {'rect': [20, 20, 380, 480]})):
            with self.subTest(operation=operation):
                target = self.output(operation + '-alias.pdf')
                run(operation, [source], target, {'pages': '1', **options})
                with fitz.open(target) as result:
                    self.assert_alias_structure(result, outline)
                    self.assertEqual(result[1].get_pixmap().samples, unselected_pixels)
                    self.assertEqual(result[1].rotation, 0)
                    self.assertEqual(list(result[1].cropbox), [0, 0, 400, 500])

    def test_aliases_with_uncopiable_widgets_fail_instead_of_dropping_fields(self):
        source = self.alias_source('orphan-fields.pdf', valid_form=False)
        original = source.read_bytes()
        for operation in ('bates', 'stamp', 'print-prepare'):
            with self.subTest(operation=operation):
                target = self.output(operation + '-orphan-fields.pdf')
                with self.assertRaisesRegex(ValueError, 'campos.*estrutura'):
                    run(operation, [source], target, {'pages': '1'})
                self.assertFalse(target.exists())
                self.assertEqual(source.read_bytes(), original)

    def test_alias_normalization_preserves_complete_link_and_outline_dictionaries(self):
        base = self.alias_source('link-metadata-base.pdf')
        source = self.output('link-metadata.pdf')
        attributes = {
            'Contents': '(Accessible destination description)', 'C': '[1 0 0]',
            'Border': '[0 0 4]', 'F': '4', 'H': '/P', 'Lang': '(pt-BR)',
        }
        appearance = b'q 1 0 0 RG 4 w 2 2 156 36 re S Q'
        with fitz.open(base) as document:
            document[0].insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(40, 130, 200, 150), 'uri': 'https://example.org/audit'})
            document[2].insert_link({'kind': fitz.LINK_GOTO, 'from': fitz.Rect(40, 100, 200, 140), 'page': 0})
            action = document.get_new_xref()
            document.update_object(action, f'<< /S /GoTo /D [{document[0].xref} 0 R /XYZ null 500 null] '
                                          '/Next << /S /Named /N /NextPage >> /AuditAction (Keep action metadata) >>')
            document.xref_set_key(document.pdf_catalog(), 'AuditSharedAction', f'{action} 0 R')
            ap = document.get_new_xref()
            document.update_object(ap, '<< /Type /XObject /Subtype /Form /BBox [0 0 160 40] /Resources <<>> >>')
            document.update_stream(ap, appearance)
            for index in (0, 2):
                page = document.reload_page(document[index])
                for link in page.get_links():
                    reference = link['xref']
                    for key, value in attributes.items():
                        document.xref_set_key(reference, key, value)
                    document.xref_set_key(reference, 'P', f'{page.xref} 0 R')
                    document.xref_set_key(reference, 'AP', f'<< /N {ap} 0 R >>')
                    if index == 2:
                        document.xref_set_key(reference, 'A', f'{action} 0 R')
            outline_ref = document.get_outline_xrefs()[0]
            document.xref_set_key(outline_ref, 'Lang', '(pt-BR)')
            document.xref_set_key(outline_ref, 'AuditMarker', '(Keep outline metadata)')
            document.xref_set_key(outline_ref, 'A', f'{action} 0 R')
            document.save(source)
        original = source.read_bytes()
        with fitz.open(source) as baseline:
            outline = baseline.get_toc()
            expected_links = [[(link['kind'], link.get('page'), link.get('uri'), tuple(link['from']))
                               for link in page.get_links()] for page in baseline]
            expected_attributes = {key: baseline.xref_get_key(baseline[2].get_links()[0]['xref'], key) for key in attributes}
            pixels = baseline[2].get_pixmap().samples
        for operation, options in (('bates', {}), ('stamp', {'rect': [40, 280, 300, 340]}), ('print-prepare', {})):
            with self.subTest(operation=operation):
                target = self.output(operation + '-link-metadata.pdf')
                run(operation, [source], target, {'pages': '1', **options})
                with fitz.open(target) as result:
                    self.assert_alias_structure(result, outline)
                    self.assertEqual(result[2].get_pixmap().samples, pixels)
                    for index, page in enumerate(result):
                        actual_links = [(link['kind'], link.get('page'), link.get('uri'), tuple(link['from'])) for link in page.get_links()]
                        self.assertEqual(actual_links, expected_links[index])
                        for link in page.get_links():
                            reference = link['xref']
                            for key, value in expected_attributes.items():
                                self.assertEqual(result.xref_get_key(reference, key), value)
                            self.assertEqual(result.xref_get_key(reference, 'P'), ('xref', f'{page.xref} 0 R'))
                            ap_kind, ap_ref = result.xref_get_key(reference, 'AP/N')
                            self.assertEqual(ap_kind, 'xref')
                            self.assertEqual(result.xref_stream(int(ap_ref.split()[0])), appearance)
                    third_link = result[2].get_links()[0]['xref']
                    outline_ref = result.get_outline_xrefs()[0]
                    for reference in (third_link, outline_ref):
                        self.assertEqual(result.xref_get_key(reference, 'A/AuditAction'), ('string', 'Keep action metadata'))
                        self.assertEqual(result.xref_get_key(reference, 'A/Next/N'), ('name', '/NextPage'))
                        self.assertIn(f'[{result[1].xref} 0 R/XYZ null 500 null]', result.xref_get_key(reference, 'A/D')[1])
                    self.assertEqual(result.xref_get_key(outline_ref, 'Lang'), ('string', 'pt-BR'))
                    self.assertEqual(result.xref_get_key(outline_ref, 'AuditMarker'), ('string', 'Keep outline metadata'))
                    shared = result.xref_get_key(result.pdf_catalog(), 'AuditSharedAction')
                    self.assertEqual(shared[0], 'xref')
                    self.assertEqual(result.xref_get_key(int(shared[1].split()[0]), 'D')[1], f'[{result[0].xref} 0 R/XYZ null 500 null]')
                self.assertEqual(source.read_bytes(), original)

    def test_alias_normalization_preserves_indirect_dest_array_and_refuses_named_ambiguity(self):
        base = self.alias_source('destination-base.pdf')
        for named in (False, True):
            with self.subTest(named=named):
                source = self.output(f'destination-{named}.pdf')
                with fitz.open(base) as document:
                    document[2].insert_link({'kind': fitz.LINK_GOTO, 'from': fitz.Rect(40, 100, 200, 140), 'page': 0})
                    page = document.reload_page(document[2])
                    reference = page.get_links()[0]['xref']
                    destination = f'[{document[0].xref} 0 R /FitH null]'
                    document.xref_set_key(reference, 'A', 'null')
                    document.xref_set_key(reference, 'Contents', '(Keep direct destination description)')
                    if named:
                        document.xref_set_key(document.pdf_catalog(), 'Names', f'<< /Dests << /Names [(alias-target) {destination}] >> >>')
                        document.xref_set_key(reference, 'Dest', '(alias-target)')
                    else:
                        array_ref = document.get_new_xref()
                        document.update_object(array_ref, destination)
                        document.xref_set_key(reference, 'Dest', f'{array_ref} 0 R')
                    document.save(source)
                original = source.read_bytes()
                target = self.output(f'destination-result-{named}.pdf')
                if named:
                    with self.assertRaisesRegex(ValueError, 'destino.*(nomeado|ambiguidade)'):
                        run('bates', [source], target, {'pages': '1'})
                    self.assertFalse(target.exists())
                else:
                    run('bates', [source], target, {'pages': '1'})
                    with fitz.open(target) as result:
                        reference = result[2].get_links()[0]['xref']
                        self.assertEqual(result.xref_get_key(reference, 'Dest'), ('array', f'[{result[1].xref} 0 R/FitH null]'))
                        self.assertEqual(result.xref_get_key(reference, 'Contents'), ('string', 'Keep direct destination description'))
                self.assertEqual(source.read_bytes(), original)

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

    def test_area_refuses_crossed_or_degenerate_polygons(self):
        for points in ([[10, 10], [82, 82], [82, 10], [10, 82]],
                       [[10, 10], [20, 20], [30, 30]],
                       [[10, 10], [20, 10], [20, 10], [10, 20]]):
            with self.subTest(points=points), self.assertRaises(ValueError):
                run('measure', [self.source], self.output('invalid-area.json'), {'points': points, 'closed': True})
        self.assertFalse(self.output('invalid-area.json').exists())

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
