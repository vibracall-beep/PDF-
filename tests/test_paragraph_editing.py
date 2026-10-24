"""Source-bound multiline edits on real PDF content, including refusal paths."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import unicodedata

import fitz
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run


class ParagraphEditingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source.pdf'
        with fitz.open() as doc:
            page=doc.new_page(width=500,height=600)
            page.insert_text((40,70),'First sentence here.\nSecond line here.\nThird line here.',fontsize=12)
            page.insert_text((330,80),'Neighbor stays',fontsize=12)
            page.draw_rect(fitz.Rect(40,350,180,410),color=(0,0,1))
            image=io.BytesIO();Image.new('RGB',(20,20),(200,20,30)).save(image,format='PNG')
            page.insert_image(fitz.Rect(250,350,300,400),stream=image.getvalue())
            page.add_text_annot((350,350),'Private annotation remains')
            doc.new_page(width=500,height=600).insert_text((40,70),'Untouched second page')
            doc.save(self.source)
        self.original=self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertFalse(list(self.root.glob('.pdf-output-*')))
        self.temp.cleanup()

    def inspect(self,source=None,options=None):
        target=self.root/('inspection-'+str(len(list(self.root.glob('inspection-*'))))+'.json')
        run('content-inspect',[source or self.source],target,options or {})
        report=json.loads(target.read_text())
        return report,next(item for item in report['objects'] if item['kind']=='paragraph')

    def apply(self,report,edits,source=None,options=None):
        target=self.root/'edited.pdf'
        run('content-apply',[source or self.source],target,dict(source_sha256=report['source_sha256'],edits=edits,**(options or {})))
        return target

    def test_group_is_stable_flat_and_keeps_individual_source_runs(self):
        report,group=self.inspect();again,_=self.inspect();self.assertEqual(report,again)
        members=[item for item in report['objects'] if item['id'] in group['member_ids']]
        self.assertEqual(len(members),3);self.assertTrue(all(item['kind']=='text' and item['page']==1 for item in members))
        self.assertEqual(group['text'],'\n'.join(item['text'] for item in members))
        self.assertTrue(group['editable']);self.assertEqual(group['alignment'],'left')
        self.assertAlmostEqual(group['line_spacing'],1.374,places=3)

    def test_replace_whole_paragraph_at_original_bounds_preserves_neighbors(self):
        report,group=self.inspect();target=self.apply(report,[dict(id=group['id'],action='replace',text='New first line.\nSecond changed.\nThird changed.')])
        with fitz.open(target) as result,fitz.open(self.source) as before:
            text=result[0].get_text();self.assertNotIn('First sentence',text)
            for value in ('New first line.','Second changed.','Third changed.','Neighbor stays'): self.assertIn(value,text)
            self.assertEqual(result[1].get_pixmap().samples,before[1].get_pixmap().samples)
            self.assertEqual(result[0].get_image_info()[0]['bbox'],before[0].get_image_info()[0]['bbox'])
            self.assertEqual(len(result[0].get_drawings()),len(before[0].get_drawings()))
            self.assertEqual(next(result[0].annots()).info['content'],'Private annotation remains')
            area=fitz.Rect(group['rect'])+(-0.05,-0.05,0.05,0.05)
            self.assertTrue(all(area.contains(rect) for text in ('New first line.','Second changed.','Third changed.') for rect in result[0].search_for(text)))

    def test_multiline_reflow_alignment_and_line_spacing_use_actual_geometry(self):
        report,group=self.inspect();rect=[40,150,240,285]
        target=self.apply(report,[dict(id=group['id'],action='replace',rect=rect,text='A short first line\nA second line\nLast line',alignment='right',line_spacing=2,font_size=12)])
        with fitz.open(target) as doc:
            lines=[line for block in doc[0].get_text('dict')['blocks'] if block['type']==0 for line in block['lines'] if 149<line['bbox'][1]<285]
            self.assertEqual(len(lines),3)
            for line in lines: self.assertAlmostEqual(line['bbox'][2],240,places=2)
            self.assertAlmostEqual(lines[1]['spans'][0]['origin'][1]-lines[0]['spans'][0]['origin'][1],24,places=2)
            self.assertNotIn('First sentence',doc[0].get_text())

    def test_reflow_wraps_without_losing_words(self):
        report,group=self.inspect();replacement='These words must all survive while a longer paragraph wraps into several separate lines.'
        target=self.apply(report,[dict(id=group['id'],action='replace',rect=[40,145,220,320],text=replacement,line_spacing=1.6)])
        with fitz.open(target) as doc:
            words=[word[4] for word in doc[0].get_text('words') if fitz.Rect([40,145,220,320]).contains(fitz.Rect(word[:4]))]
            self.assertEqual(words,replacement.split())

    def test_group_and_member_conflict_refuses_all_actions_without_publication(self):
        report,group=self.inspect()
        for edits in ([dict(id=group['id'],action='delete'),dict(id=group['member_ids'][0],action='delete')],
                      [dict(id=group['member_ids'][0],action='replace',text='Short'),dict(id=group['id'],action='move',rect=[40,140,240,260])]):
            with self.assertRaisesRegex(ValueError,'parágrafo'): self.apply(report,edits)
            self.assertFalse((self.root/'edited.pdf').exists())

    def test_individual_span_remains_editable_when_parent_group_exists(self):
        report,group=self.inspect();target=self.apply(report,[dict(id=group['member_ids'][0],action='replace',text='Individual line.')])
        with fitz.open(target) as doc:
            self.assertIn('Individual line.',doc[0].get_text());self.assertIn('Second line here.',doc[0].get_text())

    def test_paragraph_destinations_refuse_text_images_vectors_and_annotations(self):
        report,group=self.inspect()
        for rect in ([320,50,480,120],[220,330,320,420],[20,330,190,420],[330,330,450,410]):
            with self.subTest(rect=rect),self.assertRaises(ValueError):
                self.apply(report,[dict(id=group['id'],action='move',rect=rect)])
            self.assertFalse((self.root/'edited.pdf').exists())

    def test_new_destinations_cannot_collide_with_another_planned_edit(self):
        report,group=self.inspect();neighbor=next(item for item in report['objects'] if item.get('text')=='Neighbor stays')
        edits=[dict(id=neighbor['id'],action='move',rect=[50,180,240,210]),
               dict(id=group['id'],action='move',rect=[40,150,250,270])]
        for order in (edits,list(reversed(edits))):
            with self.assertRaisesRegex(ValueError,'destino'): self.apply(report,order)
            self.assertFalse((self.root/'edited.pdf').exists())

    def test_overflow_spacing_and_source_tampering_refuse_atomically(self):
        report,group=self.inspect()
        for change in (dict(text='Overflow '*1000),dict(line_spacing=0.99),dict(line_spacing=3.01),dict(line_spacing=float('nan'))):
            with self.subTest(keys=list(change)),self.assertRaises(ValueError):
                self.apply(report,[dict(id=group['id'],action='replace',**change)])
            self.assertFalse((self.root/'edited.pdf').exists())
        report['source_sha256']=hashlib.sha256(b'other source').hexdigest()
        with self.assertRaises(ValueError): self.apply(report,[dict(id=group['id'],action='delete')])

    def test_mixed_styles_do_not_form_a_homogeneous_paragraph(self):
        source=self.root/'mixed.pdf'
        with fitz.open() as doc:
            page=doc.new_page();page.insert_text((40,70),'Regular line',fontsize=12)
            page.insert_text((40,86.488),'Bold line',fontsize=12,fontname='hebo');doc.save(source)
        target=self.root/'mixed.json';run('content-inspect',[source],target)
        self.assertFalse(any(item['kind']=='paragraph' for item in json.loads(target.read_text())['objects']))

    def test_unicode_composition_requires_consent_and_retains_combining_and_cjk_text(self):
        report,group=self.inspect();text='Ação e cafe\u0301\n世界 Ω'
        edit=dict(id=group['id'],action='replace',rect=[40,140,240,290],text=text,line_spacing=2)
        with self.assertRaisesRegex(ValueError,'fonte'): self.apply(report,[edit])
        self.assertFalse((self.root/'edited.pdf').exists())
        target=self.apply(report,[dict(**edit,allow_font_substitution=True)])
        with fitz.open(target) as doc:
            content=unicodedata.normalize('NFC',doc[0].get_text())
            self.assertIn('Ação e café',content);self.assertIn('世界 Ω',content);self.assertNotIn('??',content)

    def test_annotation_isolation_does_not_hide_real_content_clipping(self):
        source=self.root/'clipped.pdf'
        with fitz.open() as doc:
            page=doc.new_page(width=500,height=600)
            page.insert_text((40,70),'First sentence here.\nSecond line here.\nThird line here.',fontsize=12)
            for xref in page.get_contents(): doc.update_stream(xref,b'q\n40 480 30 100 re W n\n'+doc.xref_stream(xref)+b'\nQ')
            page.add_text_annot((350,350),'Unrelated annotation');doc.save(source)
        report,group=self.inspect(source)
        self.assertFalse(group['editable']);self.assertIn('clipped-page-content',group['limitations'])
        with self.assertRaises(ValueError): self.apply(report,[dict(id=group['id'],action='delete')],source)
        self.assertFalse((self.root/'edited.pdf').exists())

    def test_protected_cropped_rotated_duplicate_pages_remain_independent(self):
        protected=self.root/'protected.pdf';password='paragraph-test-reader'
        with fitz.open(self.source) as doc:
            doc[0].set_cropbox(fitz.Rect(20,20,480,580));doc[0].set_rotation(90);doc.select([0,0])
            doc.save(protected,encryption=fitz.PDF_ENCRYPT_AES_256,user_pw=password,owner_pw='paragraph-test-owner',permissions=fitz.PDF_PERM_PRINT|fitz.PDF_PERM_ACCESSIBILITY)
        report,group=self.inspect(protected,dict(password=password))
        target=self.apply(report,[dict(id=group['id'],action='replace',text='Changed line.\nSecond changed.\nThird changed.')],protected,dict(password=password))
        with fitz.open(target) as doc,fitz.open(protected) as before:
            self.assertTrue(doc.needs_pass);self.assertFalse(doc.authenticate('wrong'));doc.authenticate(password);before.authenticate(password)
            self.assertEqual(doc.permissions,before.permissions);self.assertEqual(doc[0].cropbox,before[0].cropbox);self.assertEqual(doc[0].rotation,90)
            self.assertIn('Changed line.',doc[0].get_text());self.assertIn('First sentence here.',doc[1].get_text())
            self.assertEqual(doc[1].get_pixmap().samples,before[1].get_pixmap().samples)
