"""Standard AcroForm /Opt export/display pairs from external PDF producers."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import fitz

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run


class ChoiceOptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.source=self.root/'external-form.pdf'
        with fitz.open() as doc:
            for name,kind in [('combo',fitz.PDF_WIDGET_TYPE_COMBOBOX),('list',fitz.PDF_WIDGET_TYPE_LISTBOX)]:
                page=doc.new_page(); widget=fitz.Widget()
                widget.field_name=name; widget.field_type=kind
                widget.rect=fitz.Rect(30,30,250,100); widget.text_fontsize=12
                widget.choice_values=['BR','PT']; widget.field_value='BR'
                xref=page.add_widget(widget).xref
                # Pairs are defined by PDF itself, independent of our form creator.
                doc.xref_set_key(xref,'Opt','[[(BR)(Brasil)][(PT)(Portugal)]]')
            doc.save(self.source)
        self.original=self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original)
        self.temporary.cleanup()

    def test_inspection_separates_export_values_from_display_labels(self):
        target=self.root/'fields.json';run('forms',[self.source],target)
        records=json.loads(target.read_text())
        self.assertEqual(len(records),2)
        for record in records:
            self.assertEqual(record['value'],'BR')
            self.assertEqual(record['choices'],['BR','PT'])
            self.assertEqual(record['choice_labels'],{'BR':'Brasil','PT':'Portugal'})

    def test_fill_preserves_export_values_labels_and_selection_appearance(self):
        target=self.root/'filled.pdf'
        run('form-fill',[self.source],target,{'values':{'combo':'PT','list':'PT'}})
        with fitz.open(target) as doc:
            for page in doc:
                widget=next(page.widgets())
                self.assertEqual(widget.field_value,'PT')
                self.assertEqual(widget.choice_values,[('BR','Brasil'),('PT','Portugal')])
                self.assertEqual(doc.xref_get_key(widget.xref,'I'),('array','[1]'))
                text=page.get_text().strip()
                self.assertIn('Portugal',text)
                self.assertNotIn('PT',text)
                if widget.field_type==fitz.PDF_WIDGET_TYPE_COMBOBOX:
                    self.assertEqual(text,'Portugal')

    def test_display_label_is_not_accepted_as_export_value(self):
        target=self.root/'invalid.pdf'
        with self.assertRaisesRegex(ValueError,'Escolha inválida'):
            run('form-fill',[self.source],target,{'values':{'combo':'Portugal'}})
        self.assertFalse(target.exists())

    def test_clearing_pair_choices_preserves_options_and_clears_selection(self):
        target=self.root/'cleared.pdf'
        run('form-fill',[self.source],target,{'values':{'combo':'','list':''}})
        with fitz.open(target) as doc:
            for page in doc:
                widget=next(page.widgets())
                self.assertEqual(widget.field_value,'')
                self.assertEqual(doc.xref_get_key(widget.xref,'I'),('array','[]'))
                self.assertEqual(widget.choice_values,[('BR','Brasil'),('PT','Portugal')])
            self.assertEqual(doc[0].get_text().strip(),'')


if __name__=='__main__':unittest.main()
