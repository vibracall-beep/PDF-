"""Text-only angle evidence and refusal controls, independent of OCR results."""
from pathlib import Path
import random
import sys
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from scan_analysis import _segments,_components
from scan_geometry import deskew
from tests.scan_text_skew_fixture import text_raster


class TextDeskewTests(unittest.TestCase):
    def check(self,image):
        before=image.tobytes();result,metadata=deskew(image,2.5,_segments,_components)
        self.assertEqual(image.tobytes(),before)
        if result is not image:result.close()
        return metadata
    def test_known_text_baselines_recover_both_directions_without_mutating_pixels(self):
        with text_raster() as source:
            for angle in (-4.2,-1.5,1.5,3.5):
                with self.subTest(angle=angle),source.rotate(angle,Image.Resampling.BICUBIC,expand=True,fillcolor=255) as image:
                    metadata=self.check(image)
                    self.assertTrue(metadata['applied']);self.assertEqual(metadata['status'],'text-line-projection-evidence')
                    self.assertAlmostEqual(metadata['rotation_degrees'],-angle,delta=.3)
                    self.assertGreaterEqual(metadata['text_line_bands'],4)
    def test_upright_and_out_of_range_text_are_not_rotated(self):
        with text_raster() as source:
            for angle in (0,-10,10):
                with self.subTest(angle=angle),source.rotate(angle,Image.Resampling.BICUBIC,expand=True,fillcolor=255) as image:
                    self.assertFalse(self.check(image)['applied'])
    def test_sparse_text_is_insufficient_even_when_its_angle_is_known(self):
        with text_raster(lines=1) as source,source.rotate(3,Image.Resampling.BICUBIC,expand=True,fillcolor=255) as image:
            self.assertFalse(self.check(image)['applied'])
    def test_upright_frame_takes_precedence_over_a_tilted_text_inset(self):
        with text_raster() as source,source.rotate(3,Image.Resampling.BICUBIC,expand=True,fillcolor=255) as image:
            drawing=ImageDraw.Draw(image)
            drawing.rectangle((10,10,image.width-11,image.height-11),outline=0,width=4)
            self.assertFalse(self.check(image)['applied'])
    def test_blank_rules_and_speckled_pages_do_not_invent_text_baselines(self):
        for mode in ('blank','rules','speckles'):
            with self.subTest(mode=mode),Image.new('L',(800,1000),255) as source:
                drawing=ImageDraw.Draw(source)
                if mode=='rules':
                    for row in range(100,900,70):drawing.line((40,row,760,row),fill=0,width=4)
                if mode=='speckles':
                    rng=random.Random(1459)
                    for _ in range(4000):drawing.point((rng.randrange(800),rng.randrange(1000)),fill=0)
                with source.rotate(3,Image.Resampling.NEAREST,expand=True,fillcolor=255) as image:
                    self.assertFalse(self.check(image)['applied'])


if __name__=='__main__':unittest.main()
