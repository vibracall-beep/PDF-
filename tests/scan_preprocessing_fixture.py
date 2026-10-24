"""Raster text at enlarged physical sizes; no hidden searchable text remains."""
import fitz


def scanned_prose(path, enlarged=True):
    with fitz.open() as drawing:
        page = drawing.new_page(width=595, height=842)
        page.insert_text((48,96), 'A reference for comparison.', fontname='hebo', fontsize=23, color=(0,.48,1))
        lines = [
            'Read clearly and find the information that matters.',
            'The PDF reader combines organization and local intelligence.',
            'Select text to highlight. Add notes or draw on the page.',
            'Use thumbnails and bookmarks to navigate the document.',
            'Save a new copy to preserve your original document.',
        ]
        for index, line in enumerate(lines):
            page.insert_text((48,152+index*27), line, fontsize=12)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1600/842,1600/842), alpha=False)
    with fitz.open() as scanned:
        width,height = (pixmap.width,pixmap.height) if enlarged else (595,842)
        page = scanned.new_page(width=width,height=height)
        page.insert_image(page.rect,stream=pixmap.tobytes('png'))
        scanned.save(path)
    return lines
