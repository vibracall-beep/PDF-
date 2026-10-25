"""Do not turn print colors/states into unqualified display-RGB vector edits."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import fitz
from PIL import ImageCms

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
from pdf_vector_state import source_states


class VectorGraphicsStateTests(unittest.TestCase):
    def setUp(self): self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self): self.assertFalse(list(self.root.glob('.pdf-output-*')));self.temp.cleanup()

    def source(self,name,stream,resources=None):
        source=self.root/f'{name}.pdf'
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500)
            page.insert_text((30,350),'Original text remains',fontsize=12)
            reference=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
            if resources:
                for key,value in resources(doc).items(): doc.xref_set_key(reference,key,value)
            xref=doc.get_new_xref();doc.update_object(xref,'<<>>');doc.update_stream(xref,stream)
            previous=page.get_contents();doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{item} 0 R' for item in [*previous,xref])+']')
            doc.save(source)
        return source

    def inspect(self,source):
        output=source.with_suffix('.json');run('content-inspect',[source],output)
        report=json.loads(output.read_text());return report,[entry for entry in report['objects'] if entry['kind']=='vector']

    def assert_refused(self,source):
        before=source.read_bytes();report,vectors=self.inspect(source)
        self.assertTrue(vectors,'The fixture must contain an actual inspected primitive.')
        self.assertTrue(all(not entry['editable'] for entry in vectors))
        self.assertTrue(all('vector-graphics-state-unproven' in entry['limitations'] for entry in vectors))
        target=source.with_name(source.stem+'-rejected.pdf')
        with self.assertRaises(ValueError): run('content-apply',[source],target,dict(source_sha256=report['source_sha256'],edits=[dict(id=vectors[0]['id'],action='delete')]))
        self.assertFalse(target.exists());self.assertEqual(source.read_bytes(),before)

    def test_fill_only_f_operator_is_parsed_as_paint_and_retains_gray(self):
        source=self.source('fill-only',b'q .12345 g 40 300 120 70 re f Q')
        report,vectors=self.inspect(source);self.assertEqual(len(vectors),1)
        item=vectors[0];self.assertTrue(item['editable']);self.assertIsNone(item['color'])
        output=self.root/'fill-only-moved.pdf'
        run('content-apply',[source],output,dict(source_sha256=report['source_sha256'],edits=[dict(id=item['id'],action='replace',rect=[200,50,320,120],stroke_color=None,fill_color=item['fill_color'])]))
        with fitz.open(output) as doc:
            proof=source_states(doc,doc[0],doc[0].get_bboxlog())
            self.assertEqual(list(proof.values()),[('/DeviceGray',(0.12345,))])
            self.assertIn('Original text remains',doc[0].get_text())

    def test_cmyk_operators_are_not_rewritten_as_device_rgb(self):
        source=self.source('cmyk',b'q 0 1 1 0 K 2 w 40 300 120 70 re S Q')
        self.assert_refused(source)

    def test_spot_separation_is_not_lost_through_rgb_inspection(self):
        resource=lambda doc:{'ColorSpace':'<< /Spot [/Separation /BrandOrange /DeviceCMYK << /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [0 1 1 0] /N 1 >>] >>'}
        source=self.source('spot',b'q /Spot CS 1 SCN 2 w 40 300 120 70 re S Q',resource)
        self.assert_refused(source)

    def test_real_embedded_icc_rgb_is_not_claimed_to_be_device_rgb(self):
        def resources(doc):
            profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
            xref=doc.get_new_xref();doc.update_object(xref,'<< /N 3 /Alternate /DeviceRGB >>');doc.update_stream(xref,profile)
            return {'ColorSpace':f'<< /Calibrated [/ICCBased {xref} 0 R] >>'}
        source=self.source('icc',b'q /Calibrated CS 1 0 0 SCN 2 w 40 300 120 70 re S Q',resources)
        self.assert_refused(source)

    def test_pattern_color_is_not_replaced_by_a_solid_display_color(self):
        def resources(doc):
            xref=doc.get_new_xref();doc.update_object(xref,'<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 10 10] /XStep 10 /YStep 10 /Resources <<>> >>')
            doc.update_stream(xref,b'1 0 0 rg 0 0 5 5 re f')
            return {'Pattern':f'<< /P0 {xref} 0 R >>'}
        source=self.source('pattern',b'q /Pattern cs /P0 scn 40 300 120 70 re f Q',resources)
        self.assert_refused(source)

    def test_overprint_mode_and_transfer_states_are_refused(self):
        settings={'overprint':'/OP true','nonstroke-overprint':'/op true','overprint-mode':'/OPM 1',
                  'blend':'/BM /Multiply','transfer':'/TR << /FunctionType 2 /Domain [0 1] /C0 [1] /C1 [0] /N 1 >>',
                  'transfer2':'/TR2 /Default','halftone':'/HT /Default','render-intent':'/RI /Perceptual'}
        for name,state in settings.items():
            with self.subTest(state=name):
                resource=lambda doc,state=state:{'ExtGState':'<< /GS << /Type /ExtGState '+state+' >> >>'}
                self.assert_refused(self.source(name,b'q /GS gs 1 0 0 RG 2 w 40 300 120 70 re S Q',resource))

    def test_default_color_space_substitution_is_refused(self):
        resource=lambda doc:{'ColorSpace':'<< /DefaultRGB [/CalRGB << /WhitePoint [0.9505 1 1.089] /Gamma [2.2 2.2 2.2] >>] >>'}
        self.assert_refused(self.source('default-rgb',b'q 1 0 0 RG 2 w 40 300 120 70 re S Q',resource))

    def test_form_xobject_and_marked_content_are_not_flattened_as_independent_primitives(self):
        source=self.root/'form.pdf'
        with fitz.open() as original,fitz.open() as output:
            page=original.new_page(width=400,height=500);page.draw_rect(fitz.Rect(40,100,160,170),color=(1,0,0),width=2)
            output.new_page(width=400,height=500).show_pdf_page(fitz.Rect(0,0,400,500),original,0);output.save(source)
        self.assert_refused(source)
        self.assert_refused(self.source('marked',b'q /Figure << /MCID 0 >> BDC 1 0 0 RG 2 w 40 300 120 70 re S EMC Q'))

    def test_escaped_resource_and_state_names_cannot_bypass_inspection(self):
        resources=lambda doc:{'ExtGState':'<< /G#53 << /Type /ExtGState /O#50 true >> >>'}
        self.assert_refused(self.source('escaped',b'q /G#53 gs 1 0 0 RG 2 w 40 300 120 70 re S Q',resources))

    def test_operator_words_inside_text_do_not_disable_rgb_primitives(self):
        source=self.source('literal',b'q BT /helv 12 Tf 1 0 0 1 20 40 Tm (/OP true /GS gs /Separation /DefaultRGB 0 1 1 0 K) Tj ET 1 0 0 RG 2 w 40 300 120 70 re S Q')
        report,vectors=self.inspect(source);self.assertTrue(vectors);self.assertTrue(all(entry['editable'] for entry in vectors))
        target=self.root/'literal-edited.pdf'
        run('content-apply',[source],target,dict(source_sha256=report['source_sha256'],edits=[dict(id=vectors[0]['id'],action='move',rect=[220,100,342,172])]))
        with fitz.open(target) as after: self.assertIn('/OP true /GS gs /Separation',after[0].get_text())

    def test_device_gray_remains_gray_after_move(self):
        source=self.source('gray',b'q 0.4 G 0.7 g 2 w 40 300 120 70 re B Q')
        report,vectors=self.inspect(source);self.assertTrue(vectors[0]['editable'])
        target=self.root/'gray-edited.pdf'
        run('content-apply',[source],target,dict(source_sha256=report['source_sha256'],edits=[dict(id=vectors[0]['id'],action='move',rect=[220,100,342,172])]))
        with fitz.open(target) as after:
            states=source_states(after,after[0],after[0].get_bboxlog())
            self.assertEqual(list(states.values()),[('/DeviceGray',(0.7,)),('/DeviceGray',(0.4,))])

    def test_explicit_default_graphics_state_is_supported_without_relaxing_other_states(self):
        resources=lambda doc:{'ExtGState':'<< /GS << /Type /ExtGState /CA 1 /ca 1 /BM /Normal /OP false /op false /OPM 0 /ML 10 >> >>'}
        source=self.source('defaults',b'q /GS gs 1 0 0 RG 2 w 40 300 120 70 re S Q',resources)
        _,vectors=self.inspect(source);self.assertTrue(vectors);self.assertTrue(all(entry['editable'] for entry in vectors))
