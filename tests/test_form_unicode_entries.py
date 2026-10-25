"""Form identities and export values must remain exact across Swift/Python JSON."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

import fitz

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run


class FormUnicodeEntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.composed='caf\u00e9';self.decomposed='cafe\u0301'
        base=self.root/'base.pdf'
        with fitz.open() as doc:doc.new_page();doc.save(base)
        created=self.root/'created.pdf'
        run('form-create',[base],created,{'fields':[
            {'name':self.composed,'type':'text','rect':[40,50,240,80],'value':'First original'},
            {'name':self.decomposed,'type':'text','rect':[40,100,240,130],'value':'Second original'},
            {'name':'choice','type':'choice','rect':[40,150,240,180],'choices':['First','Second'],'value':'First'},
            {'name':'check','type':'checkbox','rect':[40,200,60,220],'value':False},
            {'name':'radio','type':'radio','choices':[
                {'value':self.composed,'label':'First','rect':[40,250,60,270]},
                {'value':self.decomposed,'label':'Second','rect':[40,290,60,310]}]}]})
        self.source=self.root/'source.pdf'
        with fitz.open(created) as doc:
            widget=next(widget for widget in doc[0].widgets() if widget.field_name=='choice')
            doc.xref_set_key(widget.xref,'Opt','[['+fitz.get_pdf_str(self.composed)+'(First)]['+fitz.get_pdf_str(self.decomposed)+'(Second)]]')
            doc.xref_set_key(widget.xref,'V',fitz.get_pdf_str(self.composed));doc.xref_set_key(widget.xref,'I','[0]')
            doc.save(self.source)
        self.original=self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual(list(self.root.glob('.pdf-output-*')),[])
        self.temporary.cleanup()

    def records(self,source):
        target=self.root/('inspect-'+str(len(list(self.root.glob('inspect-*'))))+'.json')
        run('forms',[source],target)
        return json.loads(target.read_text())

    def test_inspection_retains_distinct_names_and_choice_labels(self):
        records=self.records(self.source)
        self.assertIn(self.composed,[item['name'] for item in records]);self.assertIn(self.decomposed,[item['name'] for item in records])
        choice=next(item for item in records if item['name']=='choice')
        self.assertEqual(choice['choice_items'],[{'value':self.composed,'label':'First'},{'value':self.decomposed,'label':'Second'}])
        self.assertEqual(choice['choices'],[self.composed,self.decomposed])
        radio=next(item for item in records if item['name']=='radio')
        self.assertEqual([item['value'] for item in radio['choice_items']],[self.composed,self.decomposed])

    def test_array_updates_distinct_names_choices_radio_and_checkbox(self):
        target=self.root/'filled.pdf'
        values=[{'name':self.composed,'value':'First updated'}, {'name':self.decomposed,'value':'Second updated'},
                {'name':'choice','value':self.decomposed},{'name':'radio','value':self.decomposed},{'name':'check','value':True}]
        run('form-fill',[self.source],target,{'value_entries':values})
        records={item['name']:item for item in self.records(target)}
        self.assertEqual(records[self.composed]['value'],'First updated');self.assertEqual(records[self.decomposed]['value'],'Second updated')
        self.assertEqual(records['choice']['value'],self.decomposed);self.assertEqual(records['radio']['value'],self.decomposed)
        self.assertEqual(records['check']['value'],'Yes')
        with fitz.open(target) as doc:
            self.assertIn('Second',doc[0].get_text())
            self.assertEqual(next(widget for widget in doc[0].widgets() if widget.field_name=='choice').choice_values,[(self.composed,'First'),(self.decomposed,'Second')])

    def test_legacy_dictionary_remains_compatible(self):
        target=self.root/'legacy.pdf';run('form-fill',[self.source],target,{'values':{self.composed:'Legacy updated'}})
        records={item['name']:item for item in self.records(target)}
        self.assertEqual(records[self.composed]['value'],'Legacy updated');self.assertEqual(records[self.decomposed]['value'],'Second original')

    def test_invalid_or_duplicate_entries_and_mixed_payload_are_atomic(self):
        payloads=[{'value_entries':[]},{'value_entries':{}},{'value_entries':[False]},
                  {'value_entries':[{'name':True,'value':'x'}]}, {'value_entries':[{'name':'choice'}]},
                  {'value_entries':[{'name':'choice','value':'x','extra':1}]},
                  {'value_entries':[{'name':self.composed,'value':'x'},{'name':self.composed,'value':'y'}]},
                  {'value_entries':[{'name':self.composed,'value':'x'}],'values':{self.decomposed:'y'}},
                  {'value_entries':[{'name':self.composed,'value':'x'},{'name':'missing','value':'y'}]}]
        for index,payload in enumerate(payloads):
            with self.subTest(payload=payload):
                target=self.root/f'invalid-{index}.pdf'
                with self.assertRaises(ValueError):run('form-fill',[self.source],target,payload)
                self.assertFalse(target.exists())

    def test_array_does_not_bypass_font_or_readonly_validation(self):
        with self.assertRaisesRegex(ValueError,'Latin-1'):
            run('form-fill',[self.source],self.root/'bad-font.pdf',{'value_entries':[{'name':self.composed,'value':self.decomposed}]})
        self.assertFalse((self.root/'bad-font.pdf').exists())
        protected=self.root/'readonly.pdf'
        with fitz.open(self.source) as doc:
            page=doc[0];widget=next(widget for widget in page.widgets() if widget.field_name==self.decomposed)
            widget.field_flags|=1;widget.update();doc.save(protected)
        original=protected.read_bytes()
        with self.assertRaisesRegex(ValueError,'somente leitura'):
            run('form-fill',[protected],self.root/'readonly-output.pdf',{'value_entries':[{'name':self.composed,'value':'valid'},{'name':self.decomposed,'value':'blocked'}]})
        self.assertFalse((self.root/'readonly-output.pdf').exists());self.assertEqual(protected.read_bytes(),original)


if __name__=='__main__':unittest.main()
