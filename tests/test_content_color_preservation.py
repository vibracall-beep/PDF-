"""Text color models and complete image-object preservation on real PDFs."""
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

import fitz
from PIL import Image,ImageCms

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
from pdf_vector_state import source_states


class ContentColorPreservationTests(unittest.TestCase):
    def setUp(self): self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self): self.assertFalse(list(self.root.glob('.pdf-output-*')));self.temp.cleanup()

    def inspect(self,source):
        output=source.with_suffix('.json');run('content-inspect',[source],output)
        return json.loads(output.read_text())

    def apply(self,source,report,edit):
        output=source.with_name(source.stem+'-edited.pdf')
        run('content-apply',[source],output,dict(source_sha256=report['source_sha256'],edits=[edit]));return output

    def colored_text(self,name,operator,resources=None):
        source=self.root/f'{name}.pdf'
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500);page.insert_text((40,70),'Original content',fontsize=14)
            if resources:
                xref=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
                for key,value in resources.items(): doc.xref_set_key(xref,key,value)
            for xref in page.get_contents():
                data=doc.xref_stream(xref).replace(b'BT\n',b'BT\n'+operator+b'\n')
                doc.update_stream(xref,data)
            doc.save(source)
        return source

    def test_stencil_image_stays_readonly_and_retains_its_source_paint_color(self):
        source=self.root/'stencil.pdf'
        with fitz.open() as doc:
            page=doc.new_page(width=300,height=300)
            resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0]);xref=doc.get_new_xref()
            doc.update_object(xref,'<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ImageMask true /BitsPerComponent 1 >>')
            doc.update_stream(xref,bytes([170,85])*4);doc.xref_set_key(resources,'XObject',f'<< /Im0 {xref} 0 R >>')
            content=doc.get_new_xref();doc.update_object(content,'<<>>')
            doc.update_stream(content,b'q 1 0 0 rg 80 0 0 80 40 100 cm /Im0 Do Q');page.set_contents(content);doc.save(source)
        report=self.inspect(source);item=next(item for item in report['objects'] if item['kind']=='image')
        self.assertFalse(item['editable']);self.assertIn('image-mask',item['limitations'])
        with self.assertRaises(ValueError): self.apply(source,report,dict(id=item['id'],action='move',rect=[160,100,240,180]))
        output=self.root/'stencil-compressed.pdf';run('compress',[source],output,dict(image_dpi=72,quality=70))
        with fitz.open(source) as before,fitz.open(output) as after:
            self.assertEqual(before[0].get_pixmap().samples,after[0].get_pixmap().samples)
            self.assertEqual(after.xref_get_key(after[0].get_images()[0][0],'ImageMask'),('bool','true'))

    def test_replacement_and_compression_preserve_layer_membership(self):
        for operation in ('replace','compress'):
            with self.subTest(operation=operation):
                source=self.root/f'layer-{operation}.pdf';asset=self.root/'layer-new.png'
                old=io.BytesIO();Image.new('RGB',(800,600),'red').save(old,format='PNG')
                Image.new('RGB',(80,60),'blue').save(asset,format='PNG')
                with fitz.open() as doc:
                    page=doc.new_page(width=400,height=500);layer=doc.add_ocg('Source visibility',on=operation=='replace')
                    xref=page.insert_image(fitz.Rect(40,80,120,140),stream=old.getvalue(),oc=layer)
                    doc.xref_set_key(xref,'StructParent','73');doc.save(source)
                if operation=='replace':
                    report=self.inspect(source);item=next(item for item in report['objects'] if item['kind']=='image')
                    output=self.apply(source,report,dict(id=item['id'],action='replace',image_path=str(asset)))
                else:
                    output=self.root/'layer-compressed.pdf';run('compress',[source],output,dict(image_dpi=72,quality=70))
                with fitz.open(output) as doc:
                    active=next(x for x,*_ in doc[0].get_images() if doc.xref_get_key(x,'StructParent')==('int','73'))
                    kind,value=doc.xref_get_key(active,'OC');self.assertEqual(kind,'xref')
                    self.assertEqual(doc.get_ocgs()[int(value.split()[0])]['on'],operation=='replace')
                    if operation=='compress': self.assertEqual(set(doc[0].get_pixmap().samples),{255})
                    else: self.assertIn(0,doc[0].get_pixmap().samples)

    def test_text_cmyk_spot_overprint_and_transfer_are_not_silently_recolored(self):
        cases=[('cmyk',b'0 1 1 0 k',None),
               ('spot',b'/Spot cs 1 scn',{'ColorSpace':'<< /Spot [/Separation /Ink /DeviceCMYK << /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [0 1 1 0] /N 1 >>] >>'}),
               ('overprint',b'/GS gs',{'ExtGState':'<< /GS << /op true >> >>'}),
               ('transfer',b'/GS gs',{'ExtGState':'<< /GS << /TR /Identity >> >>'})]
        for name,operator,resources in cases:
            with self.subTest(name=name):
                source=self.colored_text(name,operator,resources);before=source.read_bytes();report=self.inspect(source)
                item=next(item for item in report['objects'] if item['kind']=='text')
                self.assertFalse(item['editable']);self.assertIn('content-graphics-state-unproven',item['limitations'])
                with self.assertRaises(ValueError): self.apply(source,report,dict(id=item['id'],action='replace',text='Changed'))
                self.assertEqual(source.read_bytes(),before)

    def test_gray_and_rgb_text_retain_exact_source_components_without_byte_rounding(self):
        for name,operator,expected in [('gray',b'0.12345 g',('/DeviceGray',(0.12345,))),
                                       ('rgb',b'0.12345 0.54321 0.33333 rg',('/DeviceRGB',(0.12345,0.54321,0.33333)))]:
            source=self.colored_text(name,operator);report=self.inspect(source);item=next(item for item in report['objects'] if item['kind']=='text')
            self.assertTrue(item['editable'])
            output=self.apply(source,report,dict(id=item['id'],action='replace',text='Changed text'))
            with fitz.open(output) as doc:
                proof=source_states(doc,doc[0],doc[0].get_bboxlog(),include_text=True)
                self.assertEqual(list(proof.values()),[expected]);self.assertIn('Changed text',doc[0].get_text())

    def test_mixed_text_colors_in_one_text_object_map_to_the_correct_runs(self):
        source=self.root/'mixed.pdf'
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500);page.insert_text((30,50),'Initial')
            xref=page.get_contents()[0]
            doc.update_stream(xref,b'q BT /helv 12 Tf 1 0 0 1 30 430 Tm 0.12345 g (Gray original) Tj 0 -30 Td 0.9 0.2 0.1 rg (Red original) Tj ET Q')
            doc.save(source)
        report=self.inspect(source);gray=next(item for item in report['objects'] if item.get('text')=='Gray original')
        output=self.apply(source,report,dict(id=gray['id'],action='replace',text='Gray edited'))
        with fitz.open(output) as doc:
            proof=source_states(doc,doc[0],doc[0].get_bboxlog(),include_text=True)
            self.assertCountEqual(list(proof.values()),[('/DeviceGray',(0.12345,)),('/DeviceRGB',(0.9,0.2,0.1))])
            self.assertIn('Red original',doc[0].get_text())

    def test_unicode_composition_retains_gray_operators_and_actual_glyphs(self):
        source=self.colored_text('unicode',b'0.12345 g');report=self.inspect(source);item=next(item for item in report['objects'] if item['kind']=='text')
        output=self.apply(source,report,dict(id=item['id'],action='replace',text='Ação 世界 Ω',rect=[40,100,260,155],allow_font_substitution=True))
        with fitz.open(output) as doc:
            self.assertIn('Ação 世界 Ω',doc[0].get_text())
            streams=[doc.xref_stream(xref) for xref in doc[0].get_contents()]
            streams.extend(doc.xref_stream(xref) for xref,*_ in doc[0].get_xobjects())
            self.assertTrue(any(b'0.12345000 g' in stream for stream in streams))
            self.assertFalse(any(re.search(rb'(?<![A-Za-z])(?:rg|RG)(?![A-Za-z])',stream) for stream in streams))
            for trace in doc[0].get_texttrace():
                self.assertTrue(all(abs(component-0.12345)<0.0001 for component in trace['color']))

    def test_move_image_preserves_icc_decode_intent_stream_and_rendered_pixels(self):
        source=self.root/'icc-image.pdf'
        encoded=io.BytesIO();Image.new('RGB',(80,60),(210,45,90)).save(encoded,format='JPEG',quality=94)
        profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500);xref=page.insert_image(fitz.Rect(40,80,120,140),stream=encoded.getvalue())
            icc=doc.get_new_xref();doc.update_object(icc,'<< /N 3 /Alternate /DeviceRGB >>');doc.update_stream(icc,profile)
            doc.xref_set_key(xref,'ColorSpace',f'[/ICCBased {icc} 0 R]');doc.xref_set_key(xref,'Decode','[1 0 1 0 1 0]')
            doc.xref_set_key(xref,'Intent','/Saturation');page.insert_text((40,250),'Other content remains');doc.save(source)
        before_bytes=source.read_bytes();report=self.inspect(source);item=next(item for item in report['objects'] if item['kind']=='image')
        self.assertIn('move',item['supported_actions'])
        output=self.apply(source,report,dict(id=item['id'],action='move',rect=[250,80,330,140]))
        with fitz.open(source) as before,fitz.open(output) as after:
            original=before[0].get_image_info(xrefs=True)[0]['xref']
            moved=next(info for info in after[0].get_image_info(xrefs=True) if tuple(info['bbox'])==(250,80,330,140))['xref']
            for key in ('Width','Height','BitsPerComponent','Decode','Intent','Filter'):
                self.assertEqual(after.xref_get_key(moved,key),before.xref_get_key(original,key))
            self.assertEqual(after.xref_stream_raw(moved),before.xref_stream_raw(original))
            self.assertEqual(after.xref_stream(moved),before.xref_stream(original))
            color=after.xref_get_key(moved,'ColorSpace')[1];self.assertIn('/ICCBased',color)
            new_icc=int(re.search(r'(\d+) 0 R',color).group(1));self.assertEqual(after.xref_stream(new_icc),profile)
            self.assertEqual(after[0].get_pixmap(clip=fitz.Rect(250,80,330,140)).samples,before[0].get_pixmap(clip=fitz.Rect(40,80,120,140)).samples)
            self.assertIn('Other content remains',after[0].get_text())
        self.assertEqual(source.read_bytes(),before_bytes)

    def test_image_with_overprint_context_keeps_position_required_for_that_context(self):
        source=self.root/'overprint-image.pdf';encoded=io.BytesIO();Image.new('RGB',(20,20),'red').save(encoded,format='PNG')
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500);page.insert_image(fitz.Rect(40,80,120,140),stream=encoded.getvalue())
            resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0]);doc.xref_set_key(resources,'ExtGState','<< /GS << /op true >> >>')
            for xref in page.get_contents(): doc.update_stream(xref,b'q /GS gs\n'+doc.xref_stream(xref)+b'\nQ')
            doc.save(source)
        report=self.inspect(source);item=next(item for item in report['objects'] if item['kind']=='image')
        self.assertEqual(item['supported_actions'],['replace','delete']);self.assertTrue(item['editable'])
        with self.assertRaisesRegex(ValueError,'recorte'):
            self.apply(source,report,dict(id=item['id'],action='move',rect=[250,80,330,140]))

    def test_replacement_image_keeps_its_real_embedded_icc_profile(self):
        source=self.root/'replacement.pdf';asset=self.root/'profiled.png'
        profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.new('RGB',(80,60),(45,70,210)).save(asset,format='PNG',icc_profile=profile)
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500);page.insert_image(fitz.Rect(40,80,120,140),filename=str(asset));doc.save(source)
        report=self.inspect(source);item=next(item for item in report['objects'] if item['kind']=='image')
        output=self.apply(source,report,dict(id=item['id'],action='replace',image_path=str(asset)))
        with fitz.open(output) as doc:
            xref=doc[0].get_image_info(xrefs=True)[0]['xref'];kind,space=doc.xref_get_key(xref,'ColorSpace')
            if kind=='xref': space=doc.xref_object(int(space.split()[0]))
            self.assertIn('/ICCBased',space);profile_xref=int(re.search(r'(\d+) 0 R',space).group(1))
            self.assertEqual(doc.xref_stream(profile_xref),profile);self.assertEqual(doc.xref_get_key(profile_xref,'N'),('int','3'))

    def test_invalid_embedded_replacement_profile_refuses_before_publication(self):
        source=self.root/'invalid-profile.pdf';asset=self.root/'invalid.png';image=io.BytesIO()
        Image.new('RGB',(20,20),'red').save(image,format='PNG')
        Image.new('RGB',(20,20),'blue').save(asset,format='PNG',icc_profile=b'not a valid ICC profile')
        with fitz.open() as doc: doc.new_page().insert_image(fitz.Rect(40,80,120,140),stream=image.getvalue());doc.save(source)
        report=self.inspect(source);item=next(item for item in report['objects'] if item['kind']=='image')
        with self.assertRaisesRegex(ValueError,'ICC'):
            self.apply(source,report,dict(id=item['id'],action='replace',image_path=str(asset)))
        self.assertFalse(source.with_name(source.stem+'-edited.pdf').exists())

    def test_identical_replacement_cannot_erase_its_deduplicated_image_object(self):
        source=self.root/'deduplicated.pdf';asset=self.root/'same.png'
        Image.new('RGB',(80,60),(30,120,220)).save(asset,format='PNG')
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500);page.insert_image(fitz.Rect(40,80,120,140),filename=str(asset))
            page.insert_text((40,100),'Above image',color=(1,1,1));doc.save(source)
        report=self.inspect(source);item=next(item for item in report['objects'] if item['kind']=='image')
        output=self.apply(source,report,dict(id=item['id'],action='replace',image_path=str(asset)))
        with fitz.open(source) as before,fitz.open(output) as after:
            self.assertEqual(after[0].get_pixmap().samples,before[0].get_pixmap().samples)
            self.assertEqual(len(after[0].get_image_info()),1);self.assertIn('Above image',after[0].get_text())

    def test_image_compression_preserves_profiles_decode_intent_and_color_key_masks(self):
        profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        for name in ('icc','decode','intent','mask'):
            with self.subTest(name=name):
                source=self.root/f'compress-{name}.pdf';target=self.root/f'compressed-{name}.pdf'
                encoded=io.BytesIO();Image.new('RGB',(800,600),(100,120,140)).save(encoded,format='PNG')
                with fitz.open() as doc:
                    page=doc.new_page(width=400,height=500);xref=page.insert_image(fitz.Rect(40,80,120,140),stream=encoded.getvalue())
                    if name=='icc':
                        icc=doc.get_new_xref();doc.update_object(icc,'<< /N 3 /Alternate /DeviceRGB >>');doc.update_stream(icc,profile)
                        doc.xref_set_key(xref,'ColorSpace',f'[/ICCBased {icc} 0 R]')
                    if name=='decode': doc.xref_set_key(xref,'Decode','[1 0 1 0 1 0]')
                    if name=='intent': doc.xref_set_key(xref,'Intent','/Saturation')
                    if name=='mask': doc.xref_set_key(xref,'Mask','[0 0 0 0 0 0]')
                    doc.save(source)
                run('compress',[source],target,{'image_dpi':72,'quality':80})
                with fitz.open(source) as before,fitz.open(target) as after:
                    original=before[0].get_images()[0][0];retained=after[0].get_images()[0][0]
                    self.assertEqual(after.xref_stream(retained),before.xref_stream(original))
                    for key in ('Width','Height','Decode','Intent','Mask'):
                        self.assertEqual(after.xref_get_key(retained,key),before.xref_get_key(original,key))
                    self.assertEqual(after[0].get_pixmap().samples,before[0].get_pixmap().samples)
                    if name=='icc':
                        from pdf_content import _embedded_image_profile
                        self.assertEqual(_embedded_image_profile(after,retained),('/ICCBased',3,profile))
                        self.assertEqual(after.xref_get_key(retained,'Width'),('int','800'))
                        self.assertEqual(after.xref_get_key(retained,'Height'),('int','600'))

    def test_supported_gray_and_rgb_images_still_downsample_in_the_same_color_model(self):
        for mode,space in [('L','/DeviceGray'),('RGB','/DeviceRGB')]:
            source=self.root/f'compress-{mode}.pdf';target=self.root/f'compressed-{mode}.pdf';encoded=io.BytesIO()
            Image.new(mode,(800,600),100 if mode=='L' else (100,120,140)).save(encoded,format='PNG')
            with fitz.open() as doc:
                xref=doc.new_page().insert_image(fitz.Rect(40,80,120,140),stream=encoded.getvalue())
                # This control deliberately uses uncalibrated samples. PNG
                # import may attach a default ICC profile, covered separately.
                doc.xref_set_key(xref,'ColorSpace',space);doc.save(source)
            run('compress',[source],target,{'image_dpi':72,'quality':80})
            with fitz.open(target) as after:
                image=after[0].get_image_info(xrefs=True)[0];self.assertEqual((image['width'],image['height']),(80,60))
                from pdf_content import _embedded_image_profile
                kind,channels,profile=_embedded_image_profile(after,image['xref'])
                if kind=='/ICCBased':
                    from print_inspection import icc_description
                    self.assertEqual((icc_description(profile)['color_space'],channels),('GRAY',1) if mode=='L' else ('RGB',3))
                else: self.assertEqual(kind,space)

    def test_cmyk_image_compression_keeps_original_channels_and_samples(self):
        source=self.root/'cmyk-image.pdf';target=self.root/'cmyk-compressed.pdf';encoded=io.BytesIO()
        Image.new('CMYK',(800,600),(0,120,220,15)).save(encoded,format='JPEG',quality=94)
        with fitz.open() as doc: doc.new_page().insert_image(fitz.Rect(40,80,120,140),stream=encoded.getvalue());doc.save(source)
        run('compress',[source],target,{'image_dpi':72,'quality':80})
        with fitz.open(source) as before,fitz.open(target) as after:
            first=before[0].get_image_info(xrefs=True)[0];second=after[0].get_image_info(xrefs=True)[0]
            self.assertEqual((second['width'],second['height']),(800,600))
            self.assertEqual(after.xref_stream(second['xref']),before.xref_stream(first['xref']))
            self.assertEqual(after[0].get_pixmap().samples,before[0].get_pixmap().samples)
