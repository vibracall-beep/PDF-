"""Independent privacy review: real PDF objects, streams and hidden channels."""
import hashlib, io, json, struct, sys, tempfile, unittest
from pathlib import Path
import fitz
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run

SECRET='SENSITIVE-REDACTION-68291'
VISIBLE='PUBLIC-CONTENT-43827'

def ref(doc,raw,stream=None):
    xref=doc.get_new_xref();doc.update_object(xref,raw)
    if stream is not None:doc.update_stream(xref,stream)
    return xref

def text(value):return fitz.get_pdf_str(value)

def searchable_bytes(doc):
    chunks=[]
    for xref in range(1,doc.xref_length()):
        chunks.append(doc.xref_object(xref,compressed=False).encode())
        if doc.xref_is_stream(xref):
            chunks.append(doc.xref_stream(xref));chunks.append(doc.xref_stream_raw(xref))
    # Inline images can remain encoded inside page streams. Extraction yields
    # their actual JPEG container, including EXIF hidden by ASCIIHex wrapping.
    for page in doc:
        for block in page.get_text('dict')['blocks']:
            if block['type']==1:chunks.append(block['image'])
    return b'\n'.join(chunks)

class IndependentRedactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='PDF independent redact ')
        self.root=Path(self.temporary.name);self.source=self.root/'source.pdf';self.target=self.root/'redacted.pdf'
    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual(list(self.root.glob('.pdf-output-*')),[])
        self.temporary.cleanup()
    def fixture(self,channel,protected=False):
        if self.source.exists():
            self.assertEqual(self.source.read_bytes(),self.original)
            self.source.unlink()
        self.target.unlink(missing_ok=True)
        with fitz.open() as doc:
            page=doc.new_page();page.insert_text((40,50),SECRET);page.insert_text((40,180),VISIBLE)
            second=doc.new_page();second.insert_text((40,80),'OTHER-PAGE-PUBLIC-7192');page=doc[0]
            if channel=='structure':
                root=ref(doc,'<< /Type /StructTreeRoot >>')
                node=ref(doc,f'<< /Type /StructElem /S /P /P {root} 0 R /Pg {page.xref} 0 R /K 0 /ActualText {text(SECRET)} /Alt {text(SECRET)} /E {text(SECRET)} >>')
                tree=ref(doc,f'<< /Nums [0 [{node} 0 R]] >>')
                doc.xref_set_key(root,'K',f'[{node} 0 R]');doc.xref_set_key(root,'ParentTree',f'{tree} 0 R')
                doc.xref_set_key(doc.pdf_catalog(),'StructTreeRoot',f'{root} 0 R')
                doc.xref_set_key(doc.pdf_catalog(),'MarkInfo','<< /Marked true >>')
                doc.xref_set_key(page.xref,'StructParents','0')
                contents=page.get_contents()[0]
                doc.update_stream(contents,b'/P << /MCID 0 >> BDC\n'+doc.xref_stream(contents)+b'\nEMC')
            elif channel=='inline-actual':
                contents=page.get_contents()[0]
                doc.update_stream(contents,(f'/Span << /ActualText {text(SECRET)} /Alt {text(SECRET)} /E {text(SECRET)} >> BDC\n').encode()+doc.xref_stream(contents)+b'\nEMC')
            elif channel=='named-actual':
                prop=ref(doc,f'<< /ActualText {text(SECRET)} /Alt {text(SECRET)} /E {text(SECRET)} >>')
                resource_kind,resource_value=doc.xref_get_key(page.xref,'Resources')
                if resource_kind=='xref':doc.xref_set_key(int(resource_value.split()[0]),'Properties',f'<< /TextOverride {prop} 0 R >>')
                else:doc.xref_set_key(page.xref,'Resources/Properties',f'<< /TextOverride {prop} 0 R >>')
                contents=page.get_contents()[0]
                doc.update_stream(contents,b'/Span /TextOverride BDC\n'+doc.xref_stream(contents)+b'\nEMC')
            elif channel=='af':
                embedded=ref(doc,'<< /Type /EmbeddedFile /Subtype /text#2Fplain >>',SECRET.encode())
                spec=ref(doc,f'<< /Type /Filespec /F (private.txt) /UF (private.txt) /Desc {text(SECRET)} /AFRelationship /Data /EF << /F {embedded} 0 R >> >>')
                doc.xref_set_key(doc.pdf_catalog(),'AF',f'[{spec} 0 R]');doc.xref_set_key(page.xref,'AF',f'[{spec} 0 R]')
                self.assertEqual(doc.embfile_names(),[])
            elif channel=='annotations-forms':
                note=page.add_text_annot((400,650),SECRET);note.set_info(title=SECRET,subject=SECRET);note.update()
                doc.xref_set_key(note.xref,'RC',text('<body><p>'+SECRET+'</p></body>'))
                page.add_file_annot((450,700),SECRET.encode(),'embedded.txt',desc=SECRET)
                widget=fitz.Widget();widget.field_name=SECRET;widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
                widget.field_value='VISIBLE-FORM-VALUE';widget.field_label=SECRET;widget.rect=fitz.Rect(40,250,260,280)
                added=page.add_widget(widget)
                doc.xref_set_key(added.xref,'DV',text(SECRET))
                doc.xref_set_key(added.xref,'TM',text(SECRET))
            elif channel.startswith('hidden-interactivity-'):
                flag=int(channel.rsplit('-',1)[1])
                widget=fitz.Widget();widget.field_name='hidden-field';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
                widget.field_value=SECRET;widget.rect=fitz.Rect(350,450,590,480)
                added=page.add_widget(widget);doc.xref_set_key(added.xref,'F',str(flag))
                note=page.add_freetext_annot(fitz.Rect(350,510,590,540),SECRET,fontsize=12)
                note.set_flags(flag);note.update()
            elif channel in ('masked-password','alternate-appearance'):
                font=page.get_fonts()[0][0]
                widget=fitz.Widget();widget.field_name='private-field';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
                widget.field_value=SECRET if channel=='masked-password' else 'PUBLIC-FIELD'
                widget.rect=fitz.Rect(40,450,400,480)
                if channel=='masked-password':widget.field_flags=fitz.PDF_TX_FIELD_IS_PASSWORD
                added=page.add_widget(widget)
                appearance_text='********************' if channel=='masked-password' else SECRET
                appearance=ref(doc,f'<< /Type /XObject /Subtype /Form /BBox [0 0 360 30] /Resources << /Font << /F1 {font} 0 R >> >> >>',
                               (f'BT /F1 12 Tf 1 0 0 1 0 12 Tm {text(appearance_text)} Tj ET').encode())
                for state in (('N',) if channel=='masked-password' else ('R','D')):
                    doc.xref_set_key(added.xref,'AP/'+state,f'{appearance} 0 R')
            elif channel=='metadata':
                doc.set_metadata({'title':SECRET,'subject':SECRET,'keywords':SECRET,'author':SECRET})
                doc.set_xml_metadata('<x:xmpmeta xmlns:x="adobe:ns:meta/">'+SECRET+'</x:xmpmeta>')
                metadata=ref(doc,'<< /Type /Metadata /Subtype /XML >>',SECRET.encode())
                doc.xref_set_key(page.xref,'Metadata',f'{metadata} 0 R')
                doc.xref_set_key(page.xref,'PieceInfo',f'<< /PrivateApplication << /Private {text(SECRET)} >> >>')
                doc.xref_set_key(doc.pdf_catalog(),'PieceInfo',f'<< /PrivateApplication << /Private {text(SECRET)} >> >>')
                doc.xref_set_key(page.xref,'LastModified',text(SECRET))
                doc.set_toc([[1,SECRET,1]])
            elif channel.startswith('resource-'):
                name={'resource-escaped':b'/Public#2F#23Name','resource-utf8':b'/F#C3#A9','resource-nonutf8':b'/F#E9'}[channel]
                resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
                doc.update_object(resources,doc.xref_object(resources).replace('/helv',name.decode('ascii')))
                for xref in page.get_contents():doc.update_stream(xref,doc.xref_stream(xref).replace(b'/helv',name))
            elif channel=='binary-glyphs':
                raw=b'q BT /helv 11 Tf 1 0 0 1 40 400 Tm <feff00410042004300> Tj ET Q'
                extra=ref(doc,'<< >>',raw)
                doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{x} 0 R' for x in page.get_contents()+[extra])+']')
            elif channel in ('jpeg-exif','inline-jpeg-exif','inline-jpeg-exif-progressive','inline-jpeg-exif-cmyk'):
                cmyk=channel.endswith('-cmyk')
                image=Image.new('CMYK' if cmyk else 'RGB',(64,64),(10,40,80,20) if cmyk else (90,100,120));exif=Image.Exif();exif[270]=SECRET
                encoded=io.BytesIO();image.save(encoded,format='JPEG',exif=exif,progressive=channel.endswith('-progressive'))
                if channel=='jpeg-exif':page.insert_image(fitz.Rect(350,500,450,600),stream=encoded.getvalue())
                else:
                    colorspace=b'/CMYK' if cmyk else b'/RGB'
                    extra=ref(doc,'<< >>',b'q 100 0 0 100 350 242 cm BI /W 64 /H 64 /CS '+colorspace+b' /BPC 8 /F /DCT ID '+encoded.getvalue()+b' EI Q')
                    doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{item} 0 R' for item in page.get_contents()+[extra])+']')
            elif channel=='jpeg2000-xml':
                image=Image.new('RGB',(32,32),(80,90,100));encoded=io.BytesIO()
                image.save(encoded,format='JPEG2000')
                metadata=('<metadata>'+SECRET+'</metadata>').encode()
                raw=encoded.getvalue()+struct.pack('>I',len(metadata)+8)+b'xml '+metadata
                image_xref=page.insert_image(fitz.Rect(350,500,450,600),stream=raw)
                self.assertEqual(doc.xref_get_key(image_xref,'Filter'),('name','/JPXDecode'))
                self.assertIn(SECRET.encode(),doc.xref_stream_raw(image_xref))
            elif channel=='signature-appearance':
                # A signature field with a genuine Form appearance and synthetic
                # CMS payload: this checks removal, not certificate validity.
                widget=fitz.Widget();widget.field_name='signature';widget.field_type=fitz.PDF_WIDGET_TYPE_SIGNATURE
                widget.rect=fitz.Rect(35,25,315,75);added=page.add_widget(widget)
                resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
                font=doc.xref_get_key(resources,'Font/helv')[1]
                appearance=ref(doc,f'<< /Type /XObject /Subtype /Form /BBox [0 0 280 50] /Resources << /Font << /F1 {font} >> >> >>',
                    (f'BT /F1 12 Tf 1 0 0 1 0 20 Tm {text(SECRET)} Tj ET').encode())
                value=ref(doc,f'<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached /Contents <{SECRET.encode().hex()}> /Name {text(SECRET)} >>')
                doc.xref_set_key(added.xref,'AP',f'<< /N {appearance} 0 R >>');doc.xref_set_key(added.xref,'V',f'{value} 0 R')
            elif channel=='hidden-text':
                page.insert_text((350,450),SECRET,render_mode=3)
            elif channel in ('inherited-hidden-form','inherited-hidden-covered-form',
                              'inherited-hidden-offpage-form','inherited-hidden-clipped-form','inherited-hidden-crop-form'):
                # Form XObjects inherit the caller's graphics/text state. A
                # normalizer must not reset inherited Tr=3 and reveal text.
                font=page.get_fonts()[0][0]
                bounds='[0 0 1 1]' if channel=='inherited-hidden-clipped-form' else '[0 0 600 800]'
                form=ref(doc,f'<< /Type /XObject /Subtype /Form /BBox {bounds} /Resources << /Font << /F1 {font} 0 R >> >> >>',
                         (f'BT /F1 12 Tf 1 0 0 1 350 450 Tm {text(SECRET)} Tj ET').encode())
                resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
                doc.xref_set_key(resources,'XObject',f'<< /Hidden {form} 0 R >>')
                covering=b' q 1 g 300 400 290 100 re f Q' if channel=='inherited-hidden-covered-form' else b''
                transform=b'1 0 0 1 0 -2000 cm ' if channel=='inherited-hidden-offpage-form' else b''
                extra=ref(doc,'<< >>',b'q '+transform+b'3 Tr /Hidden Do Q'+covering)
                doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{item} 0 R' for item in page.get_contents()+[extra])+']')
                if channel=='inherited-hidden-crop-form':page.set_cropbox(fitz.Rect(0,0,595,300))
            elif channel=='transparent-text':
                page.insert_text((350,450),SECRET,fill_opacity=0)
            elif channel=='clip-text':
                page.insert_text((350,450),SECRET,render_mode=7)
            elif channel=='mixed-hidden-text':
                extra=ref(doc,'<< >>',(f'q BT /helv 11 Tf 1 0 0 1 350 450 Tm 3 Tr {text(SECRET)} Tj 0 Tr (KEEP-VISIBLE-POSTFIX) Tj ET Q').encode())
                doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{item} 0 R' for item in page.get_contents()+[extra])+']')
            elif channel=='optional-content':
                ocg=doc.add_ocg(SECRET,on=False);page.insert_text((350,450),SECRET,oc=ocg)
            elif channel=='xfa':
                widget=fitz.Widget();widget.field_name='field';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT;widget.rect=fitz.Rect(40,250,200,280);page.add_widget(widget)
                packet=ref(doc,'<< >>',('<xdp>'+SECRET+'</xdp>').encode())
                doc.xref_set_key(doc.pdf_catalog(),'AcroForm/XFA',f'[(template) {packet} 0 R]')
            else:raise ValueError(channel)
            kwargs=dict(encryption=fitz.PDF_ENCRYPT_AES_256,user_pw='review-pass',owner_pw='review-owner',permissions=fitz.PDF_PERM_PRINT|fitz.PDF_PERM_MODIFY|fitz.PDF_PERM_COPY|fitz.PDF_PERM_ANNOTATE) if protected else {}
            doc.save(self.source,**kwargs)
        self.original=self.source.read_bytes()
    def redact(self,protected=False):
        run('redact',[self.source],self.target,{'pages':'1','rects':[[20,20,340,100]],**({'password':'review-pass'} if protected else {})})
    def assert_clean(self,protected=False):
        with fitz.open(self.target) as doc:
            if protected:
                self.assertTrue(doc.needs_pass);self.assertFalse(doc.authenticate(''));self.assertTrue(doc.authenticate('review-pass'))
                with fitz.open(self.source) as original:
                    self.assertTrue(original.authenticate('review-pass'))
                    self.assertEqual(doc.permissions,original.permissions)
            self.assertNotIn(SECRET,'\n'.join(p.get_text() for p in doc))
            self.assertIn(VISIBLE,doc[0].get_text());self.assertIn('OTHER-PAGE-PUBLIC-7192',doc[1].get_text())
            self.assertFalse(SECRET.encode() in searchable_bytes(doc),'Sensitive fixture bytes survived in a PDF object or encoded/decoded stream.')
            self.assertEqual(doc.embfile_names(),[])
            self.assertFalse(list(doc[0].widgets() or []));self.assertFalse(list(doc[0].annots() or []))
            self.assertEqual(doc.xref_get_key(doc.pdf_catalog(),'StructTreeRoot')[0],'null')
            self.assertEqual(doc.xref_get_key(doc.pdf_catalog(),'AF')[0],'null')
    def test_structure_and_inline_named_actualtext_are_erased(self):
        for channel in ('structure','inline-actual','named-actual'):
            with self.subTest(channel=channel):
                self.fixture(channel);self.redact();self.assert_clean()
    def test_associated_files_without_embedded_names_tree_are_erased(self):
        self.fixture('af');self.redact();self.assert_clean()
    def test_annotation_richtext_field_defaults_and_file_attachments_are_erased(self):
        self.fixture('annotations-forms');self.redact();self.assert_clean()
        with fitz.open(self.target) as doc:self.assertIn('VISIBLE-FORM-VALUE',doc[0].get_text())
    def test_xmp_page_private_metadata_and_outline_labels_are_erased(self):
        self.fixture('metadata');self.redact();self.assert_clean()
    def test_hidden_text_cannot_survive_outside_the_visual_redaction_area(self):
        self.fixture('hidden-text');self.redact();self.assert_clean()
    def test_hidden_text_state_inherited_by_form_is_removed_or_refused(self):
        for channel in ('inherited-hidden-form','inherited-hidden-covered-form',
                        'inherited-hidden-offpage-form','inherited-hidden-clipped-form','inherited-hidden-crop-form'):
            with self.subTest(channel=channel):
                self.fixture(channel);before=self.pixels(self.source)
                with fitz.open(self.source) as original:
                    self.assertTrue(any(item['type']==3 for item in original[0].get_texttrace()))
                try:self.redact()
                except ValueError:self.assertFalse(self.target.exists())
                else:self.assert_clean();self.assert_pixels_preserved(before)
    def test_encrypted_original_and_result_keep_encryption(self):
        self.fixture('af',protected=True);self.redact(protected=True);self.assert_clean(protected=True)
    def pixels(self,path):
        with fitz.open(path) as doc:
            pix=doc[0].get_pixmap(alpha=False,annots=True)
            return pix.width,pix.height,pix.stride,pix.n,pix.samples
    def assert_pixels_preserved(self,before,ignore_attachment=False):
        after=self.pixels(self.target)
        self.assertEqual(before[:4],after[:4])
        width,height,stride,channels,a=before;b=after[4]
        for y in range(height):
            # Compare contiguous row fragments outside the selected rectangle
            # and the attachment icon deliberately removed with its payload.
            excluded=[]
            if 18<=y<=102:excluded.append((18,343))
            if ignore_attachment and 700<=y<=719:excluded.append((450,470))
            start=0
            for left,right in sorted(excluded)+[(width,width)]:
                self.assertTrue(a[y*stride+start*channels:y*stride+left*channels] ==
                                b[y*stride+start*channels:y*stride+left*channels],
                                 'Visible appearance changed outside the redaction on row '+str(y))
                start=right
    def test_remaining_form_and_annotation_appearance_is_preserved(self):
        self.fixture('annotations-forms');before=self.pixels(self.source)
        self.redact();self.assert_clean();self.assert_pixels_preserved(before,ignore_attachment=True)
    def test_hidden_invisible_and_noview_fields_annotations_cannot_be_exposed_by_flattening(self):
        for flag in (1,2,32):
            with self.subTest(flag=flag):
                self.fixture('hidden-interactivity-'+str(flag));before=self.pixels(self.source)
                with fitz.open(self.source) as original:
                    pixels=original[0].get_pixmap(clip=fitz.Rect(340,440,595,550),alpha=False,annots=True)
                    self.assertTrue(all(value==255 for value in pixels.samples))
                try:self.redact()
                except ValueError:self.assertFalse(self.target.exists())
                else:self.assert_clean();self.assert_pixels_preserved(before)
    def test_password_values_and_rollover_down_appearances_are_removed(self):
        for channel in ('masked-password','alternate-appearance'):
            with self.subTest(channel=channel):
                self.fixture(channel);before=self.pixels(self.source)
                with fitz.open(self.source) as original:
                    self.assertEqual(original[0].get_text().count(SECRET),1)
                self.redact();self.assert_clean();self.assert_pixels_preserved(before)
    def test_signature_appearance_inside_area_does_not_reappear_after_flattening(self):
        self.fixture('signature-appearance');self.redact();self.assert_clean()
    def test_escaped_and_nonutf8_resource_names_preserve_pixels_or_refuse(self):
        for channel in ('resource-escaped','resource-nonutf8'):
            with self.subTest(channel=channel):
                self.fixture(channel);before=self.pixels(self.source)
                try:self.redact()
                except ValueError:
                    self.assertFalse(self.target.exists())
                else:self.assert_clean();self.assert_pixels_preserved(before)
    def test_utf8_resource_names_and_binary_glyph_strings_roundtrip_visually(self):
        for channel in ('resource-utf8','binary-glyphs'):
            with self.subTest(channel=channel):
                self.fixture(channel);before=self.pixels(self.source)
                self.redact();self.assert_clean();self.assert_pixels_preserved(before)
    def test_jpeg_exif_metadata_is_erased_losslessly_or_refused_before_publication(self):
        for channel in ('jpeg-exif','inline-jpeg-exif','inline-jpeg-exif-progressive','inline-jpeg-exif-cmyk'):
            with self.subTest(channel=channel):
                self.fixture(channel);before=self.pixels(self.source)
                try:self.redact()
                except ValueError:self.assertFalse(self.target.exists())
                else:self.assert_clean();self.assert_pixels_preserved(before)
    def test_jpeg2000_xml_metadata_is_erased_losslessly_or_refused_before_publication(self):
        self.fixture('jpeg2000-xml');before=self.pixels(self.source)
        try:self.redact()
        except ValueError:self.assertFalse(self.target.exists())
        else:self.assert_clean();self.assert_pixels_preserved(before)
    def test_unsupported_zero_opacity_refuses_without_output(self):
        self.fixture('transparent-text')
        with self.assertRaises(ValueError):self.redact()
        self.assertFalse(self.target.exists())
    def test_unsupported_text_clipping_refuses_without_output(self):
        self.fixture('clip-text')
        with self.assertRaises(ValueError):self.redact()
        self.assertFalse(self.target.exists())
    def test_mixed_invisible_and_visible_text_refuses_instead_of_moving_visible_glyphs(self):
        self.fixture('mixed-hidden-text')
        with self.assertRaises(ValueError):self.redact()
        self.assertFalse(self.target.exists())
    def test_unsupported_optional_layers_refuse_without_output(self):
        self.fixture('optional-content')
        with self.assertRaises(ValueError):self.redact()
        self.assertFalse(self.target.exists())
    def test_unsupported_xfa_refuses_without_output(self):
        self.fixture('xfa')
        with self.assertRaises(ValueError):self.redact()
        self.assertFalse(self.target.exists())

if __name__=='__main__':unittest.main(verbosity=2)
