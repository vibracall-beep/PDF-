import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import fitz
from pyhanko.pdf_utils import generic as g
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
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

    def assert_content_identical(self,before,after):
        with fitz.open(before) as original,fitz.open(after) as result:
            self.assertEqual(len(original),len(result))
            for left,right in zip(original,result):
                self.assertEqual(left.get_text(),right.get_text())
                self.assertEqual(left.get_pixmap().samples,right.get_pixmap().samples)
                self.assertEqual([original.xref_stream(x) for x in left.get_contents()],
                                 [result.xref_stream(x) for x in right.get_contents()])

    def test_role_only_edit_does_not_introduce_empty_replacement_text(self):
        tagged=self.create();source_bytes=tagged.read_bytes();report=self.inspect(tagged)
        paragraph=report['nodes'][1];out=self.root/'heading.pdf'
        self.assertNotIn('actual_text',paragraph['present_fields'])
        accessibility.remediate_pdf(tagged,out,{'input_sha256':report['input_sha256'],
            'edits':[{'id':paragraph['id'],'role':'H2'}]})
        result=self.inspect(out)['nodes'][1]
        self.assertEqual(result['role'],'H2');self.assertEqual(result['present_fields'],[])
        self.assertEqual(result['content'],paragraph['content'])
        with out.open('rb') as stream:
            _,_,index,_=accessibility._tree(PdfFileReader(stream))
            node=index[paragraph['id']][1]
            for key in ('/ActualText','/Alt','/T','/Lang'):self.assertNotIn(key,node)
        self.assert_content_identical(tagged,out)
        self.assertEqual(source_bytes,tagged.read_bytes())

    def test_absent_empty_and_explicit_removal_are_distinct(self):
        tagged=self.create();report=self.inspect(tagged);identity=report['nodes'][1]['id']
        empty=self.root/'deliberate-empty.pdf'
        accessibility.remediate_pdf(tagged,empty,{'input_sha256':report['input_sha256'],
            'edits':[{'id':identity,'actual_text':'','alt':'','title':'','language':'pt-BR'}]})
        empty_report=self.inspect(empty)
        self.assertEqual(set(empty_report['nodes'][1]['present_fields']),{'actual_text','alt','title','language'})
        changed=self.root/'empty-preserved.pdf'
        accessibility.remediate_pdf(empty,changed,{'input_sha256':empty_report['input_sha256'],
            'edits':[{'id':identity,'role':'H2'}]})
        with changed.open('rb') as stream:
            _,_,index,_=accessibility._tree(PdfFileReader(stream));node=index[identity][1]
            for key in ('/ActualText','/Alt','/T'):
                self.assertIn(key,node);self.assertEqual(node[key],'')
            self.assertEqual(node['/Lang'],'pt-BR')
        changed_report=self.inspect(changed);removed=self.root/'removed.pdf'
        accessibility.remediate_pdf(changed,removed,{'input_sha256':changed_report['input_sha256'],
            'edits':[{'id':identity,'actual_text':None,'alt':None,'title':None,'language':None}]})
        self.assertEqual(self.inspect(removed)['nodes'][1]['present_fields'],[])
        self.assert_content_identical(tagged,removed)

    def test_removal_is_local_and_literal_text_is_not_normalized(self):
        tagged=self.create();report=self.inspect(tagged);identity=report['nodes'][1]['id']
        initial=self.root/'alternatives.pdf'
        accessibility.remediate_pdf(tagged,initial,{'input_sha256':report['input_sha256'],'edits':[
            {'id':identity,'actual_text':'Read this instead','alt':'Descrição é','title':'Título','language':'pt-BR'}]})
        initial_bytes=initial.read_bytes();initial_report=self.inspect(initial);out=self.root/'local-removal.pdf'
        accessibility.remediate_pdf(initial,out,{'input_sha256':initial_report['input_sha256'],'edits':[
            {'id':identity,'actual_text':None,'alt':'Descrição e\u0301'}]})
        node=self.inspect(out)['nodes'][1]
        self.assertNotIn('actual_text',node['present_fields'])
        self.assertEqual(node['alt'].encode(), 'Descrição e\u0301'.encode())
        self.assertEqual(node['title'],'Título');self.assertEqual(node['language'],'pt-BR')
        # Removing ActualText deliberately restores extraction of the original
        # paragraph; its page streams and rendering must still be unchanged.
        self.assertEqual(initial_bytes,initial.read_bytes());self.assert_content_identical(tagged,out)

    def attribute_fixture(self):
        tagged=self.create();target=self.root/'attributes.pdf'
        with tagged.open('rb') as source:
            writer=IncrementalPdfFileWriter(source);_,nodes,index,_=accessibility._tree(writer)
            table=writer.add_object(g.DictionaryObject({g.pdf_name('/O'):g.pdf_name('/Table'),
                g.pdf_name('/Scope'):g.pdf_name('/Column'),g.pdf_name('/RowSpan'):g.NumberObject(2),
                g.pdf_name('/ColSpan'):g.NumberObject(3),g.pdf_name('/Headers'):g.ArrayObject([g.pdf_string('head-é')])}))
            layout=writer.add_object(g.DictionaryObject({g.pdf_name('/O'):g.pdf_name('/Layout'),
                g.pdf_name('/Placement'):g.pdf_name('/Block')}))
            extra=writer.add_object(g.DictionaryObject({g.pdf_name('/O'):g.pdf_name('/Table'),
                g.pdf_name('/Scope'):g.pdf_name('/Row'),g.pdf_name('/Summary'):g.pdf_string('Keep this attribute')}))
            shared=writer.add_object(g.ArrayObject([table,g.NumberObject(2),layout,g.NumberObject(3),extra,g.NumberObject(5)]))
            for record in nodes[1:]:
                ref,node=index[record['id']];node[g.pdf_name('/S')]=g.pdf_name('/TH');node[g.pdf_name('/A')]=shared
                writer.mark_update(ref)
            with target.open('xb') as destination:writer.write(destination)
        return target

    def test_header_to_data_cell_removes_only_scope_without_mutating_shared_attributes(self):
        tagged=self.attribute_fixture();before=tagged.read_bytes();report=self.inspect(tagged)
        first,second=report['nodes'][1:];out=self.root/'data-cell.pdf'
        accessibility.remediate_pdf(tagged,out,{'input_sha256':report['input_sha256'],
            'edits':[{'id':first['id'],'role':'TD'}]})
        result=self.inspect(out);self.assertEqual(result['nodes'][1]['role'],'TD')
        self.assertIsNone(result['nodes'][1]['scope']);self.assertNotIn('scope',result['nodes'][1]['present_fields'])
        self.assertEqual(result['nodes'][2]['scope'],second['scope'])
        with out.open('rb') as stream:
            _,_,index,_=accessibility._tree(PdfFileReader(stream))
            altered=index[first['id']][1]['/A'];unmodified=index[second['id']][1]['/A']
            self.assertEqual(len(altered),len(unmodified));self.assertEqual(len(altered),6)
            self.assertEqual([int(altered[i]) for i in (1,3,5)],[2,3,5])
            self.assertEqual(altered[2],unmodified[2])
            for i in (0,4):
                self.assertNotIn('/Scope',altered[i]);self.assertIn('/Scope',unmodified[i])
                self.assertEqual(set(altered[i]),set(unmodified[i])-{'/Scope'})
                for key in altered[i]:self.assertEqual(altered[i][key],unmodified[i][key])
            self.assertEqual(altered[0]['/RowSpan'],2);self.assertEqual(altered[0]['/ColSpan'],3)
        self.assertEqual(before,tagged.read_bytes());self.assert_content_identical(tagged,out)

    def test_explicit_scope_change_and_removal_keep_attribute_order_and_revisions(self):
        tagged=self.attribute_fixture();report=self.inspect(tagged);identity=report['nodes'][1]['id']
        changed=self.root/'scope-changed.pdf'
        accessibility.remediate_pdf(tagged,changed,{'input_sha256':report['input_sha256'],'edits':[{'id':identity,'scope':'Both'}]})
        with changed.open('rb') as stream:
            _,_,index,_=accessibility._tree(PdfFileReader(stream));attrs=index[identity][1]['/A']
            self.assertEqual(attrs[0]['/Scope'],'/Both');self.assertEqual(attrs[4]['/Scope'],'/Both')
            self.assertEqual(attrs[2]['/O'],'/Layout');self.assertEqual(attrs[4]['/Summary'],'Keep this attribute')
            self.assertEqual([int(attrs[i]) for i in (1,3,5)],[2,3,5])
        updated=self.inspect(changed);removed=self.root/'scope-removed.pdf'
        accessibility.remediate_pdf(changed,removed,{'input_sha256':updated['input_sha256'],'edits':[{'id':identity,'scope':None}]})
        record=self.inspect(removed)['nodes'][1]
        self.assertEqual(record['role'],'TH');self.assertIsNone(record['scope']);self.assert_content_identical(tagged,removed)

    def test_invalid_optional_edits_refuse_without_output_or_source_change(self):
        tagged=self.create();source_bytes=tagged.read_bytes();report=self.inspect(tagged);identity=report['nodes'][1]['id']
        invalid=[{'scope':'Column'},{'role':'TD','scope':'Row'},{'scope':''},{'scope':False},
                 {'actual_text':False},{'alt':[]},{'title':42},{'language':{}},{'role':[]}]
        for change in invalid:
            with self.subTest(change=change),self.assertRaises(ValueError):
                accessibility.remediate_pdf(tagged,self.root/'refused.pdf',{'input_sha256':report['input_sha256'],
                    'edits':[{'id':identity,**change}]})
            self.assertFalse((self.root/'refused.pdf').exists());self.assertEqual(tagged.read_bytes(),source_bytes)


if __name__=='__main__': unittest.main()
