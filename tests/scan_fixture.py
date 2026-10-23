"""Raster-only fixtures: original vector/text objects never enter the test PDF."""
import fitz


def scanned_form(path):
    with fitz.open() as drawing:
        page=drawing.new_page(width=500,height=650)
        page.insert_text((40,35),'Order form',fontsize=18)
        for x in (40,220,340): page.draw_line((x,70),(x,190),width=1.5)
        for y in (70,110,150,190): page.draw_line((40,y),(340,y),width=1.5)
        for row,texts in enumerate([['Product','Amount'],['Apples','12'],['Oranges','34']]):
            for column,text in enumerate(texts): page.insert_text((50 if column==0 else 230,96+row*40),text,fontsize=14)
        page.insert_text((40,250),'Name:',fontsize=14)
        page.draw_rect(fitz.Rect(110,230,340,260),width=1.5)
        page.insert_text((75,310),'Accept terms',fontsize=14)
        page.draw_rect(fitz.Rect(40,292,58,310),width=1.5)
        page.insert_text((40,365),'Date:',fontsize=14)
        page.draw_line((110,365),(300,365),width=1.5)
        image=page.get_pixmap(dpi=200).tobytes('png')
    with fitz.open() as result:
        page=result.new_page(width=500,height=650);page.insert_image(page.rect,stream=image);result.save(path)
