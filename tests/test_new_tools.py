"""Additional screenshot tools: image/text/book conversion and PDF page utilities."""
from pathlib import Path
import sys
import tempfile
import unittest
import unicodedata
import zipfile

import fitz
from PIL import Image, ImageChops, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run


def write_epub(path):
    files = {
        'META-INF/container.xml': '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>''',
        'OEBPS/content.opf': '''<?xml version="1.0" encoding="UTF-8"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="book">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>PDF EPUB fixture</dc:title><dc:language>pt</dc:language><dc:identifier id="book">urn:uuid:pdf-test-book</dc:identifier></metadata>
<manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>
<spine toc="ncx"><itemref idref="chapter"/></spine></package>''',
        'OEBPS/toc.ncx': '''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="urn:uuid:pdf-test-book"/></head><docTitle><text>PDF EPUB fixture</text></docTitle><navMap><navPoint id="chapter" playOrder="1"><navLabel><text>Capítulo</text></navLabel><content src="chapter.xhtml"/></navPoint></navMap></ncx>''',
        'OEBPS/chapter.xhtml': '''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Capítulo</title></head><body><h1>EPUB Integration</h1><p>Conteúdo do livro: ação e coração.</p><p>End of the fixture book.</p></body></html>''',
    }
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        for name, text in files.items():
            archive.writestr(name, text.encode('utf-8'), compress_type=zipfile.ZIP_DEFLATED)


class NewToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.pdf'
        with fitz.open() as doc:
            for index in range(1, 5):
                page = doc.new_page(width=200, height=300)
                page.insert_text((20, 40), f'Original page {index}', fontsize=12)
            doc.save(self.source)
        self.original = self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.tmp.cleanup()

    def test_png_export_uses_requested_resolution_and_alpha(self):
        folder = self.root / 'png'
        run('png', [self.source], folder, {'pages': '2', 'dpi': 144, 'alpha': True})
        paths = list(folder.glob('*.png'))
        self.assertEqual(len(paths), 1)
        with Image.open(paths[0]) as image:
            self.assertEqual(image.size, (400, 600))
            self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(image.getpixel((0, 0))[3], 0)
            self.assertGreater(image.getchannel('A').getextrema()[1], 0)

    def test_png_export_can_render_opaque_background(self):
        folder = self.root / 'opaque'
        run('png', [self.source], folder, {'pages': '1', 'dpi': 72, 'alpha': False})
        with Image.open(next(folder.glob('*.png'))) as image:
            self.assertEqual(image.size, (200, 300))
            self.assertEqual(image.convert('RGB').getpixel((0, 0)), (255, 255, 255))
            if image.mode == 'RGBA':
                self.assertEqual(image.getchannel('A').getextrema(), (255, 255))

    def test_embedded_png_reconstructs_image_transparency(self):
        image_path = self.root / 'transparent.png'
        image = Image.new('RGBA', (50, 30), (0, 0, 0, 0))
        image.paste((230, 30, 40, 128), (10, 5, 40, 25))
        image.save(image_path)
        source = self.root / 'image.pdf'
        with fitz.open() as doc:
            page = doc.new_page(width=200, height=300)
            page.insert_image(fitz.Rect(20, 50, 120, 110), filename=str(image_path))
            doc.save(source)
        folder = self.root / 'embedded-png'
        run('png', [source], folder, {'mode': 'embedded'})
        with Image.open(next(folder.glob('*.png'))) as restored:
            self.assertEqual(restored.size, (50, 30))
            self.assertEqual(restored.mode, 'RGBA')
            self.assertEqual(restored.getpixel((0, 0))[3], 0)
            self.assertEqual(restored.getpixel((20, 10))[3], 128)

    def test_text_to_pdf_preserves_portuguese_and_unicode(self):
        source = self.root / 'source.txt'
        text = 'Ação, açúcar e coração.\nEuro € e travessão — preservados.'
        source.write_text(text, encoding='utf-8')
        before = source.read_bytes()
        target = self.root / 'text.pdf'
        run('txt', [source], target)
        with fitz.open(target) as doc:
            content = ''.join(page.get_text() for page in doc)
            for token in ('Ação', 'açúcar', 'coração', '€', '—'):
                self.assertIn(token, content)
        self.assertEqual(source.read_bytes(), before)

    def test_text_to_pdf_paginates_without_losing_last_line(self):
        source = self.root / 'long.txt'
        source.write_text('\n'.join(f'Linha {index:03d} do documento de teste.' for index in range(180)), encoding='utf-8')
        target = self.root / 'long.pdf'
        run('txt', [source], target, {'font_size': 14, 'paper': 'a5', 'margin': 24})
        with fitz.open(target) as doc:
            self.assertGreater(len(doc), 1)
            text = ''.join(page.get_text() for page in doc)
            self.assertIn('Linha 000', text)
            self.assertIn('Linha 179', text)
            self.assertEqual(text.count('do documento de teste.'), 180)

    def test_text_long_unbroken_token_is_wrapped_without_character_loss(self):
        source = self.root / 'long-token.txt'
        source.write_text('A' * 5000, encoding='utf-8')
        target = self.root / 'long-token.pdf'
        run('txt', [source], target, {'paper': 'a5', 'font_size': 14, 'margin': 24})
        with fitz.open(target) as doc:
            self.assertGreater(len(doc), 1)
            self.assertEqual(sum(page.get_text().count('A') for page in doc), 5000)
            for page in doc:
                for block in page.get_text('blocks'):
                    self.assertGreaterEqual(block[0], -1)
                    self.assertLessEqual(block[2], page.rect.width + 1)

    def test_csv_unrenderable_cell_is_rejected_without_partial_output(self):
        source = self.root / 'unrenderable.csv'
        source.write_text('Header\n' + 'verylongvalue ' * 1000 + '\n', encoding='utf-8')
        original = source.read_bytes()
        target = self.root / 'unrenderable.pdf'
        with self.assertRaises(ValueError):
            run('csv', [source], target)
        self.assertFalse(target.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_invalid_text_encoding_does_not_publish_partial_pdf(self):
        source = self.root / 'invalid.txt'
        source.write_bytes(b'\xff\xfe\xff')
        target = self.root / 'invalid.pdf'
        with self.assertRaises((UnicodeError, ValueError)):
            run('txt', [source], target, {'encoding': 'utf-8'})
        self.assertFalse(target.exists())

    def test_epub_conversion_preserves_book_content(self):
        source = self.root / 'book.epub'
        write_epub(source)
        original = source.read_bytes()
        target = self.root / 'book.pdf'
        run('epub', [source], target)
        with fitz.open(target) as doc:
            self.assertGreater(len(doc), 0)
            # Reflow may encode typographic ligatures such as 'ﬁ'; normalize
            # presentation forms while still verifying the complete book text.
            text = unicodedata.normalize('NFKC', ''.join(page.get_text() for page in doc))
            self.assertIn('EPUB Integration', text)
            self.assertIn('coração', text)
            self.assertIn('End of the fixture book.', text)
        self.assertEqual(source.read_bytes(), original)

    def test_flatten_bakes_visible_annotations_and_widgets(self):
        source = self.root / 'interactive.pdf'
        with fitz.open(self.source) as doc:
            page = doc[0]
            note = page.add_freetext_annot(fitz.Rect(20, 70, 180, 105), 'Reviewed', fontsize=16)
            note.update()
            field = fitz.Widget()
            field.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            field.field_name = 'customer'
            field.field_value = 'Maria Silva'
            field.text_fontsize = 14
            field.rect = fitz.Rect(20, 150, 180, 180)
            page.add_widget(field)
            doc.save(source)
        before = source.read_bytes()
        target = self.root / 'flattened.pdf'
        run('flatten', [source], target)
        with fitz.open(source) as original, fitz.open(target) as flattened:
            self.assertEqual(len(flattened), len(original))
            self.assertFalse(any(list(page.annots() or []) for page in flattened))
            self.assertFalse(any(list(page.widgets() or []) for page in flattened))
            rendered_before = original[0].get_pixmap(dpi=144, alpha=False)
            rendered_after = flattened[0].get_pixmap(dpi=144, alpha=False)
            first = Image.frombytes('RGB', (rendered_before.width, rendered_before.height), rendered_before.samples)
            second = Image.frombytes('RGB', (rendered_after.width, rendered_after.height), rendered_after.samples)
            difference = ImageChops.difference(first, second)
            self.assertLess(max(ImageStat.Stat(difference).mean), 0.5)
            text = flattened[0].get_text()
            self.assertIn('Reviewed', text)
            self.assertIn('Maria Silva', text)
        self.assertEqual(source.read_bytes(), before)

    def test_delete_pages_keeps_remaining_order(self):
        target = self.root / 'deleted.pdf'
        run('delete-pages', [self.source], target, {'pages': '2,4'})
        with fitz.open(target) as doc:
            self.assertEqual(len(doc), 2)
            self.assertIn('Original page 1', doc[0].get_text())
            self.assertIn('Original page 3', doc[1].get_text())

    def test_delete_all_pages_is_rejected_without_output(self):
        target = self.root / 'empty.pdf'
        with self.assertRaises(ValueError):
            run('delete-pages', [self.source], target, {'pages': '1-4'})
        self.assertFalse(target.exists())

    def test_delete_invalid_page_is_rejected_without_output(self):
        target = self.root / 'invalid-delete.pdf'
        with self.assertRaises(ValueError):
            run('delete-pages', [self.source], target, {'pages': '5'})
        self.assertFalse(target.exists())

    def test_delete_and_extract_require_explicit_page_selection(self):
        for operation in ['delete-pages', 'extract-pages']:
            with self.subTest(operation=operation):
                target = self.root / (operation + '-missing.pdf')
                with self.assertRaises(ValueError):
                    run(operation, [self.source], target)
                self.assertFalse(target.exists())

    def test_extract_pages_keeps_explicit_order(self):
        target = self.root / 'extracted.pdf'
        run('extract-pages', [self.source], target, {'pages': '4,2-3'})
        with fitz.open(target) as doc:
            self.assertEqual(len(doc), 3)
            self.assertIn('Original page 4', doc[0].get_text())
            self.assertIn('Original page 2', doc[1].get_text())
            self.assertIn('Original page 3', doc[2].get_text())

    def test_flatten_delete_extract_preserve_password(self):
        password = 'protected-tools-123'
        protected = self.root / 'protected.pdf'
        run('protect', [self.source], protected, {'new_password': password})
        original = protected.read_bytes()
        for operation, options, expected_pages in [('flatten', {}, 4), ('delete-pages', {'pages': '2-4'}, 1), ('extract-pages', {'pages': '2-3'}, 2)]:
            with self.subTest(operation=operation):
                target = self.root / (operation + '.pdf')
                run(operation, [protected], target, {'password': password, **options})
                with fitz.open(target) as doc:
                    self.assertTrue(doc.needs_pass)
                    self.assertFalse(doc.authenticate('wrong'))
                    self.assertTrue(doc.authenticate(password))
                    self.assertEqual(len(doc), expected_pages)
                    self.assertIn('Original page', doc[0].get_text())
        self.assertEqual(protected.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
