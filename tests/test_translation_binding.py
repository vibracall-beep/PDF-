"""Source identity is verified on actual immutable PDF bytes, not just text boxes."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run


class TranslationBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'original.pdf'
        with fitz.open() as document:
            page = document.new_page(width=400, height=500)
            page.insert_text((40,80), 'Original text', fontsize=16)
            page.draw_rect((200,250,300,350), color=(1,0,0), fill=(1,0,0))
            document.save(self.source)
        self.original = self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.root.glob('.pdf-output-*')), [])
        self.temporary.cleanup()

    def blocks(self, source=None, options=None):
        output = self.root / ('layout-' + str(len(list(self.root.glob('layout-*')))) + '.json')
        run('layout-extract', [source or self.source], output, options)
        return json.loads(output.read_text())

    def edit(self, block=None):
        block = block or self.blocks()[0]
        return {**block, 'source_text': block['text'], 'text': 'Texto traduzido'}

    def test_extraction_binds_all_blocks_to_original_file_bytes(self):
        blocks = self.blocks()
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['source_sha256'], hashlib.sha256(self.original).hexdigest())
        output = self.root / 'translated.pdf'
        run('translate-layout', [self.source], output, {'edits': [self.edit(blocks[0])]})
        with fitz.open(output) as document:
            self.assertIn('Texto traduzido', document[0].get_text())
            self.assertNotIn('Original text', document[0].get_text())
            self.assertEqual(document[0].get_pixmap(clip=fitz.Rect(200,250,300,350)).samples,
                             fitz.open(stream=self.original, filetype='pdf')[0].get_pixmap(clip=fitz.Rect(200,250,300,350)).samples)

    def test_changed_graphic_with_identical_text_and_boxes_is_refused(self):
        edit = self.edit()
        changed = self.root / 'graphic-changed.pdf'
        with fitz.open(self.source) as document:
            document[0].draw_rect((200,250,300,350), color=(0,0,1), fill=(0,0,1))
            document.save(changed)
        self.assertEqual(self.blocks(changed)[0]['text'], edit['source_text'])
        output = self.root / 'refused.pdf'
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            run('translate-layout', [changed], output, {'edits': [edit]})
        self.assertFalse(output.exists())

    def test_changed_metadata_outside_translated_blocks_is_refused(self):
        edit = self.edit()
        changed = self.root / 'metadata-changed.pdf'
        with fitz.open(self.source) as document:
            document.set_metadata({'title': 'A different document revision'})
            document.save(changed)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            run('translate-layout', [changed], self.root / 'refused.pdf', {'edits': [edit]})
        self.assertFalse((self.root / 'refused.pdf').exists())

    def test_same_bytes_at_another_path_keep_the_valid_plan(self):
        edit = self.edit(); copied = self.root / 'renamed.pdf'; copied.write_bytes(self.original)
        output = self.root / 'translated.pdf'
        run('translate-layout', [copied], output, {'edits': [edit]})
        with fitz.open(output) as document: self.assertIn('Texto traduzido', document[0].get_text())

    def test_missing_malformed_and_mixed_fingerprints_are_refused(self):
        original = self.edit()
        for digest in (None, '', '0' * 64, 'A' * 64, True, ['a' * 64]):
            with self.subTest(digest=digest):
                edit = dict(original)
                if digest is None: edit.pop('source_sha256')
                else: edit['source_sha256'] = digest
                output = self.root / 'refused.pdf'
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    run('translate-layout', [self.source], output, {'edits': [edit]})
                self.assertFalse(output.exists())
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            run('translate-layout', [self.source], self.root / 'mixed.pdf',
                {'edits': [original, {**original, 'source_sha256': '0' * 64}]})
        self.assertFalse((self.root / 'mixed.pdf').exists())

    def test_source_bound_id_page_rectangle_and_source_text_cannot_be_changed(self):
        original = self.edit()
        mutations = [{'id': 'p1-b999'}, {'page': 2}, {'rect': [40,40,200,150]}, {'source_text': 'Other text'}, {'source_text': ''}]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                output = self.root / 'refused.pdf'
                with self.assertRaises(ValueError):
                    run('translate-layout', [self.source], output, {'edits': [{**original, **mutation}]})
                self.assertFalse(output.exists())
        with self.assertRaisesRegex(ValueError, 'repetido'):
            run('translate-layout', [self.source], self.root / 'duplicate.pdf', {'edits': [original, original]})
        self.assertFalse((self.root / 'duplicate.pdf').exists())

    def test_input_snapshot_remains_bound_when_path_is_replaced_after_read(self):
        import pdf_content
        copied = self.root / 'mutable.pdf'; copied.write_bytes(self.original)
        original_source = pdf_content._source
        def changed_after_snapshot(path, options):
            document, digest = original_source(path, options)
            with fitz.open() as replacement:
                replacement.new_page().insert_text((40,80), 'Changed file on disk')
                replacement.save(path)
            return document, digest
        with patch('pdf_content._source', side_effect=changed_after_snapshot):
            blocks = self.blocks(copied)
        self.assertEqual(blocks[0]['text'], 'Original text')
        self.assertEqual(blocks[0]['source_sha256'], hashlib.sha256(self.original).hexdigest())
        output = self.root / 'refused.pdf'
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            run('translate-layout', [copied], output, {'edits': [self.edit(blocks[0])]})
        self.assertFalse(output.exists())

    def test_nonregular_and_symlink_sources_are_refused(self):
        linked = self.root / 'link.pdf'; linked.symlink_to(self.source)
        fifo = self.root / 'fifo.pdf'; os.mkfifo(fifo)
        for path in (linked, fifo):
            with self.subTest(path=path.name), self.assertRaises(ValueError): self.blocks(path)

    def test_source_text_comparison_preserves_exact_unicode_codepoints(self):
        source = self.root / 'unicode.pdf'
        with fitz.open() as document:
            document.new_page().insert_text((40,80), 'Caf\u00e9 original', fontsize=16)
            document.save(source)
        block = self.blocks(source)[0]
        self.assertEqual(block['text'], 'Caf\u00e9 original')
        edit = self.edit(block); edit['source_text'] = 'Cafe\u0301 original'
        output = self.root / 'unicode-refused.pdf'
        with self.assertRaisesRegex(ValueError, 'bloco original mudou'):
            run('translate-layout', [source], output, {'edits': [edit]})
        self.assertFalse(output.exists())

    def test_encrypted_source_identity_and_output_protection_are_preserved(self):
        encrypted = self.root / 'protected.pdf'; secret = 'synthetic-translation-password'
        with fitz.open(self.source) as document:
            document.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=secret, owner_pw='synthetic-owner',
                          permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY | fitz.PDF_PERM_MODIFY)
        original = encrypted.read_bytes()
        with fitz.open(encrypted) as document:
            self.assertTrue(document.authenticate(secret)); permissions = document.permissions
        block = self.blocks(encrypted, {'password': secret})[0]
        self.assertEqual(block['source_sha256'], hashlib.sha256(original).hexdigest())
        output = self.root / 'translated-protected.pdf'
        run('translate-layout', [encrypted], output, {'password': secret, 'edits': [self.edit(block)]})
        with fitz.open(output) as document:
            self.assertTrue(document.needs_pass)
            self.assertFalse(document.authenticate('incorrect'))
            self.assertTrue(document.authenticate(secret))
            self.assertEqual(document.permissions, permissions)
            self.assertIn('Texto traduzido', document[0].get_text())
        self.assertEqual(encrypted.read_bytes(), original)

if __name__ == '__main__': unittest.main()
