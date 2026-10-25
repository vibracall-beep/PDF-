"""Real PDF resource graphs and ICC containers, independently parsed."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest

import fitz
from PIL import ImageCms

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run
from print_inspection import icc_description, inspect_structure, read_cmyk_profile


class PrintInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.assertFalse(list(self.root.glob('.pdf-output-*')))
        self.temporary.cleanup()

    def source(self, customize=None, name='source.pdf'):
        path = self.root / name
        with fitz.open() as document:
            page = document.new_page(width=400, height=500)
            page.insert_text((40, 60), 'Real print inspection text')
            if customize:
                customize(document, page)
            document.save(path)
        return path

    def report(self, source, **options):
        target = self.root / ('report-' + str(len(list(self.root.glob('report*')))) + '.json')
        run('print-preflight', [source], target, options)
        return json.loads(target.read_text())

    def resources(self, document, page):
        return int(document.xref_get_key(page.xref, 'Resources')[1].split()[0])

    def test_nested_form_resources_report_spots_overprint_and_transparency(self):
        def customize(document, page):
            function = document.get_new_xref()
            document.update_object(function, '<< /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [1 0.3 0 0] /N 1 >>')
            state = document.get_new_xref()
            document.update_object(state, '<< /Type /ExtGState /OP true /OPM 1 /ca 0.5 >>')
            form = document.get_new_xref()
            document.update_object(form, f'<< /Type /XObject /Subtype /Form /BBox [0 0 100 100] /Resources << /ColorSpace << /Brand [/Separation /Brand#20Blue /DeviceCMYK {function} 0 R] >> /ExtGState << /Ink {state} 0 R >> >> >>')
            document.update_stream(form, b'/Ink gs /Brand cs 1 scn 0 0 100 100 re f')
            document.xref_set_key(self.resources(document, page), 'XObject', f'<< /Logo {form} 0 R >>')
            content = document.get_new_xref()
            document.update_object(content, '<< >>')
            document.update_stream(content, b'q 1 0 0 1 50 200 cm /Logo Do Q')
            document.xref_set_key(page.xref, 'Contents', '[' + ' '.join(f'{xref} 0 R' for xref in page.get_contents()) + f' {content} 0 R]')
        source = self.source(customize)
        original = source.read_bytes()
        report = self.report(source)
        structure = report['structure']
        self.assertEqual(structure['parser'], 'pyHanko')
        self.assertEqual(structure['pages'][0]['spot_inks'], ['Brand Blue'])
        state = structure['pages'][0]['graphics_states'][0]
        self.assertTrue(state['stroke_overprint'])
        self.assertTrue(state['fill_overprint'])
        self.assertEqual(state['overprint_mode'], 1)
        self.assertEqual(state['fill_alpha'], .5)
        self.assertTrue(state['transparency'])
        self.assertIn('overprint-declared', [item['code'] for item in report['findings']])
        checks = {item['code']: item['status'] for item in structure['pdfx_checks']['checks']}
        self.assertEqual(checks['no-transparency-resources'], 'failed')
        self.assertIsNone(structure['pdfx_checks']['conformant'])
        self.assertFalse(report['independently_certified'])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(report['source_sha256'], hashlib.sha256(original).hexdigest())

    def test_explicit_nonstroking_overprint_false_is_not_overridden(self):
        def customize(document, page):
            document.xref_set_key(self.resources(document, page), 'ExtGState', '<< /Ink << /OP true /op false /OPM 0 /CA 1 /ca 1 >> >>')
        report = self.report(self.source(customize))
        state = report['structure']['pages'][0]['graphics_states'][0]
        self.assertTrue(state['stroke_overprint'])
        self.assertFalse(state['fill_overprint'])
        self.assertFalse(state['transparency'])

    def test_device_n_and_registration_inks_distinguished_from_process_colors(self):
        def customize(document, page):
            document.xref_set_key(self.resources(document, page), 'ColorSpace', '<< /Special [/DeviceN [/Orange /Varnish] /DeviceCMYK << /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [0 1 1 0] /N 1 >>] /Marks [/Separation /All /DeviceCMYK << /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [1 1 1 1] /N 1 >>] >>')
        report = self.report(self.source(customize))
        page = report['structure']['pages'][0]
        self.assertEqual(page['spot_inks'], ['Orange', 'Varnish'])
        self.assertIn('registration-color', [item['code'] for item in report['findings']])
        self.assertIn('/DeviceCMYK', [item['kind'] for item in page['color_spaces']])

    def test_recursive_form_resources_are_reported_without_false_coverage(self):
        def customize(document, page):
            form = document.get_new_xref()
            resource = document.get_new_xref()
            document.update_object(resource, f'<< /XObject << /Loop {form} 0 R >> >>')
            document.update_object(form, f'<< /Type /XObject /Subtype /Form /BBox [0 0 100 100] /Resources {resource} 0 R >>')
            document.update_stream(form, b'')
            document.xref_set_key(self.resources(document, page), 'XObject', f'<< /Loop {form} 0 R >>')
        report = self.report(self.source(customize))
        checks = {item['code']: item['status'] for item in report['structure']['pdfx_checks']['checks']}
        self.assertEqual(checks['resource-coverage'], 'failed')
        self.assertTrue(report['structure']['pages'][0]['uninspected'])

    def test_icc_uses_real_littlecms_parse_and_rejects_tag_outside_file(self):
        raw = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        info = icc_description(raw)
        self.assertEqual(info['color_space'], 'RGB')
        self.assertEqual(info['sha256'], hashlib.sha256(raw).hexdigest())
        broken = bytearray(raw)
        broken[136:140] = (len(raw) + 4).to_bytes(4, 'big')
        with self.assertRaisesRegex(ValueError, 'fora do arquivo'):
            icc_description(bytes(broken))
        profile = self.root / 'rgb.icc'; profile.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'CMYK'):
            read_cmyk_profile(profile)
        link = self.root / 'linked.icc'; link.symlink_to(profile)
        with self.assertRaises((ValueError, OSError)):
            read_cmyk_profile(link)

    def test_header_only_fake_profile_and_duplicate_tags_are_rejected(self):
        fake = bytearray(132); fake[:4] = (132).to_bytes(4, 'big')
        fake[36:40] = b'acsp'; fake[16:20] = b'CMYK'; fake[12:16] = b'prtr'
        with self.assertRaises(ValueError):
            icc_description(bytes(fake))
        raw = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        raw[144:148] = raw[132:136]
        with self.assertRaisesRegex(ValueError, 'duplicada'):
            icc_description(bytes(raw))

    def test_invalid_output_intent_is_not_accepted_as_a_profile(self):
        # A dictionary in place of the profile stream is a real, well-formed
        # object graph that must not pass merely because OutputIntents exists.
        def real_graph(document, page):
            document.xref_set_key(document.pdf_catalog(), 'OutputIntents', '[<< /Type /OutputIntent /S /GTS_PDFX /OutputConditionIdentifier (Fake) /DestOutputProfile << /N 4 >> >>]')
        report = self.report(self.source(real_graph))
        self.assertTrue(report['output_intents_present'])
        self.assertIn('invalid-output-profile', [item['code'] for item in report['findings']])
        self.assertIsNone(report['structure']['output_intents'][0]['profile'])

    def test_encrypted_inspection_authenticates_and_rendering_does_not_leak_password(self):
        source = self.source()
        encrypted = self.root / 'encrypted.pdf'
        with fitz.open(source) as document:
            document.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='segredo')
        before = encrypted.read_bytes()
        report = self.report(encrypted, password='segredo')
        self.assertTrue(report['structure']['encrypted'])
        self.assertNotIn('segredo', json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'Senha'):
            self.report(encrypted, password='wrong')
        with self.assertRaisesRegex(ValueError, 'desbloqueie uma cópia'):
            self.report(encrypted, password='segredo', render_inks=True)
        self.assertEqual(encrypted.read_bytes(), before)

    def test_preflight_refuses_nonboolean_render_option_without_publication(self):
        with self.assertRaisesRegex(ValueError, 'booleana'):
            self.report(self.source(), render_inks='false')
        self.assertFalse(list(self.root.glob('report*')))

    def test_malformed_resource_shapes_and_names_never_pass_coverage(self):
        cases = [('ColorSpace', '<< /Bad /NotAValidColorSpace >>'), ('ExtGState', '[42]'),
                 ('ColorSpace', '<< /Ink [/Separation] >>'), ('Font', '[42]'),
                 ('XObject', '(invalid)'), ('Pattern', '[1 2]'), ('Shading', '[null]'),
                 ('ColorSpace', '<< /Bad [/Lab 42] >>'),
                 ('ColorSpace', '<< /Bad [/DeviceN [] /DeviceCMYK << /FunctionType 2 >>] >>'),
                 ('ExtGState', '<< /Bad << /OP (true) /ca -1 /OPM 10 >> >>')]
        for index, (key, value) in enumerate(cases):
            with self.subTest(key=key, value=value):
                def customize(document, page):
                    document.xref_set_key(self.resources(document, page), key, value)
                source = self.source(customize, name=f'malformed-{index}.pdf')
                report = self.report(source)
                checks = {item['code']: item['status'] for item in report['structure']['pdfx_checks']['checks']}
                self.assertEqual(checks['resource-coverage'], 'failed')
                self.assertTrue(report['structure']['pages'][0]['uninspected'])

    def test_null_optional_resource_entries_are_treated_as_absent(self):
        def customize(document, page):
            for category in ('ColorSpace', 'XObject', 'Pattern', 'Shading', 'ExtGState'):
                document.xref_set_key(self.resources(document, page), category, 'null')
        report = self.report(self.source(customize))
        checks = {item['code']: item['status'] for item in report['structure']['pdfx_checks']['checks']}
        self.assertEqual(checks['resource-coverage'], 'passed')

    def test_catalog_version_is_included_in_effective_pdf_version(self):
        def customize(document, page):
            document.xref_set_key(document.pdf_catalog(), 'Version', '/2.0')
        source = self.source(customize)
        # Header version 1.3 alone cannot override the newer catalog version.
        raw = source.read_bytes().replace(b'%PDF-1.7', b'%PDF-1.3', 1)
        source.write_bytes(raw)
        report = self.report(source)
        check = next(item for item in report['structure']['pdfx_checks']['checks'] if item['code'] == 'pdf-version')
        self.assertEqual(check['status'], 'failed')
        self.assertEqual(check['detail'], '2.0')

    def test_catalog_actions_attachments_and_embedded_font_checks_are_separate(self):
        def customize(document, page):
            document.xref_set_key(document.pdf_catalog(), 'OpenAction', '<< /S /JavaScript /JS (app.alert\\(1\\)) >>')
            document.embfile_add('attached.txt', b'attachment')
        report = self.report(self.source(customize))
        checks = {item['code']: item['status'] for item in report['structure']['pdfx_checks']['checks']}
        self.assertEqual(checks['no-open-action'], 'failed')
        self.assertEqual(checks['no-attached-files-or-javascript'], 'failed')
        self.assertEqual(checks['embedded-fonts'], 'failed')


if __name__ == '__main__':
    unittest.main()
