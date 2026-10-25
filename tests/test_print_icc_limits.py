"""ICC decompression limits exercised using real, compact PDF streams."""
from pathlib import Path
import base64
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch, PropertyMock
import zlib

from PIL import ImageCms
from pyhanko.pdf_utils import generic as g
from pyhanko.pdf_utils.writer import PdfFileWriter, PageObject

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import print_inspection
from print_inspection import inspect_structure, ICC_MAX_BYTES, ICCNotInspected, _decode_icc_stage
from pdf_engine import run


class ICCDecodingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()

    def tearDown(self):
        self.assertFalse(list(self.root.glob('.pdf-output-*')))
        self.temporary.cleanup()

    def fixture(self, encoded, filters=None, parameters=None, *, encrypted=False, count=1):
        writer = PdfFileWriter(stream_xrefs=False)
        content = writer.add_object(g.StreamObject(stream_data=b''))
        profiles = []
        for _ in range(count):
            dictionary = {g.pdf_name('/N'): g.NumberObject(3)}
            if filters is not None:
                dictionary[g.pdf_name('/Filter')] = g.pdf_name(filters) if isinstance(filters, str) else g.ArrayObject([g.pdf_name(name) for name in filters])
            if parameters is not None:
                dictionary[g.pdf_name('/DecodeParms')] = parameters
            profiles.append(writer.add_object(g.StreamObject(dictionary, encoded_data=encoded)))
        # Each profile is referenced both by an OutputIntent and a resource;
        # cache successes and failures without repeatedly decoding the stream.
        writer.root[g.pdf_name('/OutputIntents')] = g.ArrayObject([
            g.DictionaryObject({g.pdf_name('/S'): g.pdf_name('/GTS_PDFX'),
                                g.pdf_name('/OutputConditionIdentifier'): g.pdf_string('ICC decoding fixture'),
                                g.pdf_name('/DestOutputProfile'): profile}) for profile in profiles])
        resources = g.DictionaryObject({g.pdf_name('/ColorSpace'): g.DictionaryObject({
            g.pdf_name('/ICC' + str(index)): g.ArrayObject([g.pdf_name('/ICCBased'), profile])
            for index, profile in enumerate(profiles)})})
        writer.insert_page(PageObject(content, [0, 0, 200, 200], resources=resources))
        if encrypted:
            writer.encrypt('owner', 'segredo', pdf_mac=False)
        target = self.root / ('source-' + str(len(list(self.root.glob('source*')))) + '.pdf')
        with target.open('wb') as stream:
            writer.write(stream)
        return target

    def nested_fixture(self, mode, *, oversized=True):
        writer = PdfFileWriter(stream_xrefs=False)
        def dictionary(**values):
            return g.DictionaryObject({g.pdf_name('/' + key): value for key, value in values.items()})
        box = g.ArrayObject([g.NumberObject(number) for number in (0, 0, 200, 200)])
        payload = b'X' * (25 * 1024**2) if oversized else self.profile
        profile = writer.add_object(g.StreamObject(dictionary(N=g.NumberObject(3), Filter=g.pdf_name('/FlateDecode')),
                                                    encoded_data=zlib.compress(payload, 9)))
        color = g.ArrayObject([g.pdf_name('/ICCBased'), profile])
        resource = dictionary(ColorSpace=dictionary(ICC=color))
        group = dictionary(S=g.pdf_name('/Transparency'), CS=color)
        def form(with_group=False):
            values = dictionary(Type=g.pdf_name('/XObject'), Subtype=g.pdf_name('/Form'), BBox=box)
            values[g.pdf_name('/Group' if with_group else '/Resources')] = group if with_group else resource
            return writer.add_object(g.StreamObject(values, stream_data=b'0 0 200 200 re f'))
        def image(with_profile=True):
            return writer.add_object(g.StreamObject(dictionary(Type=g.pdf_name('/XObject'), Subtype=g.pdf_name('/Image'),
                Width=g.NumberObject(1), Height=g.NumberObject(1), BitsPerComponent=g.NumberObject(8),
                ColorSpace=color if with_profile else g.pdf_name('/DeviceRGB')), stream_data=b'\x00\x00\x00'))
        resources = dictionary()
        page_values = {}
        if mode in ('softmask-group', 'softmask-resources', 'pattern-state-softmask', 'cycle-softmask', 'bad-softmask'):
            target = form(mode == 'softmask-group')
            mask = dictionary(S=g.pdf_name('/Luminosity'), G=target)
            state = dictionary(SMask=mask)
            resources = dictionary(ExtGState=dictionary(GS=state))
            if mode == 'cycle-softmask':
                target.get_object()[g.pdf_name('/Resources')] = resources
            if mode == 'bad-softmask':
                mask[g.pdf_name('/G')] = g.NumberObject(42)
            if mode == 'pattern-state-softmask':
                shading = dictionary(ShadingType=g.NumberObject(2), ColorSpace=g.pdf_name('/DeviceRGB'))
                resources = dictionary(Pattern=dictionary(P=dictionary(PatternType=g.NumberObject(2), Shading=shading, ExtGState=state)))
        elif mode in ('image-smask', 'image-mask', 'image-alternate', 'bad-alternate'):
            parent = image(False); child = image()
            if mode == 'image-alternate':
                parent.get_object()[g.pdf_name('/Alternates')] = g.ArrayObject([dictionary(Image=child)])
            elif mode == 'bad-alternate':
                parent.get_object()[g.pdf_name('/Alternates')] = g.ArrayObject([g.NumberObject(42)])
            else:
                parent.get_object()[g.pdf_name('/SMask' if mode == 'image-smask' else '/Mask')] = child
            resources = dictionary(XObject=dictionary(Image=parent))
        elif mode in ('shading-pattern', 'tiling-pattern'):
            if mode == 'shading-pattern':
                pattern = dictionary(PatternType=g.NumberObject(2), Shading=dictionary(ShadingType=g.NumberObject(2), ColorSpace=color))
            else:
                pattern = writer.add_object(g.StreamObject(dictionary(PatternType=g.NumberObject(1), Resources=resource), stream_data=b''))
            resources = dictionary(Pattern=dictionary(P=pattern))
        elif mode in ('appearance', 'appearance-state', 'bad-appearance'):
            value = form(True) if mode != 'bad-appearance' else g.NumberObject(42)
            if mode == 'appearance-state': value = dictionary(On=value)
            annotation = writer.add_object(dictionary(Type=g.pdf_name('/Annot'), Subtype=g.pdf_name('/Square'), Rect=box, AP=dictionary(N=value)))
            page_values['/Annots'] = g.ArrayObject([annotation])
        elif mode in ('page-group', 'bad-group'):
            page_values['/Group'] = group if mode == 'page-group' else g.NumberObject(42)
        elif mode == 'form-group':
            resources = dictionary(XObject=dictionary(Form=form(True)))
        elif mode == 'inherited':
            writer.root['/Pages'][g.pdf_name('/Resources')] = resource
        elif mode == 'acroform':
            writer.root[g.pdf_name('/AcroForm')] = dictionary(DR=resource)
        elif mode in ('devicen-colorants', 'devicen-process'):
            function = dictionary(FunctionType=g.NumberObject(2))
            if mode == 'devicen-colorants':
                attributes = dictionary(Colorants=dictionary(Spot=g.ArrayObject([g.pdf_name('/Separation'), g.pdf_name('/Spot'), color, function])))
            else:
                attributes = dictionary(Process=dictionary(ColorSpace=color))
            device = g.ArrayObject([g.pdf_name('/DeviceN'), g.ArrayObject([g.pdf_name('/Spot')]), g.pdf_name('/DeviceCMYK'), function, attributes])
            resources = dictionary(ColorSpace=dictionary(Inks=device))
        else: raise AssertionError(mode)
        content = writer.add_object(g.StreamObject(stream_data=b''))
        page = PageObject(content, [0, 0, 200, 200], resources=resources)
        if mode == 'inherited': del page[g.pdf_name('/Resources')]
        for key, value in page_values.items(): page[g.pdf_name(key)] = value
        writer.insert_page(page)
        target = self.root / ('graph-' + mode + ('-large' if oversized else '-small') + '.pdf')
        with target.open('wb') as stream: writer.write(stream)
        return target

    def test_nested_icc_graphs_are_gated_before_mupdf_and_ghostscript(self):
        modes = ('softmask-group', 'softmask-resources', 'pattern-state-softmask', 'image-smask', 'image-mask',
                 'image-alternate', 'shading-pattern', 'tiling-pattern', 'appearance', 'appearance-state',
                 'page-group', 'form-group', 'inherited', 'acroform', 'devicen-colorants', 'devicen-process')
        for mode in modes:
            with self.subTest(mode=mode):
                source = self.nested_fixture(mode); original = source.read_bytes()
                output = self.root / ('partial-' + mode + '.json')
                with patch('pdf_engine.open_pdf', side_effect=AssertionError('MuPDF reached nested oversized ICC')), \
                     patch('pdf_engine._external', side_effect=AssertionError('Ghostscript reached nested oversized ICC')):
                    run('print-preflight', [source], output, {'render_inks': True})
                report = json.loads(output.read_text())
                self.assertEqual(report['geometry_status'], 'not_inspected')
                self.assertEqual(report['structure']['icc_limits']['document_budget_used'], ICC_MAX_BYTES)
                self.assertIn('uninspected-color-profile', [item['code'] for item in report['findings']])
                with patch.object(print_inspection, 'read_cmyk_profile', return_value=(b'not-used', {'sha256': 'not-used'})), \
                     patch('print_legal.shutil.which', return_value='/unused/gs'), \
                     patch('pdf_engine.open_pdf', side_effect=AssertionError('MuPDF reached source gate')), \
                     patch('pdf_engine._external', side_effect=AssertionError('Ghostscript reached source gate')):
                    with self.assertRaisesRegex(ValueError, 'perfil ICC não inspecionado'):
                        run('pdfx', [source], self.root / ('refused-' + mode + '.pdf'), {'icc_profile': 'unused.icc'})
                self.assertEqual(source.read_bytes(), original)

    def test_valid_nested_icc_profiles_are_inspected_once_without_losing_coverage(self):
        for mode in ('softmask-group', 'softmask-resources', 'pattern-state-softmask', 'shading-pattern', 'appearance-state',
                     'form-group', 'inherited', 'acroform', 'devicen-colorants', 'devicen-process'):
            with self.subTest(mode=mode):
                report = inspect_structure(self.nested_fixture(mode, oversized=False))
                self.assertEqual(report['icc_limits']['document_budget_used'], len(self.profile))
                self.assertFalse(report['pages'][0]['uninspected'])
                self.assertEqual(next(item['status'] for item in report['pdfx_checks']['checks'] if item['code'] == 'resource-coverage'), 'passed')
                self.assertTrue(any(item.get('profile', {}).get('sha256') == hashlib.sha256(self.profile).hexdigest()
                                    for item in report['pages'][0]['color_spaces']))

    def test_malformed_or_cyclic_nested_resources_block_other_parsers(self):
        for mode in ('cycle-softmask', 'bad-softmask', 'bad-alternate', 'bad-appearance', 'bad-group'):
            with self.subTest(mode=mode):
                source = self.nested_fixture(mode, oversized=False)
                output = self.root / ('invalid-' + mode + '.json')
                with patch('pdf_engine.open_pdf', side_effect=AssertionError('MuPDF reached malformed/cyclic resources')), \
                     patch('pdf_engine._external', side_effect=AssertionError('GS reached malformed/cyclic resources')):
                    run('print-preflight', [source], output, {'render_inks': True})
                report = json.loads(output.read_text())
                self.assertEqual(report['geometry_status'], 'not_inspected')
                self.assertIn('uninspected-print-resources', [item['code'] for item in report['findings']])
                self.assertEqual(next(item['status'] for item in report['structure']['pdfx_checks']['checks'] if item['code'] == 'resource-coverage'), 'failed')

    @staticmethod
    def run_length(data):
        return b''.join(bytes((len(data[position:position + 128]) - 1,)) + data[position:position + 128]
                        for position in range(0, len(data), 128)) + b'\x80'

    def assert_profile(self, report):
        item = report['output_intents'][0]
        self.assertNotIn('error', item)
        self.assertEqual(item['profile']['sha256'], hashlib.sha256(self.profile).hexdigest())
        self.assertEqual(item['profile']['bytes'], len(self.profile))
        self.assertEqual(report['pages'][0]['color_spaces'][0]['profile'], item['profile'])

    def test_real_profiles_with_usual_filters_and_chains_without_generic_decode(self):
        compressed = zlib.compress(self.profile)
        predictor = g.DictionaryObject({g.pdf_name('/Predictor'): g.NumberObject(1)})
        cases = [
            (self.profile, None, None),
            (compressed, '/FlateDecode', predictor),
            (self.profile.hex().encode() + b'>', '/ASCIIHexDecode', None),
            (base64.a85encode(self.profile) + b'~>', '/ASCII85Decode', None),
            (self.run_length(self.profile), '/RunLengthDecode', None),
            (base64.a85encode(compressed) + b'~>', ['/ASCII85Decode', '/FlateDecode'], g.ArrayObject([g.NullObject(), predictor])),
            (compressed.hex().encode() + b'>', ['/ASCIIHexDecode', '/FlateDecode'], None),
            (zlib.compress(compressed), ['/FlateDecode', '/FlateDecode'], None),
            (zlib.compress(self.profile.hex().encode() + b'>'), ['/FlateDecode', '/ASCIIHexDecode'], None),
        ]
        for encoded, filters, parameters in cases:
            with self.subTest(filters=filters):
                source = self.fixture(encoded, filters, parameters)
                # The full ICC path must never fall back to the generic
                # 256 MiB decoder; classic xrefs keep this check ICC-specific.
                with patch.object(g.StreamObject, 'data', new_callable=PropertyMock,
                                  side_effect=AssertionError('Generic stream decoding was reached')):
                    report = inspect_structure(source)
                self.assert_profile(report)
                self.assertLessEqual(report['icc_limits']['document_budget_used'], 2 * ICC_MAX_BYTES)
                if filters is None or isinstance(filters, str):
                    self.assertEqual(report['icc_limits']['document_budget_used'], len(self.profile))

    def test_encrypted_flate_icc_uses_decrypted_encoded_bytes(self):
        source = self.fixture(zlib.compress(self.profile), '/FlateDecode', encrypted=True)
        before = source.read_bytes()
        report = inspect_structure(source, 'segredo')
        self.assert_profile(report)
        self.assertTrue(report['encrypted'])
        self.assertNotIn('segredo', json.dumps(report))
        self.assertEqual(source.read_bytes(), before)

    def test_25_mib_expansion_is_stopped_before_icc_parser_and_other_renderers(self):
        payload = bytearray(25 * 1024**2)
        payload[:4] = len(payload).to_bytes(4, 'big'); payload[36:40] = b'acsp'
        encoded = zlib.compress(payload, 9)
        del payload
        source = self.fixture(encoded, '/FlateDecode')
        before = source.read_bytes()
        self.assertLess(source.stat().st_size, 32 * 1024)
        with patch.object(print_inspection, 'icc_description', side_effect=AssertionError('Oversized ICC was fully expanded')):
            report = inspect_structure(source)
        self.assertEqual(report['output_intents'][0]['inspection_status'], 'not_inspected')
        self.assertEqual(report['icc_limits']['document_budget_used'], ICC_MAX_BYTES)
        self.assertIn('uninspected-output-profile', [item['code'] for item in report['findings']])
        self.assertTrue(report['pages'][0]['uninspected'])
        checks = {item['code']: item['status'] for item in report['pdfx_checks']['checks']}
        self.assertEqual(checks['resource-coverage'], 'failed')
        self.assertEqual(checks['color-profile-integrity'], 'failed')
        output = self.root / 'partial.json'
        with patch('pdf_engine.open_pdf', side_effect=AssertionError('MuPDF must not reexpand rejected ICC')), \
             patch('pdf_engine._external', side_effect=AssertionError('Ghostscript must not reexpand rejected ICC')):
            run('print-preflight', [source], output, {'render_inks': True})
        partial = json.loads(output.read_text())
        self.assertEqual(partial['geometry_status'], 'not_inspected')
        self.assertIsNone(partial['ink_coverage'])
        self.assertEqual(partial['pages'], [])
        self.assertEqual(partial['page_count'], 1)
        self.assertFalse(partial['independently_certified'])
        self.assertEqual(source.read_bytes(), before)

    def test_truncated_or_trailing_streams_and_malformed_chains_are_not_accepted(self):
        compressed = zlib.compress(self.profile)
        cases = [(compressed[:-2], '/FlateDecode'), (compressed + b'extra', '/FlateDecode'),
                 (compressed + compressed, '/FlateDecode'), (b'not-zlib', '/FlateDecode'),
                 (zlib.compress(compressed[:-2]), ['/FlateDecode', '/FlateDecode']),
                 (base64.a85encode(compressed[:-2]) + b'~>', ['/ASCII85Decode', '/FlateDecode']),
                 (b'0', '/ASCIIHexDecode'), (b'GG>', '/ASCIIHexDecode'),
                 (b'!~>', '/ASCII85Decode'), (b'zz', '/ASCII85Decode'),
                 (b'\x02A', '/RunLengthDecode'), (b'\xff', '/RunLengthDecode'),
                 (self.run_length(self.profile) + b'x', '/RunLengthDecode')]
        for encoded, filters in cases:
            with self.subTest(filters=filters, prefix=encoded[:8]):
                report = inspect_structure(self.fixture(encoded, filters))
                self.assertIn('error', report['output_intents'][0])
                self.assertIsNone(report['output_intents'][0]['profile'])
                self.assertEqual(report['pdfx_checks']['status'], 'checks_failed')

    def test_unsupported_filters_predictors_and_parameter_shapes_are_uninspected(self):
        cases = [('/LZWDecode', None), ('/DCTDecode', None),
                 ('/FlateDecode', g.DictionaryObject({g.pdf_name('/Predictor'): g.NumberObject(12)})),
                 ('/FlateDecode', g.DictionaryObject({g.pdf_name('/Unexpected'): g.NumberObject(1)})),
                 (['/ASCII85Decode', '/FlateDecode'], g.ArrayObject([g.NullObject()])),
                 ('/ASCIIHexDecode', g.DictionaryObject({g.pdf_name('/Columns'): g.NumberObject(3)})),
                 (['/FlateDecode'] * 9, None)]
        for filters, params in cases:
            with self.subTest(filters=filters):
                source = self.fixture(zlib.compress(self.profile), filters, params)
                report = inspect_structure(source)
                self.assertEqual(report['output_intents'][0]['inspection_status'], 'not_inspected')
                self.assertIn('uninspected-color-profile', [item['code'] for item in report['findings']])
                self.assertTrue(report['pages'][0]['uninspected'])
                self.assertEqual(report['icc_limits']['document_budget_used'], 0)

    def test_each_filter_stage_limits_expansion_and_honors_end_markers(self):
        # Small caps exercise the exact same decoder before huge intermediate
        # allocations; the real 16 MiB Flate boundary is covered above.
        data = b'\x00' * 256
        cases = [(zlib.compress(data), '/FlateDecode'), (data.hex().encode() + b'>', '/ASCIIHexDecode'),
                 (base64.a85encode(data) + b'~>', '/ASCII85Decode'), (b'\x81\x00\x81\x00\x80', '/RunLengthDecode')]
        for encoded, name in cases:
            with self.subTest(name=name):
                with self.assertRaises(ICCNotInspected):
                    _decode_icc_stage(encoded, name, 64)
                self.assertEqual(_decode_icc_stage(encoded, name, len(data)), data)
        self.assertEqual(_decode_icc_stage(b'0>', '/ASCIIHexDecode', 1), b'\x00')
        for length in range(1, 18):
            data = bytes(range(length))
            self.assertEqual(_decode_icc_stage(base64.a85encode(data) + b'~>', '/ASCII85Decode', len(data)), data)

    def test_document_budget_counts_failed_unique_profiles_but_not_references(self):
        payload = bytearray(25 * 1024**2); payload[:4] = len(payload).to_bytes(4, 'big')
        encoded = zlib.compress(payload, 9); del payload
        source = self.fixture(encoded, '/FlateDecode', count=3)
        # Exercise aggregate exhaustion with two actual 16 MiB stages rather
        # than allocating the full production budget in every test process.
        with patch.object(print_inspection, 'ICC_DOCUMENT_DECODE_BYTES', 2 * ICC_MAX_BYTES):
            report = inspect_structure(source)
        self.assertEqual(report['icc_limits']['document_budget_used'], 2 * ICC_MAX_BYTES)
        self.assertEqual(len(report['output_intents']), 3)
        self.assertTrue(all(item['inspection_status'] == 'not_inspected' for item in report['output_intents']))
        self.assertIn('esgotado', report['output_intents'][2]['error'])

    def test_chained_flate_cannot_bypass_the_icc_expansion_limit(self):
        payload = bytearray(25 * 1024**2)
        payload[:4] = len(payload).to_bytes(4, 'big'); payload[36:40] = b'acsp'
        compressed = zlib.compress(payload, 9); del payload
        source = self.fixture(zlib.compress(compressed, 9), ['/FlateDecode', '/FlateDecode'])
        self.assertLess(source.stat().st_size, 4096)
        with patch.object(print_inspection, 'icc_description', side_effect=AssertionError('Oversized chained ICC reached parser')):
            report = inspect_structure(source)
        self.assertEqual(report['output_intents'][0]['inspection_status'], 'not_inspected')
        self.assertEqual(report['icc_limits']['document_budget_used'], ICC_MAX_BYTES + len(compressed))
        self.assertEqual(report['pdfx_checks']['status'], 'checks_failed')

    def test_pdfx_source_gate_precedes_mupdf_and_ghostscript(self):
        source = self.fixture(zlib.compress(self.profile), '/FlateDecode',
                              g.DictionaryObject({g.pdf_name('/Predictor'): g.NumberObject(12)}))
        output = self.root / 'refused.pdf'
        # Existing integration_print tests supply the real CMYK ICC/GS; this
        # control specifically proves no converter runs for uninspected input.
        with patch.object(print_inspection, 'read_cmyk_profile', return_value=(b'not-used', {'sha256': 'not-used'})), \
             patch('print_legal.shutil.which', return_value='/unused/gs'), \
             patch('pdf_engine.open_pdf', side_effect=AssertionError('MuPDF reached before source ICC gate')), \
             patch('pdf_engine._external', side_effect=AssertionError('Ghostscript reached before source ICC gate')):
            with self.assertRaisesRegex(ValueError, 'perfil ICC não inspecionado.*Repare uma cópia'):
                run('pdfx', [source], output, {'icc_profile': 'unused.icc'})
        self.assertFalse(output.exists())

    def test_pdfx_malformed_source_explains_repair_without_calling_converter(self):
        source = self.root / 'malformed.pdf'; source.write_bytes(b'%PDF-1.7\n%%EOF\n')
        output = self.root / 'refused.pdf'
        with patch.object(print_inspection, 'read_cmyk_profile', return_value=(b'not-used', {'sha256': 'not-used'})), \
             patch('print_legal.shutil.which', return_value='/unused/gs'), \
             patch('pdf_engine.open_pdf', side_effect=AssertionError('MuPDF reached malformed input')), \
             patch('pdf_engine._external', side_effect=AssertionError('Ghostscript reached malformed input')):
            with self.assertRaisesRegex(ValueError, 'Repare uma cópia.*Reparar PDF'):
                run('pdfx', [source], output, {'icc_profile': 'unused.icc'})
        self.assertFalse(output.exists())
        self.assertEqual(source.read_bytes(), b'%PDF-1.7\n%%EOF\n')


if __name__ == '__main__':
    unittest.main()
