"""Original macOS PDFs, retained ICC Gray paint, and explicit font consent."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
import unittest

import fitz
from PIL import Image,ImageChops,ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
from pdf_vector_state import source_states

FIXTURES=Path(__file__).parent/'fixtures'/'coregraphics-gray'
HASHES={'macos-26':'396a5c61a8497d47d39b78fb4751be67e6193b98ddab14c822f0f71d73707df1',
        'xcode-27':'c84bf9016b70a1b39d0aa4b7c3f534a46d6e873c73e96d7f51220e12fccbd6ee'}
PROFILE_SHA='73d504558e7d03ef4ff2676ba62c7553ee5bd856b45da2d330e33e012ad61fb3'


class NativeGrayContentTests(unittest.TestCase):
    def setUp(self): self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self): self.assertFalse(list(self.root.glob('.pdf-output-*')));self.temp.cleanup()

    def inspect(self,source):
        report=self.root/(source.stem+'.json');run('content-inspect',[source],report)
        data=json.loads(report.read_text());return data,next(o for o in data['objects'] if o['kind']=='text')

    def edit(self,source,report,item,**options):
        target=self.root/(source.stem+'-edited.pdf')
        run('content-apply',[source],target,dict(source_sha256=report['source_sha256'],edits=[dict(id=item['id'],action='replace',text=item['text'],**options)]))
        return target

    def native(self,name,gray=0,extra_page=False):
        original=FIXTURES/(name+'.pdf');self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),HASHES[name])
        if gray==0 and not extra_page: return original
        target=self.root/(name+f'-gray-{gray}.pdf')
        with fitz.open(original) as doc:
            replacements=0
            for xref in doc[0].get_contents():
                data=doc.xref_stream(xref);replacements+=data.count(b'/Cs1 cs 0 sc')
                doc.update_stream(xref,data.replace(b'/Cs1 cs 0 sc',f'/Cs1 cs {gray} sc'.encode()))
            self.assertEqual(replacements,1)
            if extra_page:
                page=doc.new_page();page.insert_text((30,70),'Independent page');page.draw_rect(fitz.Rect(30,100,100,150),color=(1,0,0))
            doc.save(target)
        return target

    def profile(self):
        with fitz.open(FIXTURES/'macos-26.pdf') as doc: return doc.xref_stream(7)

    def simple(self,gray=0.4):
        target=self.root/'simple-profile.pdf'
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500);page.insert_text((40,80),'Original gray text',fontsize=18,color=(gray,))
            profile=doc.get_new_xref();doc.update_object(profile,'<< /N 1 /Alternate /DeviceGray >>');doc.update_stream(profile,self.profile())
            resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
            doc.xref_set_key(resources,'ColorSpace',f'<< /Cs1 [/ICCBased {profile} 0 R] /PDFContentGray0 /DeviceRGB >>')
            for xref in page.get_contents():
                data,count=re.subn(rb'[-+]?(?:\d*\.)?\d+ g\b',f'/Cs1 cs {gray} sc'.encode(),doc.xref_stream(xref))
                self.assertEqual(count,1);doc.update_stream(xref,data)
            page.draw_rect(fitz.Rect(340,400,360,420),color=None,fill=(1,1,1))
            active=page.get_contents()[-1];data=doc.xref_stream(active)
            self.assertIn(b'1 1 1 rg',data)
            doc.update_stream(active,data.replace(b'1 1 1 rg',b'/PDFContentGray0 cs 1 1 1 sc'))
            doc.save(target)
        return target

    def assert_profile_paint(self,source,result,gray):
        with fitz.open(source) as before,fitz.open(result) as after:
            expected=before[0].get_texttrace()[0]['color']
            self.assertTrue(all(trace['color']==expected for trace in after[0].get_texttrace()))
            a=before[0].get_pixmap(matrix=fitz.Matrix(3,3));b=after[0].get_pixmap(matrix=fitz.Matrix(3,3))
            # Opaque interior pixels prove the actual profile transform; glyph
            # positions/metrics may change after explicitly consented shaping.
            self.assertEqual(min(a.samples),min(b.samples))
            profiles=[after.xref_stream(xref) for xref in range(1,after.xref_length()) if after.xref_get_key(xref,'N')==('int','1') and after.xref_is_stream(xref)]
            self.assertIn(PROFILE_SHA,[hashlib.sha256(data).hexdigest() for data in profiles])
            streams=[after.xref_stream(x) for x in after[0].get_contents()]
            streams.extend(after.xref_stream(x) for x,*_ in after[0].get_xobjects())
            components=[float(value) for stream in streams for value in re.findall(rb'/PDFContentGray\d+ cs ([0-9.]+) sc',stream)]
            self.assertTrue(components);self.assertTrue(all(value==gray for value in components))

    def test_both_immutable_native_originals_are_inspected_and_preserve_icc_black(self):
        for name in HASHES:
            with self.subTest(name=name):
                source=self.native(name);report,item=self.inspect(source);self.assertTrue(item['editable'])
                result=self.edit(source,report,item,rect=[72,100,400,160],allow_font_substitution=True)
                self.assert_profile_paint(source,result,0)
                with fitz.open(result) as doc:
                    self.assertEqual(unicodedata.normalize('NFKC',doc[0].get_text()).strip(),item['text'])
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),HASHES[name])

    def test_native_gray_point_four_is_preserved_beyond_black_with_other_page_intact(self):
        for name in HASHES:
            with self.subTest(name=name):
                source=self.native(name,0.4,True);report,item=self.inspect(source)
                result=self.edit(source,report,item,rect=[72,200,400,260],allow_font_substitution=True)
                self.assert_profile_paint(source,result,0.4)
                with fitz.open(source) as before,fitz.open(result) as after:
                    self.assertEqual(before[1].get_pixmap().samples,after[1].get_pixmap().samples)
                    images=[]
                    for doc in (before,after):
                        pix=doc[0].get_pixmap();image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                        draw=ImageDraw.Draw(image)
                        for rect in (item['rect'],[72,200,400,260]): draw.rectangle(tuple(fitz.Rect(rect)+(-2,-2,2,2)),fill='white')
                        images.append(image)
                    self.assertIsNone(ImageChops.difference(*images).getbbox())

    def test_native_substitution_still_requires_explicit_consent_and_publishes_nothing(self):
        for name in HASHES:
            with self.subTest(name=name):
                source=self.native(name);report,item=self.inspect(source)
                self.assertEqual(item['font_status'],'substitution-required')
                with self.assertRaisesRegex(ValueError,'substitui'): self.edit(source,report,item,rect=[72,100,400,160])
                self.assertFalse((self.root/(source.stem+'-edited.pdf')).exists())

    def test_profiled_simple_text_remains_editable_and_avoids_existing_resource_names(self):
        source=self.simple();report,item=self.inspect(source);self.assertTrue(item['editable']);self.assertEqual(item['font_status'],'original')
        result=self.edit(source,report,item,rect=[40,180,350,220],character_spacing=0.5)
        self.assert_profile_paint(source,result,0.4)
        again,edited=self.inspect(result);self.assertTrue(edited['editable'])
        with fitz.open(result) as doc:
            proof=source_states(doc,doc[0],doc[0].get_bboxlog(),include_text=True)
            color=next(color for color in proof.values() if isinstance(color[0],tuple));self.assertEqual(color[0][:2],('/ICCBased',1));self.assertEqual(color[1],(0.4,))
            self.assertIn(b'/PDFContentGray1 cs',b''.join(doc.xref_stream(x) for x in doc[0].get_contents()))

    def test_explicit_recolor_uses_the_requested_rgb_instead_of_reattaching_source_profile(self):
        source=self.simple();report,item=self.inspect(source)
        result=self.edit(source,report,item,rect=[40,180,350,220],color='#ff0000')
        with fitz.open(result) as doc:
            proof=source_states(doc,doc[0],doc[0].get_bboxlog(),include_text=True)
            self.assertIn(('/DeviceRGB',(1,0,0)),proof.values())
            self.assertTrue(all(color[0]=='/DeviceRGB' for color in proof.values()))

    def test_mixed_native_gray_and_non_srgb_text_preserve_each_profile_and_actual_color(self):
        from test_editing_color_regressions import EditingColorRegressionTests
        profile=EditingColorRegressionTests.non_srgb_profile();components=(0.12345,0.34567,0.7)
        for name in HASHES:
            source=self.root/(name+'-mixed.pdf')
            with fitz.open(FIXTURES/(name+'.pdf')) as doc:
                page=doc[0];page.insert_text((72,180),'ICC RGB colored heading',fontsize=18,color=components)
                profile_xref=doc.get_new_xref();doc.update_object(profile_xref,'<< /N 3 /Alternate /DeviceRGB /Range [0 1 0 1 0 1] >>');doc.update_stream(profile_xref,profile)
                resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
                doc.xref_set_key(resources,'ColorSpace/RGBProof',f'[/ICCBased {profile_xref} 0 R]')
                xref=page.get_contents()[-1];data=doc.xref_stream(xref)
                numbers=' '.join(str(value) for value in components)
                for operator in ('rg','RG'):
                    pattern=rb'(?:[-+]?(?:\d*\.)?\d+ +){3}'+operator.encode()+rb'\b'
                    replacement=('/RGBProof '+('cs' if operator=='rg' else 'CS')+' '+numbers+' '+('sc' if operator=='rg' else 'SC')).encode()
                    data,count=re.subn(pattern,replacement,data);self.assertEqual(count,1)
                doc.update_stream(xref,data);doc.save(source)
            report,_=self.inspect(source);texts=[item for item in report['objects'] if item['kind']=='text']
            self.assertTrue(all(item['editable'] for item in texts));rgb=next(item for item in texts if item['text'].startswith('ICC'))
            with fitz.open(source) as doc:
                expected=doc[0].get_texttrace()[-1]['color']
                self.assertTrue(any(abs(a-b)>0.05 for a,b in zip(expected,components)),'The profile must prove a non-identity transform.')
                original_black=doc[0].get_pixmap(clip=fitz.Rect(60,90,320,135)).samples
            for unicode_text in (False,True):
                with self.subTest(name=name,unicode=unicode_text):
                    target=self.root/(name+f'-rgb-{unicode_text}.pdf')
                    text='Ação 世界 Ω' if unicode_text else rgb['text']
                    run('content-apply',[source],target,dict(source_sha256=report['source_sha256'],edits=[dict(id=rgb['id'],action='replace',text=text,rect=[72,240,500,300],color=rgb['color'],allow_font_substitution=unicode_text)]))
                    with fitz.open(target) as doc:
                        traces=doc[0].get_texttrace();self.assertTrue(all(trace['color']==expected for trace in traces[1:]))
                        self.assertEqual(doc[0].get_pixmap(clip=fitz.Rect(60,90,320,135)).samples,original_black)
                        self.assertIn(text,unicodedata.normalize('NFKC',doc[0].get_text()))
                        preserved=[doc.xref_stream(x) for x in range(1,doc.xref_length()) if doc.xref_get_key(x,'N')==('int','3') and doc.xref_is_stream(x)]
                        self.assertIn(profile,preserved)
                        streams=[doc.xref_stream(x) for x in doc[0].get_contents()]+[doc.xref_stream(x) for x,*_ in doc[0].get_xobjects()]
                        values=[tuple(float(v) for v in match.split()) for stream in streams for match in re.findall(rb'/PDFContentRGB\d+ cs ([0-9. ]+) sc',stream)]
                        self.assertTrue(values);self.assertTrue(all(value==components for value in values))

    def test_profile_binding_preserves_non_ascii_resource_name_bytes_and_other_glyphs(self):
        source=self.simple();renamed=self.root/'latin1.pdf'
        with fitz.open(source) as doc:
            page=doc[0];page.insert_text((40,350),'Unchanged glyphs',fontsize=18)
            resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
            raw=doc.xref_object(resources,compressed=False);self.assertIn('/helv',raw)
            doc.update_object(resources,raw.replace('/helv','/F#E9'))
            for x in page.get_contents(): doc.update_stream(x,doc.xref_stream(x).replace(b'/helv',b'/F#E9'))
            doc.save(renamed)
        report,item=self.inspect(renamed);self.assertTrue(item['editable'])
        result=self.edit(renamed,report,item,rect=[40,180,350,220])
        with fitz.open(renamed) as before,fitz.open(result) as after:
            clip=fitz.Rect(25,325,250,375)
            self.assertEqual(before[0].get_pixmap(clip=clip).samples,after[0].get_pixmap(clip=clip).samples)
            self.assertIn('Unchanged glyphs',after[0].get_text())
            resources=int(after.xref_get_key(after[0].xref,'Resources')[1].split()[0])
            kind,fonts=after.xref_get_key(resources,'Font')
            if kind=='xref': fonts=after.xref_object(int(fonts.split()[0]))
            self.assertIn('/F#E9',fonts);self.assertNotIn('/F#C3#A9',fonts)

    def test_partial_clip_and_non_gray_profile_remain_readonly(self):
        for variation in ('partial','channels'):
            with self.subTest(variation=variation):
                source=self.root/(variation+'.pdf')
                with fitz.open(FIXTURES/'macos-26.pdf') as doc:
                    if variation=='partial':
                        for x in doc[0].get_contents(): doc.update_stream(x,doc.xref_stream(x).replace(b'0 0 595 842 re W n',b'0 0 300 842 re W n'))
                    else: doc.xref_set_key(7,'N','3')
                    doc.save(source)
                _,item=self.inspect(source);self.assertFalse(item['editable'])
                self.assertIn('content-graphics-state-unproven',item['limitations'])


if __name__=='__main__': unittest.main()
