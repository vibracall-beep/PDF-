"""Actual PDF structure, opaque header IDs and adversarial table corrections."""
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
import accessibility_tables as tables
from tests.test_accessibility_grouping import tagged_cells


def real_table(root):
    source=tagged_cells(root);report=accessibility.inspect_pdf(source,root/'cells.json')
    ids=[node['id'] for node in report['nodes'][1:]];rows=root/'rows.pdf'
    accessibility.remediate_pdf(source,rows,dict(input_sha256=report['input_sha256'],groups=[
        dict(children=ids[:2],role='TR'),dict(children=ids[2:],role='TR')]))
    report=accessibility.inspect_pdf(rows,root/'rows.json');target=root/'table.pdf'
    accessibility.remediate_pdf(rows,target,dict(input_sha256=report['input_sha256'],groups=[
        dict(children=[node['id'] for node in report['nodes'] if node['role']=='TR'],role='Table')]))
    return target,ids


class AccessibilityTableTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.source,self.ids=real_table(self.root);self.original=self.source.read_bytes();self.serial=0
    def tearDown(self):self.temporary.cleanup()
    def inspect(self,path):
        self.serial+=1;return accessibility.inspect_pdf(path,self.root/f'report-{self.serial}.json')
    def apply(self,edits,source=None):
        source=source or self.source;self.serial+=1;target=self.root/f'output-{self.serial}.pdf'
        accessibility.remediate_pdf(source,target,dict(input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),edits=edits))
        return target
    def mutate(self,callback):
        self.serial+=1;target=self.root/f'mutated-{self.serial}.pdf'
        with self.source.open('rb') as original:
            writer=IncrementalPdfFileWriter(original);tree,nodes,index,_=accessibility._tree(writer)
            callback(writer,tree,nodes,index)
            with target.open('xb') as output:writer.write(output)
        return target
    def assert_content(self,before,after):
        with fitz.open(before) as original,fitz.open(after) as result:
            self.assertEqual(original[0].get_text(),result[0].get_text())
            self.assertEqual(original[0].get_pixmap().samples,result[0].get_pixmap().samples)
            self.assertEqual([original.xref_stream(ref) for ref in original[0].get_contents()],
                             [result.xref_stream(ref) for ref in result[0].get_contents()])
        with before.open('rb') as a,after.open('rb') as b:
            left=PdfFileReader(a);right=PdfFileReader(b)
            for reader in (left,right):
                _,nodes,index,_=accessibility._tree(reader);accessibility._validate_parent_links(reader,nodes,index)
                nums=reader.root['/StructTreeRoot']['/ParentTree']['/Nums']
                self.assertEqual([accessibility._id(ref) for ref in nums[1]],self.ids)
    def assert_rejected(self,edits,source=None):
        source=source or self.source;before=source.read_bytes();target=self.root/'rejected.pdf'
        with self.assertRaises(ValueError):
            accessibility.remediate_pdf(source,target,dict(input_sha256=hashlib.sha256(before).hexdigest(),edits=edits))
        self.assertFalse(target.exists());self.assertEqual(source.read_bytes(),before)

    def test_header_associations_create_real_unique_ids_and_id_tree(self):
        result=self.apply([dict(id=self.ids[2],headers=[self.ids[0]]),dict(id=self.ids[3],headers=[self.ids[1]])])
        records={node['id']:node for node in self.inspect(result)['nodes']}
        self.assertEqual(records[self.ids[2]]['headers'],[self.ids[0]])
        self.assertEqual(records[self.ids[3]]['headers'],[self.ids[1]])
        self.assertIn('headers',records[self.ids[2]]['present_fields'])
        with result.open('rb') as stream:
            reader=PdfFileReader(stream);tree,_,index,_=accessibility._tree(reader)
            by_bytes,by_tag=tables._identifiers(index)
            self.assertEqual(set(by_tag),set(self.ids[:2]));self.assertEqual(len(by_bytes),2)
            tables._read_id_tree(tree,index,by_bytes)
            for header,cell in zip(self.ids[:2],self.ids[2:]):
                self.assertEqual(tables.attributes(index[cell][1])[0]['headers'],[by_tag[header]])
        removed=self.apply([dict(id=self.ids[2],headers=None)],source=result)
        records={node['id']:node for node in self.inspect(removed)['nodes']}
        self.assertEqual(records[self.ids[2]]['headers'],[]);self.assertNotIn('headers',records[self.ids[2]]['present_fields'])
        self.assertEqual(records[self.ids[3]]['headers'],[self.ids[1]])
        self.assert_content(self.source,removed);self.assertEqual(self.source.read_bytes(),self.original)

    def test_column_spans_change_only_selected_shared_attributes_and_keep_revisions(self):
        def shared(writer,tree,nodes,index):
            attribute=writer.add_object(g.DictionaryObject({g.pdf_name('/O'):g.pdf_name('/Table'),
                g.pdf_name('/RowSpan'):g.NumberObject(1),g.pdf_name('/ColSpan'):g.NumberObject(1),
                g.pdf_name('/Summary'):g.pdf_string('Keep the original summary')}))
            layout=writer.add_object(g.DictionaryObject({g.pdf_name('/O'):g.pdf_name('/Layout'),g.pdf_name('/Placement'):g.pdf_name('/Block')}))
            attributes=writer.add_object(g.ArrayObject([attribute,g.NumberObject(2),layout,g.NumberObject(5)]))
            for identity in self.ids:
                ref,node=index[identity];node[g.pdf_name('/A')]=attributes;writer.mark_update(ref)
        source=self.mutate(shared)
        result=self.apply([dict(id=self.ids[0],column_span=2),dict(id=self.ids[2],column_span=2)],source=source)
        with result.open('rb') as stream:
            _,_,index,_=accessibility._tree(PdfFileReader(stream))
            for offset,identity in enumerate(self.ids):
                attributes=index[identity][1]['/A']
                self.assertEqual(int(attributes[0]['/ColSpan']),2 if offset%2==0 else 1)
                self.assertEqual(int(attributes[0]['/RowSpan']),1);self.assertEqual(attributes[0]['/Summary'],'Keep the original summary')
                self.assertEqual([int(attributes[i]) for i in (1,3)],[2,5]);self.assertEqual(attributes[2]['/O'],'/Layout')
        self.assert_content(source,result)

    def test_row_span_repairs_declared_merged_cell_without_moving_its_content(self):
        def merged(writer,tree,nodes,index):
            records={node['id']:node for node in nodes};first_ref,first=index[self.ids[0]];moved_ref,moved=index[self.ids[2]]
            parent_ref,parent=index[records[self.ids[2]]['parent']]
            parent[g.pdf_name('/K')]=g.ArrayObject([index[self.ids[3]][0]]);writer.mark_update(parent_ref)
            first[g.pdf_name('/K')]=g.ArrayObject([g.NumberObject(0),moved_ref]);writer.mark_update(first_ref)
            moved[g.pdf_name('/S')]=g.pdf_name('/P');moved[g.pdf_name('/P')]=first_ref;writer.mark_update(moved_ref)
        source=self.mutate(merged);result=self.apply([dict(id=self.ids[0],row_span=2)],source=source)
        records={node['id']:node for node in self.inspect(result)['nodes']}
        self.assertEqual(records[self.ids[0]]['row_span'],2);self.assertEqual(records[self.ids[2]]['parent'],self.ids[0])
        self.assert_content(source,result)
        self.assert_rejected([dict(id=self.ids[0],row_span=None)],source=result)

    def test_invalid_span_types_overflow_overlap_and_gaps_refuse_without_output(self):
        for value in (0,-1,1001,True,1.5,'2',[],{}):
            with self.subTest(value=value):self.assert_rejected([dict(id=self.ids[0],row_span=value)])
        self.assert_rejected([dict(id=self.ids[0],column_span=2)])
        self.assert_rejected([dict(id=self.ids[0],row_span=2)])
        self.assert_rejected([dict(id=self.ids[2],row_span=2)])

    def test_self_unknown_non_header_duplicate_and_cyclic_associations_refuse(self):
        for headers in ([self.ids[2]],['999:0'],[self.ids[3]],[self.ids[0]]*2,False,'header'):
            with self.subTest(headers=headers):self.assert_rejected([dict(id=self.ids[2],headers=headers)])
        self.assert_rejected([dict(id=self.ids[0],headers=[self.ids[1]]),dict(id=self.ids[1],headers=[self.ids[0]])])

    def test_referenced_header_cannot_change_role_until_its_associations_are_removed(self):
        source=self.apply([dict(id=self.ids[2],headers=[self.ids[0]])])
        self.assert_rejected([dict(id=self.ids[0],role='TD')],source=source)
        result=self.apply([dict(id=self.ids[0],role='TD'),dict(id=self.ids[2],headers=None)],source=source)
        nodes={node['id']:node for node in self.inspect(result)['nodes']}
        self.assertEqual(nodes[self.ids[0]]['role'],'TD');self.assertEqual(nodes[self.ids[2]]['headers'],[])
        self.assert_content(source,result)

    def test_grouping_cannot_insert_a_non_row_container_inside_an_existing_table(self):
        report=self.inspect(self.source);rows=[node['id'] for node in report['nodes'] if node['role']=='TR']
        for role in ('Table','Sect'):
            with self.subTest(role=role),self.assertRaisesRegex(ValueError,'filho estrutural'):
                accessibility.remediate_pdf(self.source,self.root/'invalid-group.pdf',dict(input_sha256=report['input_sha256'],
                    groups=[dict(children=rows,role=role)]))
            self.assertFalse((self.root/'invalid-group.pdf').exists())

    def test_duplicate_structural_ids_and_tampered_name_tree_refuse(self):
        for mode in ('duplicate','wrong-target','unsorted','bad-limits','cycle'):
            def corrupt(writer,tree,nodes,index):
                for identity,key in zip(self.ids[:2],(b'A',b'A' if mode=='duplicate' else b'B')):
                    ref,node=index[identity];node[g.pdf_name('/ID')]=g.ByteStringObject(key);writer.mark_update(ref)
                pairs=[g.ByteStringObject(b'A'),index[self.ids[0]][0],g.ByteStringObject(b'B'),index[self.ids[1]][0]]
                if mode=='wrong-target':pairs[1]=index[self.ids[1]][0]
                if mode=='unsorted':pairs=pairs[2:]+pairs[:2]
                names=g.DictionaryObject({g.pdf_name('/Names'):g.ArrayObject(pairs)})
                if mode=='bad-limits':names[g.pdf_name('/Limits')]=g.ArrayObject([g.ByteStringObject(b'B'),g.ByteStringObject(b'A')])
                ref=writer.add_object(names)
                if mode=='cycle':
                    names.pop('/Names');names[g.pdf_name('/Kids')]=g.ArrayObject([ref])
                tree[g.pdf_name('/IDTree')]=ref;writer.mark_update(accessibility._raw(writer.root,'/StructTreeRoot'))
            with self.subTest(mode=mode):
                source=self.mutate(corrupt);self.assert_rejected([dict(id=self.ids[2],headers=[self.ids[0]])],source=source)

    def test_existing_opaque_ids_remain_byte_exact_in_names_and_headers(self):
        ids=[b'\xfe\xff\x00\xe9',b'\xe9']
        def identifiers(writer,tree,nodes,index):
            for identity,key in zip(self.ids,ids):
                ref,node=index[identity];node[g.pdf_name('/ID')]=g.ByteStringObject(key);writer.mark_update(ref)
        source=self.mutate(identifiers);result=self.apply([dict(id=self.ids[2],headers=self.ids[:2])],source=source)
        with result.open('rb') as stream:
            reader=PdfFileReader(stream);tree,_,index,_=accessibility._tree(reader)
            by_bytes,by_tag=tables._identifiers(index);self.assertEqual([by_tag[identity] for identity in self.ids[:2]],ids)
            self.assertEqual(tables.attributes(index[self.ids[2]][1])[0]['headers'],ids)
            tables._read_id_tree(tree,index,by_bytes)
        self.assert_content(source,result)

    def test_name_tree_scales_to_multiple_leaves_without_dropping_existing_ids(self):
        def many_ids(writer,tree,nodes,index):
            document=nodes[0]['id'];ref,parent=index[document];children=accessibility._array(accessibility._raw(parent,'/K'))
            for number in range(70):
                child=g.DictionaryObject({g.pdf_name('/Type'):g.pdf_name('/StructElem'),g.pdf_name('/S'):g.pdf_name('/Span'),
                    g.pdf_name('/P'):ref,g.pdf_name('/ID'):g.ByteStringObject(f'Existing-{number:03}'.encode())})
                children.append(writer.add_object(child))
            parent[g.pdf_name('/K')]=g.ArrayObject(children);writer.mark_update(ref)
        source=self.mutate(many_ids);result=self.apply([dict(id=self.ids[2],headers=[self.ids[0]])],source=source)
        with result.open('rb') as stream:
            tree,_,index,_=accessibility._tree(PdfFileReader(stream));by_bytes,_=tables._identifiers(index)
            self.assertEqual(len(by_bytes),71);self.assertEqual(len(tree['/IDTree']['/Kids']),2)
            tables._read_id_tree(tree,index,by_bytes)
        self.assert_content(source,result)

    def test_span_and_headers_require_a_declared_table_structure(self):
        ungrouped=self.root/'cells-tagged.pdf'
        self.assert_rejected([dict(id=self.ids[0],row_span=1)],source=ungrouped)
        self.assert_rejected([dict(id=self.ids[2],headers=[self.ids[0]])],source=ungrouped)

    def test_header_from_another_table_and_mixed_container_content_are_refused(self):
        def separate(writer,tree,nodes,index):
            records={node['id']:node for node in nodes};document=nodes[0]['id'];doc_ref,doc=index[document]
            rows=[node['id'] for node in nodes if node['role']=='TR'];new_tables=[]
            for row in rows:
                row_ref,row_node=index[row]
                table=g.DictionaryObject({g.pdf_name('/Type'):g.pdf_name('/StructElem'),g.pdf_name('/S'):g.pdf_name('/Table'),
                    g.pdf_name('/P'):doc_ref,g.pdf_name('/K'):g.ArrayObject([row_ref])})
                ref=writer.add_object(table);new_tables.append(ref);row_node[g.pdf_name('/P')]=ref;writer.mark_update(row_ref)
            doc[g.pdf_name('/K')]=g.ArrayObject(new_tables);writer.mark_update(doc_ref)
        source=self.mutate(separate);self.assert_rejected([dict(id=self.ids[2],headers=[self.ids[0]])],source=source)
        def mixed(writer,tree,nodes,index):
            table=next(node for node in nodes if node['role']=='Table');ref,obj=index[table['id']]
            obj[g.pdf_name('/K')]=g.ArrayObject([*accessibility._array(accessibility._raw(obj,'/K')),g.NumberObject(0)]);writer.mark_update(ref)
        source=self.mutate(mixed);self.assert_rejected([dict(id=self.ids[2],column_span=1)],source=source)


if __name__=='__main__':unittest.main()
