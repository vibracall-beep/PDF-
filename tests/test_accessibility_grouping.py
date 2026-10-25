"""Real marked content is regrouped without rewriting its page or MCID owner."""
import hashlib
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


def tagged_cells(root):
    """Four independent content streams share an inherited page reference."""
    plain=root/'cells-source.pdf';target=root/'cells-tagged.pdf'
    with fitz.open() as document:
        page=document.new_page(width=400,height=240)
        for x,y,text in ((40,60,'Product'),(210,60,'Quantity'),(40,120,'Apple'),(210,120,'12')):
            page.insert_text((x,y),text,fontsize=16)
        document.save(plain)
    with plain.open('rb') as source:
        writer=IncrementalPdfFileWriter(source);page_ref,_=writer.find_page_for_modification(0);page=page_ref.get_object()
        tree=g.DictionaryObject({g.pdf_name('/Type'):g.pdf_name('/StructTreeRoot')});tree_ref=writer.add_object(tree)
        parent=g.DictionaryObject({g.pdf_name('/Type'):g.pdf_name('/StructElem'),g.pdf_name('/S'):g.pdf_name('/Document'),
            g.pdf_name('/P'):tree_ref,g.pdf_name('/Pg'):page_ref});parent_ref=writer.add_object(parent)
        children=[];streams=[]
        for index,content in enumerate(accessibility._array(accessibility._raw(page,'/Contents'))):
            role='TH' if index<2 else 'TD'
            leaf=g.DictionaryObject({g.pdf_name('/Type'):g.pdf_name('/StructElem'),g.pdf_name('/S'):g.pdf_name('/'+role),
                g.pdf_name('/P'):parent_ref,g.pdf_name('/K'):g.NumberObject(index)})
            if role=='TH':
                leaf[g.pdf_name('/A')]=g.DictionaryObject({g.pdf_name('/O'):g.pdf_name('/Table'),g.pdf_name('/Scope'):g.pdf_name('/Column')})
            children.append(writer.add_object(leaf))
            streams.extend([writer.add_object(g.StreamObject(stream_data=f'/{role} <</MCID {index}>> BDC\n'.encode())),
                            content,writer.add_object(g.StreamObject(stream_data=b'\nEMC\n'))])
        parent[g.pdf_name('/K')]=g.ArrayObject(children)
        tree[g.pdf_name('/K')]=g.ArrayObject([parent_ref])
        tree[g.pdf_name('/ParentTree')]=writer.add_object(g.DictionaryObject({g.pdf_name('/Nums'):g.ArrayObject([
            g.NumberObject(0),g.ArrayObject(children)])}))
        tree[g.pdf_name('/ParentTreeNextKey')]=g.NumberObject(1)
        page[g.pdf_name('/StructParents')]=g.NumberObject(0);page[g.pdf_name('/Contents')]=g.ArrayObject(streams);writer.mark_update(page_ref)
        writer.root[g.pdf_name('/StructTreeRoot')]=tree_ref
        writer.root[g.pdf_name('/MarkInfo')]=g.DictionaryObject({g.pdf_name('/Marked'):g.BooleanObject(True)})
        writer.root[g.pdf_name('/Lang')]=g.pdf_string('en');writer.update_root()
        with target.open('xb') as output:writer.write(output)
    return target


class AccessibilityGroupingTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.source=tagged_cells(self.root);self.before=self.source.read_bytes()
        self.report=accessibility.inspect_pdf(self.source,self.root/'source.json')
        self.leaves=self.report['nodes'][1:];self.identities=[node['id'] for node in self.leaves]
    def tearDown(self):self.temporary.cleanup()
    def apply(self,groups,**options):
        output=self.root/'result.pdf'
        accessibility.remediate_pdf(self.source,output,dict(input_sha256=self.report['input_sha256'],groups=groups,**options))
        return output
    def assert_preserved(self,before,after):
        with fitz.open(before) as original,fitz.open(after) as result:
            self.assertEqual(len(original),len(result))
            for a,b in zip(original,result):
                self.assertEqual(a.get_text(),b.get_text());self.assertEqual(a.get_pixmap().samples,b.get_pixmap().samples)
                self.assertEqual([original.xref_stream(ref) for ref in a.get_contents()],
                                 [result.xref_stream(ref) for ref in b.get_contents()])
        with before.open('rb') as a,after.open('rb') as b:
            original=PdfFileReader(a);result=PdfFileReader(b)
            for reader in (original,result):
                _,nodes,index,_=accessibility._tree(reader);accessibility._validate_parent_links(reader,nodes,index)
            for reader in (original,result):
                nums=reader.root['/StructTreeRoot']['/ParentTree']['/Nums']
                self.assertEqual(int(nums[0]),0)
                self.assertEqual([accessibility._id(ref) for ref in nums[1]],self.identities)
                _,nodes,_,_=accessibility._tree(reader)
                by_id={node['id']:node for node in nodes}
                for leaf in self.leaves:
                    self.assertEqual(by_id[leaf['id']]['page'],1)
                    self.assertEqual(by_id[leaf['id']]['content'],leaf['content'])
    def test_rows_then_table_preserve_pixels_streams_parent_tree_and_inherited_page(self):
        rows=self.apply([dict(children=self.identities[:2],role='TR'),dict(children=self.identities[2:],role='TR')])
        report=accessibility.inspect_pdf(rows,self.root/'rows.json');row_ids=[node['id'] for node in report['nodes'] if node['role']=='TR']
        target=self.root/'table.pdf'
        accessibility.remediate_pdf(rows,target,dict(input_sha256=report['input_sha256'],groups=[dict(children=row_ids,role='Table',title='Inventory')]))
        tree=accessibility.inspect_pdf(target,self.root/'table.json')
        self.assertEqual([node['role'] for node in tree['nodes']],['Document','Table','TR','TH','TH','TR','TD','TD'])
        self.assertEqual(tree['nodes'][1]['title'],'Inventory');self.assertIsNone(tree['pdfua_conformant'])
        self.assert_preserved(self.source,target);self.assertEqual(self.source.read_bytes(),self.before)
    def test_reordered_siblings_can_be_grouped_in_the_explicit_reviewed_order(self):
        parent=self.report['nodes'][0];order=[self.identities[1],self.identities[0],*self.identities[2:]]
        target=self.apply([dict(children=order[:2],role='TR')],edits=[dict(id=parent['id'],children=order)])
        report=accessibility.inspect_pdf(target,self.root/'ordered.json')
        self.assertEqual(report['nodes'][1]['children'],order[:2]);self.assert_preserved(self.source,target)
    def test_noncontiguous_duplicate_unknown_and_incompatible_groups_refuse_without_output(self):
        invalid=[None,{},[dict(children=[],role='Sect')],[dict(children=[self.identities[0],self.identities[2]],role='TR')],
            [dict(children=self.identities[:2],role='Table')],[dict(children=self.identities[:2],role='Figure')],
            [dict(children=[self.identities[0]]*2,role='TR')],[dict(children=['999:0'],role='Sect')],
            [dict(children=self.identities[:2],role='TR',unexpected=True)],
            [dict(children=self.identities[:2],role='TR'),dict(children=self.identities[1:3],role='TR')]]
        for groups in invalid:
            with self.subTest(groups=groups),self.assertRaises(ValueError):self.apply(groups)
            self.assertFalse((self.root/'result.pdf').exists());self.assertEqual(self.source.read_bytes(),self.before)
    def test_groups_from_different_parents_are_refused(self):
        rows=self.apply([dict(children=self.identities[:2],role='TR'),dict(children=self.identities[2:],role='TR')])
        report=accessibility.inspect_pdf(rows,self.root/'rows.json');output=self.root/'invalid.pdf'
        with self.assertRaisesRegex(ValueError,'mesmo pai'):
            accessibility.remediate_pdf(rows,output,dict(input_sha256=report['input_sha256'],
                groups=[dict(children=[self.identities[0],self.identities[2]],role='Sect')]))
        self.assertFalse(output.exists())
    def test_parent_backlink_mismatch_blocks_all_corrections(self):
        broken=self.root/'broken.pdf'
        with self.source.open('rb') as source:
            writer=IncrementalPdfFileWriter(source);_,_,index,_=accessibility._tree(writer)
            ref,node=index[self.identities[0]];node[g.pdf_name('/P')]=ref;writer.mark_update(ref)
            with broken.open('xb') as output:writer.write(output)
        for options in (dict(language='pt-BR'),dict(groups=[dict(children=self.identities[:2],role='TR')])):
            with self.assertRaisesRegex(ValueError,'/P e /K'):
                accessibility.remediate_pdf(broken,self.root/'invalid.pdf',dict(input_sha256=hashlib.sha256(broken.read_bytes()).hexdigest(),**options))
            self.assertFalse((self.root/'invalid.pdf').exists())
    def test_existing_destination_and_stale_source_are_never_replaced(self):
        with self.assertRaises(ValueError):
            accessibility.remediate_pdf(self.source,self.root/'invalid.pdf',dict(input_sha256='0'*64,groups=[dict(children=self.identities[:2],role='TR')]))
        with self.assertRaises(FileExistsError):
            accessibility.remediate_pdf(self.source,self.source,dict(input_sha256=self.report['input_sha256'],groups=[dict(children=self.identities[:2],role='TR')]))
        self.assertEqual(self.source.read_bytes(),self.before);self.assertFalse((self.root/'invalid.pdf').exists())


if __name__=='__main__':unittest.main()
