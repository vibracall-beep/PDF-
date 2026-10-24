"""Real PDF object edits: source binding, geometry, fonts and preservation."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run


class ContentEditingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'original.pdf'
        picture=io.BytesIO();Image.new('RGB',(40,30),(230,20,30)).save(picture,format='PNG')
        self.image=picture.getvalue()
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500)
            page.insert_text((40,60),'Original content',fontsize=14)
            page.insert_text((40,110),'Keep this paragraph',fontsize=12)
            page.draw_rect(fitz.Rect(25,180,190,300),color=(0,0.5,0),width=2)
            page.insert_image(fitz.Rect(40,200,120,260),stream=self.image)
            doc.new_page(width=400,height=500).insert_text((40,60),'Unselected page')
            doc.set_metadata({'title':'Content audit','author':'Fixture'})
            doc.save(self.source)
        self.original=self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertFalse(list(self.root.glob('.pdf-output-*')))
        self.tmp.cleanup()

    def inspect(self,source=None,options=None):
        report=self.root/('inspect-'+str(len(list(self.root.glob('inspect*'))))+'.json')
        run('content-inspect',[source or self.source],report,options or {})
        self.assertEqual(report.stat().st_mode&0o777,0o600)
        return json.loads(report.read_text())

    def text_object(self,report):
        return next(item for item in report['objects'] if item.get('text')=='Original content')

    def apply(self,report,edits,source=None,options=None):
        output=self.root/'edited.pdf'
        run('content-apply',[source or self.source],output,dict(source_sha256=report['source_sha256'],edits=edits,**(options or {})))
        return output

    def test_inspection_ids_are_stable_and_bound_to_exact_bytes(self):
        report=self.inspect();again=self.inspect()
        self.assertEqual(report,again)
        self.assertEqual(report['source_sha256'],hashlib.sha256(self.original).hexdigest())
        self.assertEqual(report['page_count'],2)
        self.assertEqual(self.text_object(report)['font_status'],'original')

    def test_replace_original_text_preserves_other_objects_and_metadata(self):
        report=self.inspect();obj=self.text_object(report)
        output=self.apply(report,[dict(id=obj['id'],action='replace',text='Edited content')])
        with fitz.open(output) as result,fitz.open(self.source) as before:
            self.assertIn('Edited content',result[0].get_text());self.assertNotIn('Original content',result[0].get_text())
            self.assertIn('Keep this paragraph',result[0].get_text())
            self.assertEqual(result[1].get_pixmap().samples,before[1].get_pixmap().samples)
            self.assertEqual(result.metadata['title'],'Content audit')
            self.assertEqual(len(result[0].get_drawings()),len(before[0].get_drawings()))
            self.assertEqual(result[0].get_image_info()[0]['bbox'],before[0].get_image_info()[0]['bbox'])

    def test_move_and_alignment_apply_to_original_object(self):
        report=self.inspect();obj=self.text_object(report)
        output=self.apply(report,[dict(id=obj['id'],action='move',rect=[200,350,390,390],alignment='right')])
        with fitz.open(output) as doc:
            found=doc[0].search_for('Original content');self.assertEqual(len(found),1)
            self.assertGreater(found[0].y0,349);self.assertAlmostEqual(found[0].x1,390,places=3)

    def test_delete_removes_selected_original_text(self):
        report=self.inspect();output=self.apply(report,[dict(id=self.text_object(report)['id'],action='delete')])
        with fitz.open(output) as doc:
            self.assertNotIn('Original content',doc[0].get_text());self.assertIn('Keep this paragraph',doc[0].get_text())

    def test_stale_source_unknown_identity_and_duplicate_edits_refuse_atomically(self):
        report=self.inspect();edit=dict(id=self.text_object(report)['id'],action='delete')
        for options in [dict(source_sha256='0'*64,edits=[edit]),dict(source_sha256=report['source_sha256'],edits=[dict(id='unknown',action='delete')]),dict(source_sha256=report['source_sha256'],edits=[edit,edit])]:
            with self.subTest(options=list(options)),self.assertRaises(ValueError):
                run('content-apply',[self.source],self.root/'rejected.pdf',options)
            self.assertFalse((self.root/'rejected.pdf').exists())

    def test_overflow_and_overlapping_destination_do_not_delete_original(self):
        report=self.inspect();identity=self.text_object(report)['id']
        for edit in [dict(id=identity,action='replace',text='too long '*100),dict(id=identity,action='move',rect=[30,90,300,130])]:
            with self.subTest(edit=edit['action']),self.assertRaises(ValueError): self.apply(report,[edit])
            self.assertFalse((self.root/'edited.pdf').exists())

    def test_unicode_font_substitution_is_explicit_and_preserves_text(self):
        report=self.inspect();edit=dict(id=self.text_object(report)['id'],action='replace',text='世界 Ω',rect=[40,40,190,80])
        with self.assertRaisesRegex(ValueError,'fonte'): self.apply(report,[edit])
        output=self.apply(report,[dict(**edit,allow_font_substitution=True)])
        with fitz.open(output) as doc:
            text=doc[0].get_text();self.assertIn('世界',text);self.assertIn('Ω',text);self.assertNotIn('??',text)

    def test_encrypted_edit_retains_password_and_permissions(self):
        protected=self.root/'protected.pdf';password='content-audit-password'
        with fitz.open(self.source) as doc:
            doc.save(protected,encryption=fitz.PDF_ENCRYPT_AES_256,user_pw=password,owner_pw='owner-audit',permissions=fitz.PDF_PERM_ACCESSIBILITY|fitz.PDF_PERM_PRINT)
        report=self.inspect(protected,{'password':password})
        output=self.apply(report,[dict(id=self.text_object(report)['id'],action='replace',text='Edited content')],protected,{'password':password})
        with fitz.open(output) as doc,fitz.open(protected) as before:
            self.assertTrue(doc.needs_pass);self.assertFalse(doc.authenticate('wrong'))
            self.assertTrue(doc.authenticate(password));before.authenticate(password)
            self.assertEqual(doc.permissions,before.permissions);self.assertIn('Edited content',doc[0].get_text())

    def test_rotated_page_crop_geometry_and_duplicate_page_independence(self):
        source=self.root/'cropped.pdf'
        with fitz.open(self.source) as doc:
            doc[0].set_cropbox(fitz.Rect(20,20,380,480));doc[0].set_rotation(90)
            doc.select([0,0]);doc.save(source)
        report=self.inspect(source)
        self.assertEqual(report['pages'][0]['width'],360);self.assertEqual(report['pages'][0]['height'],460)
        self.assertEqual(report['pages'][0]['rotation'],90)
        obj=next(item for item in report['objects'] if item.get('text')=='Original content' and item['page']==1)
        output=self.apply(report,[dict(id=obj['id'],action='replace',text='Edited content')],source)
        with fitz.open(output) as doc:
            self.assertEqual(doc[0].rotation,90);self.assertIn('Edited content',doc[0].get_text())
            self.assertIn('Original content',doc[1].get_text());self.assertNotEqual(doc[0].xref,doc[1].xref)

    def test_rotated_glyph_runs_and_interactive_overlap_are_explicitly_uneditable(self):
        source=self.root/'unsupported.pdf'
        with fitz.open() as doc:
            page=doc.new_page();page.insert_text((100,180),'Rotated',rotate=90)
            page.insert_text((30,50),'Interactive');page.add_text_annot((35,40),'Note')
            doc.save(source)
        report=self.inspect(source)
        self.assertTrue(all(not item['editable'] for item in report['objects']))
        with self.assertRaises(ValueError): self.apply(report,[dict(id=report['objects'][0]['id'],action='delete')],source)

    def test_image_replacement_retains_original_stacking_order(self):
        source=self.root/'overlay.pdf';replacement=self.root/'blue.png'
        Image.new('RGB',(40,30),(10,30,240)).save(replacement)
        with fitz.open() as doc:
            page=doc.new_page(width=200,height=200);page.insert_image(fitz.Rect(20,20,180,140),stream=self.image)
            page.insert_text((35,75),'TEXT ABOVE',fontsize=18,color=(1,1,1));doc.save(source)
        report=self.inspect(source);image=next(obj for obj in report['objects'] if obj['kind']=='image')
        output=self.apply(report,[dict(id=image['id'],action='replace',image_path=str(replacement))],source)
        with fitz.open(output) as doc:
            self.assertIn('TEXT ABOVE',doc[0].get_text());pix=doc[0].get_pixmap()
            rendered=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            self.assertGreater(sum(1 for pixel in rendered.crop((35,55,165,80)).getdata() if min(pixel)>220),30)

    def test_shared_image_and_soft_mask_are_not_editable(self):
        source=self.root/'shared.pdf'
        with fitz.open() as doc:
            page=doc.new_page();xref=page.insert_image(fitz.Rect(20,20,60,50),stream=self.image)
            page.insert_image(fitz.Rect(80,20,120,50),xref=xref);doc.save(source)
        report=self.inspect(source)
        self.assertTrue(all('shared-image-object' in obj['limitations'] for obj in report['objects']))
        transparent=io.BytesIO();Image.new('RGBA',(20,20),(240,20,20,100)).save(transparent,format='PNG')
        masked=self.root/'masked.pdf'
        with fitz.open() as doc:
            doc.new_page().insert_image(fitz.Rect(20,20,50,50),stream=transparent.getvalue());doc.save(masked)
        report=self.inspect(masked)
        self.assertIn('image-mask',report['objects'][0]['limitations']);self.assertFalse(report['objects'][0]['editable'])

    def test_output_collision_and_symlink_are_preserved(self):
        report=self.inspect();output=self.root/'edited.pdf';output.write_bytes(b'concurrent owner')
        with self.assertRaises(ValueError): self.apply(report,[dict(id=self.text_object(report)['id'],action='delete')])
        self.assertEqual(output.read_bytes(),b'concurrent owner')
        output.unlink();output.symlink_to(self.source)
        with self.assertRaises(ValueError): self.apply(report,[dict(id=self.text_object(report)['id'],action='delete')])
        self.assertTrue(output.is_symlink())

    def test_embedded_font_is_reused_without_substitution(self):
        source=self.root/'embedded.pdf';font=fitz.Font('cjk')
        with fitz.open() as doc:
            page=doc.new_page();page.insert_font(fontname='embedded',fontbuffer=font.buffer)
            page.insert_text((30,60),'Original content',fontname='embedded',fontsize=14);doc.save(source)
        report=self.inspect(source);entry=self.text_object(report)
        self.assertEqual(entry['font_status'],'original')
        output=self.apply(report,[dict(id=entry['id'],action='replace',text='Edited content')],source)
        with fitz.open(output) as doc:
            span=doc[0].get_text('dict')['blocks'][0]['lines'][0]['spans'][0]
            self.assertEqual(span['font'],entry['font']);self.assertEqual(span['text'],'Edited content')

    def test_pending_redactions_refuse_without_applying_other_marks(self):
        source=self.root/'pending.pdf'
        with fitz.open(self.source) as doc:
            doc[0].add_redact_annot(fitz.Rect(25,90,250,130));doc.save(source)
        report=self.inspect(source)
        with self.assertRaisesRegex(ValueError,'pending-redaction'):
            self.apply(report,[dict(id=self.text_object(report)['id'],action='delete')],source)
        self.assertFalse((self.root/'edited.pdf').exists())

    def test_malformed_review_json_and_source_binding_fail_before_recognition(self):
        review=self.root/'bad-review.json';review.write_text('{private document fragment')
        with patch('pdf_engine._external') as external,self.assertRaisesRegex(ValueError,'JSON válido') as failure:
            run('ocr-apply',[self.source],self.root/'rejected.pdf',{'review_path':str(review),'source_sha256':hashlib.sha256(self.original).hexdigest()})
        self.assertNotIn('private document fragment',str(failure.exception));external.assert_not_called()
        self.assertFalse((self.root/'rejected.pdf').exists())

    def test_ocr_process_errors_do_not_disclose_document_fragments(self):
        with patch('pdf_engine._external',side_effect=RuntimeError('PRIVATE_WORD /private/source.pdf')),self.assertRaises(RuntimeError) as failure:
            run('ocr-review',[self.source],self.root/'rejected.json',{'language':'eng'})
        self.assertNotIn('PRIVATE_WORD',str(failure.exception));self.assertNotIn('/private',str(failure.exception))
        self.assertFalse((self.root/'rejected.json').exists())

