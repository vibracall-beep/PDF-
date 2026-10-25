"""Actual PDF exports retain literal text, explicit lists and safe destinations."""
from pathlib import Path
import sys
import tempfile
import unittest

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run
from markdown_layout import safe_uri


class MarkdownSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = {}

    def tearDown(self):
        for source, data in self.sources.items():
            self.assertEqual(source.read_bytes(), data)
        self.assertEqual(list(self.root.glob('.pdf-output-*')), [])
        self.temporary.cleanup()

    def save(self, document, name='source'):
        source = self.root / (name + '.pdf')
        document.save(source)
        self.sources[source] = source.read_bytes()
        return source

    def export(self, source, options=None, name='result'):
        output = self.root / (name + '.md')
        run('markdown', [source], output, options)
        return output.read_text()

    def test_visible_bullets_and_nested_levels_are_structural(self):
        with fitz.open() as doc:
            page = doc.new_page(width=500, height=500)
            page.insert_font(fontname='Fixture', fontbuffer=fitz.Font('cjk').buffer)
            for x,y,text in [(40,60,'• Parent one'),(64,82,'◦ Child one'),(64,104,'◦ Child two'),(40,126,'• Parent two')]:
                page.insert_text((x,y), text, fontname='Fixture', fontsize=12)
            source = self.save(doc)
        text = self.export(source)
        for item in ['- Parent one','    - Child one','    - Child two','- Parent two']:
            self.assertIn('\n' + item + '\n', text)
        self.assertNotIn('•',text)

    def test_ascii_nested_markers_require_nearby_repeated_evidence(self):
        with fitz.open() as doc:
            page=doc.new_page()
            for x,y,text in [(40,60,'- Main'),(64,82,'- Child'),(40,104,'- Next')]:
                page.insert_text((x,y),text)
            source=self.save(doc)
        text=self.export(source)
        self.assertIn('\n- Main\n',text);self.assertIn('\n    - Child\n',text);self.assertIn('\n- Next\n',text)

    def test_ordered_sequences_and_uncertain_numbers_preserve_values(self):
        with fitz.open() as doc:
            page = doc.new_page()
            for y,text in [(50,'3. Third item'),(70,'4. Fourth item'),(160,'7. Isolated number'),(240,'4. Nonsequential A'),(260,'9. Nonsequential B'),(340,'2026. A year')]:
                page.insert_text((40,y),text)
            source = self.save(doc)
        text = self.export(source)
        self.assertIn('\n3. Third item\n',text);self.assertIn('\n4. Fourth item\n',text)
        for literal in [r'7\. Isolated number',r'4\. Nonsequential A',r'9\. Nonsequential B',r'2026\. A year']:
            self.assertIn(literal,text)

    def test_discontinuous_numbered_runs_are_never_silently_renumbered(self):
        with fitz.open() as doc:
            page=doc.new_page()
            for index,number in enumerate((1,2,4,5)):
                page.insert_text((40,60+index*22),f'{number}. Original item')
            source=self.save(doc)
        text=self.export(source)
        for number in (1,2,4,5): self.assertIn(f'{number}\\. Original item',text)

    def test_literal_entities_markup_and_unproven_bullet_remain_inert(self):
        with fitz.open() as doc:
            page = doc.new_page()
            for y,text in [(50,'&lt; literal &copy; <script>'),(90,'[not a link](javascript:alert(1))'),(130,'*literal emphasis*'),(200,'- An isolated literal marker'),(270,'---')]:
                page.insert_text((40,y),text)
            source = self.save(doc)
        text = self.export(source)
        self.assertIn('&amp;lt; literal &amp;copy; &lt;script&gt;',text)
        self.assertIn(r'\[not a link\](javascript:alert(1))',text)
        self.assertIn(r'\*literal emphasis\*',text)
        self.assertIn(r'\- An isolated literal marker',text)
        self.assertIn(r'\-\-\-',text)

    def test_external_link_stays_inline_and_uri_bytes_remain_literal(self):
        uri='https://example.org/a (b)/ação?q=1&tag=&copy;'
        with fitz.open() as doc:
            page=doc.new_page();page.insert_text((40,60),'Visit Example for details')
            page.insert_link({'kind':fitz.LINK_URI,'from':page.search_for('Example')[0],'uri':uri})
            source=self.save(doc)
        text=self.export(source)
        self.assertIn('Visit [Example](<https://example.org/a%20%28b%29/a%C3%A7%C3%A3o?q=1&amp;tag=&amp;copy;>) for details',text)
        self.assertEqual(text.count('Example'),1)

    def test_internal_links_target_only_exported_page_anchors(self):
        with fitz.open() as doc:
            doc.new_page();doc.new_page()
            page=doc[0];page.insert_text((40,60),'Go to second page')
            doc[1].insert_text((40,60),'Second page content')
            page.insert_link({'kind':fitz.LINK_GOTO,'from':page.search_for('second page')[0],'page':1,'to':fitz.Point(40,60)})
            source=self.save(doc)
        text=self.export(source)
        self.assertIn('[second page](<#pdf-page-2>)',text)
        self.assertIn('<a id="pdf-page-2"></a>',text)
        selected=self.export(source, {'pages':'1'}, name='selected')
        self.assertNotIn('#pdf-page-2',selected);self.assertNotIn('id="pdf-page-2"',selected)
        self.assertIn('Go to second page',selected)

    def test_active_schemes_controls_and_markdown_injection_are_not_links(self):
        targets=['javascript:alert(1)','data:text/html,<script>','file:///tmp/private',
                 'https://example.org/)\n\n![injected](https://injected.invalid/x)',
                 'https://example.org/%0aattack','https://example.org/\\evil']
        with fitz.open() as doc:
            page=doc.new_page()
            for index,uri in enumerate(targets):
                label=f'Unsafe target {index}'
                page.insert_text((40,60+index*35),label)
                page.insert_link({'kind':fitz.LINK_URI,'from':page.search_for(label)[0],'uri':'https://fixture.invalid'})
                # Encode the literal PDF string correctly; insert_link alone
                # interprets backslashes before the exporter ever sees them.
                xref=page.annot_xrefs()[-1][0]
                doc.xref_set_key(xref,'A','<< /S /URI /URI '+fitz.get_pdf_str(uri)+' >>')
            source=self.save(doc)
        text=self.export(source)
        for index in range(len(targets)):self.assertIn(f'Unsafe target {index}',text)
        self.assertNotIn('](<',text);self.assertNotIn('injected.invalid',text)
        for target in targets + ['https://example.org:bad/a','https://','https://user@exa mple.org','MAILTO:']:
            with self.subTest(target=target):self.assertIsNone(safe_uri(target))

    def test_styled_link_text_is_not_duplicated(self):
        with fitz.open() as doc:
            page=doc.new_page();page.insert_text((40,60),'Example',fontname='hebo')
            page.insert_link({'kind':fitz.LINK_URI,'from':page.search_for('Example')[0],'uri':'https://example.org'})
            source=self.save(doc)
        text=self.export(source)
        self.assertIn('[**Example**](<https://example.org>)',text);self.assertEqual(text.count('Example'),1)

    def test_table_cells_preserve_literal_markdown_entities_and_pipes(self):
        with fitz.open() as doc:
            page=doc.new_page(width=500,height=500)
            for x in (40,240,440):page.draw_line((x,40),(x,160))
            for y in (40,80,120,160):page.draw_line((40,y),(440,y))
            for row,values in enumerate([('Label','Value'),('*literal*','&lt; text'),('[link]','a | b')]):
                for column,value in enumerate(values):page.insert_text((50+column*200,65+row*40),value,fontsize=10)
            source=self.save(doc)
        text=self.export(source)
        self.assertIn(r'| \*literal\* | &amp;lt; text |',text)
        self.assertIn(r'| \[link\] | a \| b |',text)


if __name__ == '__main__': unittest.main()
