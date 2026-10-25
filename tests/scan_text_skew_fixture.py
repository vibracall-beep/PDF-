"""Known baselines rendered to pixels before text-only skew and OCR."""
import io

import fitz
from PIL import Image, ImageFilter


LINES = [
    'Read every line and preserve the original document.',
    'The invoice contains 12 apples and 24 oranges.',
    'Payment is due on the final working day.',
    'Keep a separate copy of the reviewed page.',
    'The total quantity is 36 items in this order.',
    'All amounts require careful independent review.',
    'Search the recognized text after saving the PDF.',
    'Confirm each value against the original image.',
]


def text_raster(lines=8,low_contrast=False):
    with fitz.open() as document:
        page=document.new_page(width=500,height=400)
        if low_contrast: page.draw_rect(page.rect,color=None,fill=(.86,.86,.86))
        for index,text in enumerate(LINES[:lines]):
            page.insert_text((36,55+index*35),text,fontsize=13,color=(.42,.42,.42) if low_contrast else (0,0,0))
        pixels=page.get_pixmap(dpi=180,colorspace=fitz.csGRAY)
        result=Image.frombytes('L',(pixels.width,pixels.height),pixels.samples)
    if low_contrast:
        prior=result;result=result.filter(ImageFilter.GaussianBlur(.4));prior.close()
    return result


def scanned_text(path,angle=0,low_contrast=False):
    with text_raster(low_contrast=low_contrast) as original:
        original_size=original.size
        with original.rotate(angle,Image.Resampling.BICUBIC,expand=True,fillcolor=219 if low_contrast else 255) as image:
            output=io.BytesIO();image.save(output,format='PNG');size=image.size
    with fitz.open() as document:
        page=document.new_page(width=size[0]/2.5,height=size[1]/2.5)
        page.insert_image(page.rect,stream=output.getvalue());document.save(path)
    return dict(original_size=original_size,size=size,scale=2.5,skew=angle)
