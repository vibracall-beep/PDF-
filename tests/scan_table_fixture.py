"""Synthetic tables rasterized before entering the PDF used by OCR tests."""
import io
import fitz
from PIL import Image


def scanned_table(path,kind='merged',skew=0,broken=False):
    scale=200/72
    with fitz.open() as drawing:
        page=drawing.new_page(width=500,height=520)
        page.insert_text((40,35),'Inventory report',fontsize=18)
        if kind=='merged':
            for x in (40,320,440): page.draw_line((x,80),(x,260),width=1.5)
            page.draw_line((180,140),(180,260),width=1.5)
            for y in (80,140,260): page.draw_line((40,y),(440,y),width=1.5)
            page.draw_line((180,200),(440,200),width=1.5)
            if broken: page.draw_rect(fitz.Rect(220,136,260,144),color=None,fill=(1,1,1))
            for x,y,value in [(50,120,'Merged header'),(330,120,'Units'),(50,185,'Group'),(190,180,'Apple'),(330,180,'10'),(190,240,'Orange'),(330,240,'20')]:
                page.insert_text((x,y),value,fontsize=14)
        else:
            rows=[['Product','Units','Price'],['Apple','12','1.20'],['Pear','5','3.00']]
            if kind=='prose': rows=[['First story','Other prose','Extra words'],['Next story','Middle prose','More words'],['Final story','Last prose','End words']]
            for row,values in enumerate(rows):
                for column,value in enumerate(values): page.insert_text((40+column*150,100+row*50),value,fontsize=14)
        page.insert_text((40,320),'Review every value',fontsize=14)
        pix=page.get_pixmap(dpi=200,colorspace=fitz.csGRAY)
        image=Image.frombytes('L',(pix.width,pix.height),pix.samples)
    original_size=image.size
    if skew:
        prior=image;image=image.rotate(skew,Image.Resampling.BICUBIC,expand=True,fillcolor=255);prior.close()
    width,height=image.size;stream=io.BytesIO();image.save(stream,format='PNG');image.close()
    with fitz.open() as result:
        page=result.new_page(width=width/scale,height=height/scale)
        page.insert_image(page.rect,stream=stream.getvalue());result.save(path)
    return dict(original_size=original_size,size=(width,height),scale=scale,skew=skew)
