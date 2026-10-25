"""Independent reproductions from the final editing/color review.

These cases read published PDF operators, streams, pixels and structure links;
they do not use the editor's graphics-state proof as their expected result.
"""
from pathlib import Path
import io
import json
import re
import sys
import tempfile
import unittest

import fitz
from PIL import Image, ImageCms

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run


class EditingColorRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.originals = {}

    def tearDown(self):
        for source, original in self.originals.items():
            self.assertEqual(source.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.pdf-output-*')))
        self.temporary.cleanup()

    def save(self, document, name):
        source = self.root / (name + '.pdf')
        document.save(source)
        self.originals[source] = source.read_bytes()
        return source

    def inspect(self, source):
        output = self.root / (source.stem + '.json')
        run('content-inspect', [source], output)
        return json.loads(output.read_text())

    def apply(self, source, report, edit, name):
        output = self.root / (name + '.pdf')
        run('content-apply', [source], output, {'source_sha256': report['source_sha256'], 'edits': [edit]})
        return output

    @staticmethod
    def color_operators(document):
        # Fixtures contain only one simple painted rectangle and no strings,
        # forms or binary inline data. Read actual output operators rather than
        # display RGB, which conceals a DeviceGray -> DeviceRGB conversion.
        stream = b'\n'.join(document.xref_stream(xref) for xref in document[0].get_contents())
        result = {}
        for match in re.finditer(rb'(?<![A-Za-z0-9./])((?:[+\-.0-9]+\s+){1,3})(g|G|rg|RG)(?=\s|$)', stream):
            operator = match[2].decode('ascii')
            result['stroke' if operator[0].isupper() else 'fill'] = (operator, tuple(float(value) for value in match[1].split()))
        return result

    def test_width_and_resize_with_unchanged_ui_hex_preserve_gray_and_rgb_components(self):
        for name, stroke, fill in [('gray', (.12345,), (.54321,)),
                                    ('rgb', (.12345,.54321,.33333), (.98765,.22222,.11111))]:
            with fitz.open() as doc:
                page = doc.new_page(width=400, height=500)
                page.draw_rect((40,60,160,140), color=stroke, fill=fill, width=2)
                source = self.save(doc, name)
            report = self.inspect(source)
            item = next(item for item in report['objects'] if item['kind'] == 'vector')
            self.assertTrue(item['editable'])
            for operation in ('width', 'resize'):
                with self.subTest(color_model=name, change=operation):
                    rect = item['rect'] if operation == 'width' else [40,60,200,170]
                    # Exact payload shape from ContentEditDraft.options: both
                    # visible colors are submitted even when only width changes.
                    output = self.apply(source, report, {'id':item['id'], 'action':'replace', 'rect':rect,
                        'stroke_width':3, 'stroke_color':item['color'].upper(), 'fill_color':item['fill_color']}, name + '-' + operation)
                    with fitz.open(source) as before, fitz.open(output) as after:
                        expected = {'stroke':('G' if name == 'gray' else 'RG', stroke),
                                    'fill':('g' if name == 'gray' else 'rg', fill)}
                        self.assertEqual(self.color_operators(before), expected)
                        self.assertEqual(self.color_operators(after), expected)
                        self.assertEqual(len(after[0].get_drawings()), 1)
                        self.assertEqual(after[0].get_drawings()[0]['width'], 3)

    def test_explicit_color_change_keeps_the_other_original_gray_paint(self):
        with fitz.open() as doc:
            page = doc.new_page(width=400, height=500)
            page.draw_rect((40,60,160,140), color=(.12345,), fill=(.54321,), width=2)
            source = self.save(doc, 'explicit-color')
        report = self.inspect(source); item = next(item for item in report['objects'] if item['kind'] == 'vector')
        for fill, name in [('#ff0000', 'red'), (None, 'no-fill')]:
            with self.subTest(fill=fill):
                output = self.apply(source, report, {'id':item['id'], 'action':'replace', 'rect':item['rect'],
                    'stroke_width':2, 'stroke_color':item['color'], 'fill_color':fill}, name)
                with fitz.open(output) as doc:
                    operators = self.color_operators(doc)
                    self.assertEqual(operators['stroke'], ('G', (.12345,)))
                    if fill is None:
                        self.assertIsNone(doc[0].get_drawings()[0]['fill'])
                    else:
                        self.assertEqual(operators['fill'], ('rg', (1.0,0.0,0.0)))

    @staticmethod
    def non_srgb_profile():
        profile = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        for index in range(int.from_bytes(profile[128:132], 'big')):
            position = 132 + index * 12
            if profile[position:position + 4] == b'rTRC':
                offset = int.from_bytes(profile[position + 4:position + 8], 'big')
                if profile[offset:offset + 4] != b'para':
                    raise AssertionError('The generated RGB profile no longer uses a parametric transfer curve.')
                # The generated sRGB profile shares this curve among R/G/B.
                # A different valid gamma makes accidental double application
                # obvious; an ordinary sRGB test would largely conceal it.
                profile[offset + 12:offset + 16] = int(1.2 * 65536).to_bytes(4, 'big')
                return bytes(profile)
        raise AssertionError('The generated RGB profile has no rTRC.')

    def test_compression_keeps_non_srgb_icc_original_samples_and_rendered_pixels(self):
        profile = self.non_srgb_profile()
        parsed = ImageCms.ImageCmsProfile(io.BytesIO(profile))
        original_pixel = (100,120,140)
        expected = ImageCms.profileToProfile(Image.new('RGB',(1,1),original_pixel), parsed,
                                             ImageCms.createProfile('sRGB')).getpixel((0,0))
        self.assertNotEqual(expected, original_pixel)
        encoded = io.BytesIO(); Image.new('RGB',(800,600),original_pixel).save(encoded,format='PNG')
        with fitz.open() as doc:
            page = doc.new_page(width=400,height=500)
            xref = page.insert_image((40,80,120,140),stream=encoded.getvalue())
            icc = doc.get_new_xref();doc.update_object(icc,'<< /N 3 /Alternate /DeviceRGB >>')
            doc.update_stream(icc,profile);doc.xref_set_key(xref,'ColorSpace',f'[/ICCBased {icc} 0 R]')
            source = self.save(doc, 'non-srgb')
        output = self.root/'non-srgb-compressed.pdf'
        run('compress',[source],output,{'image_dpi':72,'quality':95})
        with fitz.open(source) as before, fitz.open(output) as after:
            old = before[0].get_image_info(xrefs=True)[0];new = after[0].get_image_info(xrefs=True)[0]
            self.assertEqual((new['width'],new['height']),(800,600))
            self.assertEqual(after.xref_stream(new['xref']),before.xref_stream(old['xref']))
            color_space = after.xref_get_key(new['xref'],'ColorSpace')[1]
            self.assertIn('/ICCBased',color_space)
            icc = int(re.search(r'(\d+) 0 R',color_space).group(1))
            self.assertEqual(after.xref_stream(icc),profile)
            clip = fitz.Rect(50,90,110,130)
            original_render = before[0].get_pixmap(clip=clip).samples
            self.assertEqual(tuple(original_render[:3]),expected)
            self.assertEqual(after[0].get_pixmap(clip=clip).samples,original_render)

    def structured_image(self, parent_marker):
        with fitz.open() as doc:
            page = doc.new_page(width=400,height=500)
            asset=io.BytesIO();Image.new('RGB',(80,60),'red').save(asset,format='PNG')
            image=page.insert_image((40,80,120,140),stream=asset.getvalue())
            tree=doc.get_new_xref();node=doc.get_new_xref();parent=doc.get_new_xref()
            doc.update_object(tree,f'<</Type/StructTreeRoot/K[{node} 0 R]/ParentTree {parent} 0 R/ParentTreeNextKey 1>>')
            doc.update_object(node,f'<</Type/StructElem/S/Figure/P {tree} 0 R/Pg {page.xref} 0 R/Alt(A figure)/K<</Type/OBJR/Obj {image} 0 R/Pg {page.xref} 0 R>>>>')
            doc.update_object(parent,f'<</Nums[0 {node} 0 R]>>')
            if parent_marker:doc.xref_set_key(image,'StructParent','0')
            doc.xref_set_key(doc.pdf_catalog(),'StructTreeRoot',f'{tree} 0 R')
            doc.xref_set_key(doc.pdf_catalog(),'MarkInfo','<</Marked true>>')
            return self.save(doc,'structured-' + str(parent_marker))

    def test_structured_image_allows_replacement_with_live_objr_and_refuses_move_delete(self):
        asset=self.root/'blue.png';Image.new('RGB',(80,60),'blue').save(asset,format='PNG')
        for parent_marker in (True,False):
            with self.subTest(struct_parent=parent_marker):
                source=self.structured_image(parent_marker);report=self.inspect(source)
                item=next(item for item in report['objects'] if item['kind']=='image')
                self.assertTrue(item['editable']);self.assertEqual(item['supported_actions'],['replace'])
                for action in ('move','delete'):
                    target=self.root/f'refused-{parent_marker}-{action}.pdf'
                    with self.assertRaises(ValueError):
                        run('content-apply',[source],target,{'source_sha256':report['source_sha256'],
                            'edits':[{'id':item['id'],'action':action,'rect':[250,80,330,140]}]})
                    self.assertFalse(target.exists())
                output=self.apply(source,report,{'id':item['id'],'action':'replace','image_path':str(asset)},'replacement-' + str(parent_marker))
                with fitz.open(output) as doc:
                    figures=[xref for xref in range(1,doc.xref_length()) if doc.xref_get_key(xref,'S')==('name','/Figure')]
                    self.assertEqual(len(figures),1)
                    figure=figures[0]
                    referenced=int(doc.xref_get_key(figure,'K/Obj')[1].split()[0])
                    visible=doc[0].get_image_info(xrefs=True)
                    self.assertEqual(len(visible),1)
                    # get_image_info(xrefs=True) matches by pixel digest and can
                    # return a different unused resource with identical pixels.
                    # Resolve the real Do invocation to prove object identity.
                    names=re.findall(rb'/([A-Za-z0-9]+)\s+Do\b',doc[0].read_contents())
                    self.assertEqual(len(names),1)
                    invoked=doc.xref_get_key(doc[0].xref,'Resources/XObject/'+names[0].decode('ascii'))
                    self.assertEqual(invoked,('xref',f'{referenced} 0 R'))
                    self.assertEqual(doc.xref_get_key(referenced,'Width'),('int','80'))
                    self.assertEqual(doc.xref_get_key(referenced,'StructParent'),('int','0') if parent_marker else ('null','null'))
                    self.assertEqual(doc.xref_get_key(figure,'Alt'),('string','A figure'))
                    self.assertEqual(doc.xref_get_key(figure,'K/Pg'),('xref',f'{doc[0].xref} 0 R'))
                    self.assertEqual(tuple(doc[0].get_pixmap(clip=fitz.Rect(50,90,110,130)).samples[:3]),(0,0,255))

    def test_unstructured_images_retain_move_and_delete(self):
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500);asset=io.BytesIO()
            Image.new('RGB',(80,60),'red').save(asset,format='PNG')
            page.insert_image((40,80,120,140),stream=asset.getvalue());source=self.save(doc,'unstructured')
        report=self.inspect(source);item=next(item for item in report['objects'] if item['kind']=='image')
        self.assertTrue({'replace','move','delete'}.issubset(item['supported_actions']))
        moved=self.apply(source,report,{'id':item['id'],'action':'move','rect':[250,80,330,140]},'moved')
        deleted=self.apply(source,report,{'id':item['id'],'action':'delete'},'deleted')
        with fitz.open(moved) as doc:
            self.assertEqual(tuple(doc[0].get_pixmap(clip=fitz.Rect(260,90,320,130)).samples[:3]),(255,0,0))
            self.assertEqual(set(doc[0].get_pixmap(clip=fitz.Rect(50,90,110,130)).samples),{255})
        with fitz.open(deleted) as doc:self.assertEqual(set(doc[0].get_pixmap().samples),{255})


if __name__=='__main__':unittest.main()
