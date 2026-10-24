import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import fitz
from pyhanko.pdf_utils import generic as g
from pyhanko.pdf_utils.reader import PdfFileReader

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
import pdf_accessibility as accessibility


class AccessibilityRemediationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.source=self.root/'original.pdf'
        with fitz.open() as doc:
            for text in ('Título em português','A meaningful second paragraph'):
                page=doc.new_page();page.insert_text((40,60),text)
            doc.save(self.source)
        self.original=self.source.read_bytes()

    def tearDown(self): self.temporary.cleanup()
    def inspect(self,path):
        report=self.root/f'{path.stem}-report.json'
        return accessibility.inspect_pdf(path,report)
    def create(self):
        target=self.root/'tagged.pdf'
        accessibility.remediate_pdf(self.source,target,{'input_sha256':hashlib.sha256(self.original).hexdigest(),
            'language':'pt-BR','create_page_tags':[{'page':2,'role':'P'},{'page':1,'role':'H1'}]})
        return target

    def test_manual_page_tagging_preserves_render_and_content_and_real_parent_tree(self):
        tagged=self.create();report=self.inspect(tagged)
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual([n['page'] for n in report['nodes'][1:]],[2,1])
        self.assertTrue(report['manual_review_required']);self.assertIsNone(report['pdfua_conformant'])
        with fitz.open(self.source) as before,fitz.open(tagged) as after:
            for a,b in zip(before,after):
                self.assertEqual(a.get_text(),b.get_text())
                self.assertEqual(a.get_pixmap().samples,b.get_pixmap().samples)
        with tagged.open('rb') as stream:
            pdf=PdfFileReader(stream);tree=pdf.root['/StructTreeRoot']
            nums=list(tree['/ParentTree']['/Nums'])
            self.assertEqual([int(nums[0]),int(nums[2])],[0,1])
            for index in (0,1):
                page=pdf.find_page_for_modification(index)[0].get_object()
                self.assertEqual(page['/StructParents'],index)
                self.assertEqual(nums[index*2+1][0]['/K'],0)

    def test_edit_roles_alt_and_order_without_reassigning_mcids(self):
        tagged=self.create();report=self.inspect(tagged);nodes=report['nodes'];out=self.root/'edited.pdf'
        accessibility.remediate_pdf(tagged,out,{'input_sha256':report['input_sha256'],'edits':[
            {'id':nodes[0]['id'],'children':list(reversed(nodes[0]['children']))},
            {'id':nodes[1]['id'],'role':'Figure','alt':'Gráfico das vendas: aumento de 20%.'},
            {'id':nodes[2]['id'],'role':'H2','title':'Seção principal'}]})
        result=self.inspect(out)
        self.assertEqual([n['page'] for n in result['nodes'][1:]],[1,2])
        self.assertEqual(result['nodes'][1]['role'],'H2')
        self.assertIn('20%',result['nodes'][2]['alt'])
        self.assertEqual(result['nodes'][2]['content'],nodes[1]['content'])

    def test_stale_digest_and_duplicate_or_missing_page_mapping_refused(self):
        for spec in ([{'page':1,'role':'P'}],[{'page':1,'role':'P'}]*2):
            with self.assertRaises(ValueError):
                accessibility.remediate_pdf(self.source,self.root/'no.pdf',{'input_sha256':hashlib.sha256(self.original).hexdigest(),'create_page_tags':spec})
        with self.assertRaises(ValueError):
            accessibility.remediate_pdf(self.source,self.root/'no.pdf',{'input_sha256':'0'*64})
        self.assertFalse((self.root/'no.pdf').exists())

    def test_reorder_cannot_drop_duplicate_or_move_other_content(self):
        tagged=self.create();report=self.inspect(tagged);root=report['nodes'][0]
        for children in ([root['children'][0]],[root['children'][0]]*2,['999:0',root['children'][0]]):
            with self.assertRaises(ValueError): accessibility.remediate_pdf(tagged,self.root/'no.pdf',{
                'input_sha256':report['input_sha256'],'edits':[{'id':root['id'],'children':children}]})
        self.assertFalse((self.root/'no.pdf').exists())

    def test_table_header_scope_preserves_other_structure(self):
        tagged=self.create();report=self.inspect(tagged);node=report['nodes'][1];out=self.root/'table-header.pdf'
        accessibility.remediate_pdf(tagged,out,{'input_sha256':report['input_sha256'],'edits':[{'id':node['id'],'role':'TH','scope':'Column'}]})
        result=self.inspect(out);self.assertEqual(result['nodes'][1]['scope'],'Column')
        self.assertEqual(result['nodes'][1]['content'],node['content'])
        # This intentionally incomplete table is not declared conformant.
        self.assertIsNone(result['pdfua_conformant'])

    def test_tagged_creation_and_existing_output_are_not_overwritten(self):
        tagged=self.create();before=tagged.read_bytes();report=self.inspect(tagged)
        with self.assertRaises(ValueError): accessibility.remediate_pdf(tagged,self.root/'new.pdf',{
            'input_sha256':report['input_sha256'],'create_page_tags':[{'page':1},{'page':2}]})
        with self.assertRaises(FileExistsError): accessibility.remediate_pdf(tagged,tagged,{
            'input_sha256':report['input_sha256'],'language':'en'})
        self.assertEqual(before,tagged.read_bytes())


if __name__=='__main__': unittest.main()
