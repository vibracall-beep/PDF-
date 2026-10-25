"""Real primitive editing, independent drawings and pixels outside edit areas."""
import io
import json
from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image,ImageChops,ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
from pdf_vector_content import signature


class VectorEditingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'source.pdf'
        image=io.BytesIO();Image.new('RGB',(20,20),(10,50,230)).save(image,format='PNG')
        with fitz.open() as doc:
            page=doc.new_page(width=500,height=600)
            page.draw_rect(fitz.Rect(30,50,140,100),color=(1,0,0),fill=(0,1,0),width=2)
            page.draw_line((170,200),(40,200),color=(0,0,1),width=3,dashes='[3 2] 1',lineCap=1)
            page.draw_line((220,220),(220,150),color=(0.5,0,0.5),width=2)
            page.insert_text((30,300),'Original text remains',fontsize=12)
            page.insert_image(fitz.Rect(330,330,400,400),stream=image.getvalue())
            page.add_text_annot((420,100),'Annotation remains')
            page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(300,450,450,480),'uri':'https://example.org'})
            widget=fitz.Widget();widget.field_name='preserved-field';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
            widget.rect=fitz.Rect(300,510,450,540);widget.field_value='Original field value';page.add_widget(widget)
            doc.new_page(width=500,height=600).insert_text((30,80),'Second page unchanged')
            doc.set_metadata({'title':'Vector proof'});doc.save(self.source)
        self.original=self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original);self.assertFalse(list(self.root.glob('.pdf-output-*')))
        self.temp.cleanup()

    def inspect(self,source=None,options=None):
        target=self.root/f'inspection-{len(list(self.root.glob("inspection-*")))}.json'
        run('content-inspect',[source or self.source],target,options or {})
        report=json.loads(target.read_text());return report,[item for item in report['objects'] if item['kind']=='vector']

    def apply(self,report,edits,source=None,options=None,name='edited.pdf'):
        target=self.root/name
        run('content-apply',[source or self.source],target,dict(source_sha256=report['source_sha256'],edits=edits,**(options or {})))
        return target

    def assert_pixels_except(self,before,after,areas):
        def image(page):
            pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            return Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        a=image(before);b=image(after)
        try:
            difference=ImageChops.difference(a,b);mask=ImageDraw.Draw(difference)
            for area in areas: mask.rectangle(tuple((fitz.Rect(area)+(-1,-1,1,1))*fitz.Matrix(2,2)),fill=(0,0,0))
            self.assertIsNone(difference.getbbox());difference.close()
        finally: a.close();b.close()

    def test_inspection_is_source_bound_and_reports_primitive_geometry(self):
        report,vectors=self.inspect();again,_=self.inspect()
        self.assertEqual(report,again);self.assertEqual([item['vector_shape'] for item in vectors],['rectangle','line','line'])
        self.assertTrue(all(item['editable'] for item in vectors));self.assertEqual(vectors[0]['rect'],[29,49,141,101])
        self.assertEqual(vectors[0]['color'],'#ff0000');self.assertEqual(vectors[0]['fill_color'],'#00ff00')

    def test_move_rectangle_preserves_style_independent_objects_and_external_pixels(self):
        report,vectors=self.inspect();item=vectors[0];destination=[270,50,382,102]
        output=self.apply(report,[dict(id=item['id'],action='move',rect=destination)])
        with fitz.open(self.source) as before,fitz.open(output) as after:
            moved=next(drawing for drawing in after[0].get_drawings() if drawing['type']=='fs')
            self.assertEqual(tuple(moved['rect']),(271,51,381,101));self.assertEqual(moved['color'],(1,0,0));self.assertEqual(moved['fill'],(0,1,0))
            self.assertEqual(Counter(signature(d) for d in before[0].get_drawings()[1:]),
                             Counter(signature(d) for d in after[0].get_drawings() if signature(d)!=signature(moved)))
            self.assertEqual(after[0].get_text(),before[0].get_text());self.assertEqual(after.metadata['title'],'Vector proof')
            self.assertEqual(next(after[0].annots()).info['content'],'Annotation remains')
            self.assertEqual(after[0].get_links()[0]['uri'],'https://example.org')
            self.assertEqual(next(after[0].widgets()).field_value,'Original field value')
            self.assertEqual(after[1].get_pixmap().samples,before[1].get_pixmap().samples)
            self.assert_pixels_except(before[0],after[0],[item['rect'],destination])

    def test_delete_removes_only_selected_vector(self):
        report,vectors=self.inspect();output=self.apply(report,[dict(id=vectors[0]['id'],action='delete')])
        with fitz.open(self.source) as before,fitz.open(output) as after:
            self.assertEqual([signature(d) for d in after[0].get_drawings()],[signature(d) for d in before[0].get_drawings()[1:]])
            self.assertEqual(after[0].get_text(),before[0].get_text());self.assert_pixels_except(before[0],after[0],[vectors[0]['rect']])

    def test_replace_style_and_resize_changes_only_requested_primitive(self):
        report,vectors=self.inspect();output=self.apply(report,[dict(id=vectors[0]['id'],action='replace',
            rect=[30,50,180,130],stroke_color='#0000ff',fill_color=None,stroke_width=4)])
        with fitz.open(output) as doc:
            shape=next(drawing for drawing in doc[0].get_drawings() if tuple(drawing['rect'])==(32,52,178,128))
            self.assertEqual(shape['type'],'s');self.assertEqual(shape['color'],(0,0,1));self.assertEqual(shape['width'],4)
            self.assertIsNone(shape['fill']);self.assertEqual(tuple(shape['rect']),(32,52,178,128))

    def test_horizontal_and_vertical_lines_keep_direction_caps_and_dashes(self):
        report,vectors=self.inspect()
        for offset,destination in ((1,[30,350,180,353]),(2,[270,150,272,260])):
            output=self.apply(report,[dict(id=vectors[offset]['id'],action='move',rect=destination)],name=f'line-{offset}.pdf')
            with fitz.open(self.source) as original,fitz.open(output) as doc:
                before=original[0].get_drawings()[offset]
                after=next(drawing for drawing in doc[0].get_drawings() if drawing['items'][0][0]=='l' and
                    fitz.Rect(destination).contains(drawing['rect']))
                for key in ('type','color','width','dashes','lineCap','lineJoin'): self.assertEqual(after[key],before[key])
                a,b=after['items'][0][1:]
                if offset==1: self.assertGreater(a.x,b.x);self.assertEqual(a.y,b.y)
                else: self.assertGreater(a.y,b.y);self.assertEqual(a.x,b.x)

    def test_targets_reject_other_paths_text_images_annotations_and_links(self):
        report,vectors=self.inspect()
        for rect in ([30,190,180,210],[30,280,190,310],[320,320,410,410],[410,90,470,140],[300,440,450,490],[290,500,460,550]):
            with self.subTest(rect=rect),self.assertRaisesRegex(ValueError,'destino'):
                self.apply(report,[dict(id=vectors[0]['id'],action='move',rect=rect)])
            self.assertFalse((self.root/'edited.pdf').exists())

    def test_planned_vector_destinations_cannot_intersect(self):
        report,vectors=self.inspect()
        edits=[dict(id=vectors[0]['id'],action='move',rect=[30,350,170,400]),dict(id=vectors[1]['id'],action='move',rect=[40,360,180,363])]
        for order in (edits,list(reversed(edits))):
            with self.assertRaisesRegex(ValueError,'destino'): self.apply(report,order)
            self.assertFalse((self.root/'edited.pdf').exists())

    def test_multiple_independent_content_edits_preserve_remaining_vectors(self):
        report,vectors=self.inspect();text=next(item for item in report['objects'] if item['kind']=='text' and item['page']==1)
        output=self.apply(report,[dict(id=text['id'],action='replace',text='Edited text.'),
            dict(id=vectors[0]['id'],action='move',rect=[270,50,382,102]),dict(id=vectors[1]['id'],action='delete')])
        with fitz.open(output) as doc:
            self.assertIn('Edited text.',doc[0].get_text())
            with fitz.open(self.source) as before: self.assertEqual(len(doc[0].get_drawings()),len(before[0].get_drawings())-1)

    def test_unsupported_overlap_clipping_opacity_layer_and_pending_redaction_are_readonly(self):
        for mode in ('overlap','clipped','opacity','layer','redaction'):
            source=self.root/f'{mode}.pdf'
            with fitz.open() as doc:
                page=doc.new_page(width=400,height=500)
                layer=doc.add_ocg('Optional vector') if mode=='layer' else 0
                page.draw_rect(fitz.Rect(40,60,160,130),color=(1,0,0),fill=(0,1,0),width=2,fill_opacity=0.5 if mode=='opacity' else 1,oc=layer)
                if mode=='overlap': page.insert_text((50,90),'Overlapping text')
                if mode=='clipped':
                    for xref in page.get_contents(): doc.update_stream(xref,b'q\n40 390 30 80 re W n\n'+doc.xref_stream(xref)+b'\nQ')
                if mode=='redaction': page.add_redact_annot(fitz.Rect(300,300,350,350))
                doc.save(source)
            report,vectors=self.inspect(source);self.assertTrue(vectors);self.assertTrue(all(not item['editable'] for item in vectors),mode)
            with self.assertRaises(ValueError): self.apply(report,[dict(id=vectors[0]['id'],action='delete')],source)
            self.assertFalse((self.root/'edited.pdf').exists())

    def test_curves_and_diagonals_are_not_misrepresented_as_editable_primitives(self):
        source=self.root/'complex.pdf'
        with fitz.open() as doc:
            page=doc.new_page();page.draw_bezier((40,40),(80,20),(100,100),(140,40));page.draw_line((40,180),(120,220));doc.save(source)
        _,vectors=self.inspect(source);self.assertEqual(vectors,[])

    def test_text_destinations_respect_painted_stroke_extent_not_only_path_center(self):
        source=self.root/'wide-stroke.pdf'
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500);page.insert_text((30,50),'Original text',fontsize=12)
            page.draw_line((30,250),(220,250),color=(0,0,1),width=40);doc.save(source)
        report,_=self.inspect(source);text=next(item for item in report['objects'] if item['kind']=='text')
        with self.assertRaisesRegex(ValueError,'destino'):
            self.apply(report,[dict(id=text['id'],action='move',rect=[30,220,200,245])],source)
        self.assertFalse((self.root/'edited.pdf').exists())

    def test_corrupt_removal_of_another_drawing_refuses_without_publishing(self):
        report,vectors=self.inspect();original=fitz.Page.apply_redactions
        def corrupt(page,*args,**kwargs):
            result=original(page,*args,**kwargs);page.draw_line((20,550),(100,550),color=(1,0,1));return result
        with patch.object(fitz.Page,'apply_redactions',corrupt),self.assertRaisesRegex(ValueError,'demais desenhos'):
            self.apply(report,[dict(id=vectors[0]['id'],action='delete')])
        self.assertFalse((self.root/'edited.pdf').exists())

    def test_invalid_invisible_or_impossible_stroke_is_refused(self):
        report,vectors=self.inspect()
        for change in (dict(stroke_color=None,fill_color=None),dict(stroke_width=float('nan')),dict(stroke_width=100.1),
                       dict(stroke_width=30,rect=[40,60,60,80]),dict(stroke_color='not-a-color')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.apply(report,[dict(id=vectors[0]['id'],action='replace',**change)])
            self.assertFalse((self.root/'edited.pdf').exists())
        with self.assertRaisesRegex(ValueError,'linha'): self.apply(report,[dict(id=vectors[1]['id'],action='replace',fill_color='#ffffff')])

    def test_encrypted_cropped_rotated_duplicate_pages_keep_source_and_permissions(self):
        source=self.root/'protected.pdf';password='vector-reader'
        with fitz.open(self.source) as doc:
            # A raw duplicated page with a widget and no duplicated field tree
            # is deliberately refused by the shared serializer (separate test).
            page=doc[0]
            for widget in list(page.widgets()): page.delete_widget(widget)
            doc[0].set_cropbox(fitz.Rect(10,10,490,590));doc[0].set_rotation(90);doc.select([0,0])
            doc.save(source,encryption=fitz.PDF_ENCRYPT_AES_256,user_pw=password,owner_pw='vector-owner',permissions=fitz.PDF_PERM_PRINT|fitz.PDF_PERM_ACCESSIBILITY)
        report,vectors=self.inspect(source,{'password':password});item=next(item for item in vectors if item['page']==1 and item['vector_shape']=='rectangle')
        output=self.apply(report,[dict(id=item['id'],action='delete')],source,{'password':password})
        with fitz.open(source) as before,fitz.open(output) as after:
            self.assertTrue(after.needs_pass);self.assertFalse(after.authenticate('incorrect'));before.authenticate(password);after.authenticate(password)
            self.assertEqual(after.permissions,before.permissions);self.assertEqual(after[0].cropbox,before[0].cropbox);self.assertEqual(after[0].rotation,90)
            self.assertEqual(len(after[0].get_drawings()),len(before[0].get_drawings())-1)
            self.assertEqual(Counter(signature(d) for d in after[1].get_drawings()),Counter(signature(d) for d in before[1].get_drawings()))
            self.assertEqual(after[1].get_pixmap().samples,before[1].get_pixmap().samples)

    def test_duplicate_page_with_noncopyable_field_tree_remains_safely_refused(self):
        source=self.root/'duplicate-fields.pdf'
        with fitz.open(self.source) as doc: doc.select([0,0]);doc.save(source)
        report,vectors=self.inspect(source);item=next(item for item in vectors if item['page']==1)
        with self.assertRaisesRegex(ValueError,'árvore de formulário'):
            self.apply(report,[dict(id=item['id'],action='delete')],source)
        self.assertFalse((self.root/'edited.pdf').exists())

    def test_protected_cropped_rotated_page_retains_real_form_value(self):
        source=self.root/'protected-fields.pdf';password='protected-field-reader'
        with fitz.open(self.source) as doc:
            doc[0].set_cropbox(fitz.Rect(10,10,490,590));doc[0].set_rotation(90)
            doc.save(source,encryption=fitz.PDF_ENCRYPT_AES_256,user_pw=password,owner_pw='protected-field-owner',permissions=fitz.PDF_PERM_PRINT|fitz.PDF_PERM_ACCESSIBILITY)
        report,vectors=self.inspect(source,{'password':password});item=next(item for item in vectors if item['page']==1)
        output=self.apply(report,[dict(id=item['id'],action='delete')],source,{'password':password})
        with fitz.open(source) as before,fitz.open(output) as after:
            before.authenticate(password);self.assertTrue(after.authenticate(password))
            self.assertEqual(after.permissions,before.permissions)
            self.assertEqual(next(after[0].widgets()).field_value,'Original field value')
            self.assertEqual(after[1].get_pixmap().samples,before[1].get_pixmap().samples)
