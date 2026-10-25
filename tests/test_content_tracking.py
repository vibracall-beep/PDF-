"""Real PDF tracking and transaction geometry, including adversarial batches."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import fitz
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run


class ContentTrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source.pdf'
        image=io.BytesIO();Image.new('RGB',(20,20),'red').save(image,format='PNG')
        with fitz.open() as doc:
            page=doc.new_page(width=500,height=600)
            page.insert_text((30,50),'Original alpha',fontsize=12)
            page.insert_text((30,90),'Original beta',fontsize=12)
            page.insert_text((30,130),'First line here.\nSecond line here.',fontsize=12)
            page.insert_image(fitz.Rect(300,300,350,350),stream=image.getvalue())
            page.draw_rect(fitz.Rect(30,400,180,450),color=(0,0,1))
            page.add_text_annot((400,400),'Annotation preserved')
            page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(300,470,450,490),'uri':'https://example.org'})
            doc.save(self.source)
        self.original=self.source.read_bytes()
        inspection=self.root/'inspection.json';run('content-inspect',[self.source],inspection)
        self.report=json.loads(inspection.read_text())
        self.alpha=next(item for item in self.report['objects'] if item.get('text')=='Original alpha')
        self.beta=next(item for item in self.report['objects'] if item.get('text')=='Original beta')
        self.image=next(item for item in self.report['objects'] if item['kind']=='image')

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertFalse(list(self.root.glob('.pdf-output-*')))
        self.temp.cleanup()

    def apply(self,edits,name='edited.pdf'):
        output=self.root/name
        run('content-apply',[self.source],output,dict(source_sha256=self.report['source_sha256'],edits=edits))
        return output

    def test_character_spacing_uses_actual_glyph_origins_and_alignment(self):
        for spacing in (0.75,-0.25):
            with self.subTest(spacing=spacing):
                output=self.apply([dict(id=self.alpha['id'],action='replace',text='ABCDEF',rect=[30,200,250,230],
                    character_spacing=spacing,alignment='right')],f'tracked-{spacing}.pdf')
                with fitz.open(output) as doc:
                    chars=[char for block in doc[0].get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT|fitz.TEXT_INHIBIT_SPACES)['blocks']
                        if block['type']==0 for line in block['lines'] for span in line['spans'] for char in span['chars'] if 199<char['bbox'][1]<230]
                    self.assertEqual(''.join(char['c'] for char in chars),'ABCDEF')
                    self.assertAlmostEqual(chars[-1]['bbox'][2],250,places=3)
                    font=fitz.Font('helv')
                    for first,second in zip(chars,chars[1:]):
                        self.assertAlmostEqual(second['origin'][0]-first['origin'][0],font.text_length(first['c'],fontsize=12)+spacing,places=3)
                    self.assertIn('Original beta',doc[0].get_text());self.assertNotIn('Original alpha',doc[0].get_text())
                    self.assertEqual(next(doc[0].annots()).info['content'],'Annotation preserved')

    def test_spaced_paragraph_wraps_without_lost_characters(self):
        paragraph=next(item for item in self.report['objects'] if item['kind']=='paragraph')
        text='Every word in this longer paragraph must survive automatic wrapping with extra spacing.'
        output=self.apply([dict(id=paragraph['id'],action='replace',text=text,rect=[30,190,230,320],character_spacing=0.5,line_spacing=1.7)])
        with fitz.open(output) as doc:
            raw=doc[0].get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT|fitz.TEXT_INHIBIT_SPACES)
            lines=[line for block in raw['blocks'] if block['type']==0 for line in block['lines'] if 189<line['bbox'][1]<320]
            recovered=''.join(char['c'] for line in lines for span in line['spans'] for char in span['chars'])
            self.assertEqual(recovered,text);self.assertGreater(len(lines),1)
            self.assertAlmostEqual(lines[1]['spans'][0]['origin'][1]-lines[0]['spans'][0]['origin'][1],20.4,places=3)

    def test_invalid_overflow_complex_and_nonprogressing_spacing_refused_atomically(self):
        cases=[dict(character_spacing=float('nan')),dict(character_spacing=20.01),dict(character_spacing=-5.01),
               dict(character_spacing=-5,text='iiiiii'),dict(character_spacing=20,text='ImpossibleSingleWord'*20),
               dict(character_spacing=1,text='cafe\u0301',allow_font_substitution=True),
               dict(character_spacing=1,text='a\tb'),dict(character_spacing=2,text='A\nB\nC\nD\nE')]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.apply([dict(id=self.alpha['id'],action='replace',rect=[30,200,250,230],**change)])
            self.assertFalse((self.root/'edited.pdf').exists())

    def test_two_text_destinations_and_text_image_destinations_cannot_overlap(self):
        pairs=[(self.alpha,self.beta),(self.alpha,self.image)]
        for first,second in pairs:
            edits=[dict(id=first['id'],action='move',rect=[30,200,200,240]),
                   dict(id=second['id'],action='move',rect=[50,210,220,250])]
            for ordered in (edits,list(reversed(edits))):
                with self.subTest(kinds=[item['kind'] for item in (first,second)]),self.assertRaisesRegex(ValueError,'destino'):
                    self.apply(ordered)
                self.assertFalse((self.root/'edited.pdf').exists())

    def test_moving_text_or_image_cannot_cover_graphics_annotations_or_links(self):
        for item in (self.alpha,self.image):
            for rect in ([300,300,350,350],[30,400,180,450],[395,390,480,440],[300,470,450,500]):
                if item['kind']=='image' and rect==self.image['rect']: continue
                with self.subTest(kind=item['kind'],rect=rect),self.assertRaises(ValueError):
                    self.apply([dict(id=item['id'],action='move',rect=rect)])
                self.assertFalse((self.root/'edited.pdf').exists())

    def test_nonintersecting_batch_remains_functional(self):
        output=self.apply([dict(id=self.alpha['id'],action='move',rect=[30,200,200,230]),
                           dict(id=self.beta['id'],action='move',rect=[250,200,450,230])])
        with fitz.open(output) as doc:
            for text in ('Original alpha','Original beta'):
                areas=doc[0].search_for(text);self.assertEqual(len(areas),1);self.assertGreater(areas[0].y0,199)
