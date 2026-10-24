"""Raster topology evidence: no OCR mocks and no inferred missing-border merges."""
import math
from pathlib import Path
import sys
import unittest

import fitz
from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from scan_analysis import _segments, _components, _aligned_tables, elements
from scan_geometry import rectangular_grid, original_geometry, deskew, _edge


class ScanTableGeometryTests(unittest.TestCase):
    def raster(self,damage=None):
        image=Image.new('L',(600,400),255);draw=ImageDraw.Draw(image)
        for x in (50,400,550): draw.line((x,80,x,320),fill=0,width=3)
        draw.line((220,160,220,320),fill=0,width=3)
        for y in (80,160,320): draw.line((50,y,550,y),fill=0,width=3)
        draw.line((220,240,550,240),fill=0,width=3)
        if damage=='partial': draw.rectangle((290,156,330,164),fill=255)
        if damage=='lshape':
            draw.rectangle((396,82,404,158),fill=255)
            draw.rectangle((52,156,218,164),fill=255)
        return image

    def grids(self,image):
        h=_segments(image,2);v=_segments(image,2,vertical=True)
        return [grid for hs,vs in _components(h,v,3) if (grid:=rectangular_grid(hs,vs,3)) is not None]

    def test_actual_raster_partial_grid_has_exact_rectangular_merges(self):
        with self.raster() as image: grids=self.grids(image)
        self.assertEqual(len(grids),1);grid=grids[0]
        self.assertEqual((grid['rows'],grid['columns']),(3,3))
        merges={(cell['row'],cell['column'],cell['row_span'],cell['column_span']) for cell in grid['cells'] if cell['row_span']>1 or cell['column_span']>1}
        self.assertEqual(merges,{(0,0,1,2),(1,0,2,1)})
        tiles=[(r,c) for cell in grid['cells'] for r in range(cell['row'],cell['row']+cell['row_span']) for c in range(cell['column'],cell['column']+cell['column_span'])]
        self.assertEqual(len(tiles),9);self.assertEqual(len(set(tiles)),9)

    def test_broken_rule_is_not_reinterpreted_as_a_merge(self):
        with self.raster('partial') as image: self.assertEqual(self.grids(image),[])

    def test_short_remaining_border_fragment_is_ambiguous_even_on_a_wide_cell(self):
        self.assertIsNone(_edge([dict(start=0,end=30)],0,1000,3))
        self.assertFalse(_edge([],0,1000,3))

    def test_l_shaped_region_is_not_flattened_into_a_rectangle(self):
        with self.raster('lshape') as image: self.assertEqual(self.grids(image),[])

    def test_inverse_geometry_retains_all_rotated_corners(self):
        angle=-4.2;scale=2
        metadata=dict(rotation_degrees=angle,original_size=[1000,1200],processed_size=[1086,1270])
        original=fitz.Rect(100,150,180,190);radians=math.radians(angle)
        transformed=[]
        for point in (original.tl,original.tr,original.br,original.bl):
            x,y=point.x*scale-500,point.y*scale-600
            transformed.append(fitz.Point(math.cos(radians)*x+math.sin(radians)*y+543,-math.sin(radians)*x+math.cos(radians)*y+635))
        bbox=fitz.Rect(min(p.x for p in transformed),min(p.y for p in transformed),max(p.x for p in transformed),max(p.y for p in transformed))
        result,quad=original_geometry(bbox,metadata,scale,fitz.Rect(0,0,500,600))
        self.assertTrue((fitz.Rect(result)+(-.01,-.01,.01,.01)).contains(original));self.assertEqual(len(quad),4)
        self.assertGreater(abs(quad[0][1]-quad[1][1]),1)

    def test_inverse_outside_geometry_refuses_instead_of_clamping(self):
        with self.assertRaises(ValueError): original_geometry([-100,-100,50,50],dict(rotation_degrees=0,original_size=[1000,1000],processed_size=[1000,1000]),2,fitz.Rect(0,0,500,500))

    def test_deskew_requires_small_nonzero_rotation_and_preserves_input_pixels(self):
        with self.raster() as source:
            original=source.tobytes()
            for angle,expected in ((0,False),(3.5,True),(10,False)):
                with source.rotate(angle,Image.Resampling.BICUBIC,expand=True,fillcolor=255) as tilted:
                    before=tilted.tobytes();result,metadata=deskew(tilted,2,_segments,_components)
                    self.assertEqual(metadata['applied'],expected);self.assertLessEqual(abs(metadata['rotation_degrees']),7)
                    self.assertEqual(tilted.tobytes(),before)
                    if expected: self.assertAlmostEqual(metadata['rotation_degrees'],-angle,delta=.3)
                    if result is not tilted: result.close()
            self.assertEqual(source.tobytes(),original)

    def words(self,rows):
        return [dict(text=value,rect=[40+column*150,40+row*40,40+column*150+len(value)*8,56+row*40],confidence=.9)
            for row,values in enumerate(rows) for column,value in enumerate(values)]

    def test_borderless_requires_numeric_alignment_and_keeps_exact_indices(self):
        words=self.words([['Product','Units','Price'],['Apple','12','1.20'],['Pear','5','3.00']])
        tables=_aligned_tables(words,set());self.assertEqual(len(tables),1)
        self.assertEqual(tables[0]['word_indices'],list(range(9)))
        self.assertEqual(tables[0]['rows'],[['Product','Units','Price'],['Apple','12','1.20'],['Pear','5','3.00']])
        self.assertEqual(_aligned_tables(self.words([['First','Other'],['Story','Prose'],['Final','Words']]),set()),[])

    def test_table_word_identity_does_not_remove_prose_inside_enclosing_rectangle(self):
        words=self.words([['Outside','12'],['Keep','99']])
        analysis=dict(words=words,tables=[dict(rect=[0,0,500,500],rows=[['Outside','12']],word_indices=[0,1],merges=[])])
        result=elements(analysis);text=' '.join(span['text'] for entry in result if entry['type']==0 for line in entry['lines'] for span in line['spans'])
        self.assertIn('Keep',text);self.assertIn('99',text);self.assertNotIn('Outside',text)
