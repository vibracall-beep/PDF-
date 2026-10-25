"""Independent veraPDF check after manual tags; never infer semantic compliance."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
import pdf_accessibility
import pdf_standards
from tests.test_accessibility_grouping import tagged_cells
from tests.test_accessibility_tables import real_table


class AccessibilityIndependentValidation(unittest.TestCase):
    def test_merged_cells_and_header_associations_pass_structural_check_without_fabricating_pdfua(self):
        from pdf_engine import run
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source,ids=real_table(root);original=source.read_bytes();target=root/'headers.pdf'
            run('accessibility-remediate',[source],target,dict(input_sha256=hashlib.sha256(original).hexdigest(),edits=[
                dict(id=ids[0],column_span=2),dict(id=ids[2],column_span=2,headers=[ids[0]]),dict(id=ids[3],headers=[ids[1]])]))
            checked=subprocess.run(['qpdf','--check',str(target)],text=True,capture_output=True,timeout=30)
            self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
            tree=pdf_accessibility.inspect_pdf(target,root/'tree.json');records={node['id']:node for node in tree['nodes']}
            self.assertEqual(records[ids[0]]['column_span'],2);self.assertEqual(records[ids[2]]['headers'],[ids[0]])
            self.assertEqual(records[ids[3]]['headers'],[ids[1]])
            report=pdf_standards.validate_pdf(target,root/'validation.json',{'flavour':'ua1'},standard='pdfua')
            self.assertFalse(report['compliant']);self.assertGreater(report['counts']['failedRules'],0)
            self.assertTrue(report['manual_review_required']);self.assertFalse(report['accessibility_certified'])
            self.assertIn('veraPDF',report['validator']['name']);self.assertEqual(source.read_bytes(),original)

    def test_explicit_row_and_table_reconstruction_still_requires_independent_pdfua_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=tagged_cells(root)
            inspected=pdf_accessibility.inspect_pdf(source,root/'source.json')
            ids=[node['id'] for node in inspected['nodes'][1:]];rows=root/'rows.pdf'
            pdf_accessibility.remediate_pdf(source,rows,dict(input_sha256=inspected['input_sha256'],groups=[
                dict(children=ids[:2],role='TR'),dict(children=ids[2:],role='TR')]))
            inspected=pdf_accessibility.inspect_pdf(rows,root/'rows.json');table=root/'table.pdf'
            pdf_accessibility.remediate_pdf(rows,table,dict(input_sha256=inspected['input_sha256'],groups=[
                dict(children=[node['id'] for node in inspected['nodes'] if node['role']=='TR'],role='Table')]))
            report=pdf_standards.validate_pdf(table,root/'validation.json',{'flavour':'ua1'},standard='pdfua')
            self.assertTrue(report['accessibility_preflight']['has_structure_tree'])
            self.assertFalse(report['compliant']);self.assertGreater(report['counts']['failedRules'],0)
            self.assertTrue(report['manual_review_required']);self.assertFalse(report['accessibility_certified'])
            self.assertIn('veraPDF',report['validator']['name'])

    def test_remediated_structure_is_reported_but_incomplete_pdfua_is_not_certified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'original.pdf';target=root/'tagged.pdf'
            with fitz.open() as document:
                document.new_page().insert_text((40,60),'Manually identified heading')
                document.save(source)
            pdf_accessibility.remediate_pdf(source,target,{'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                'language':'en','create_page_tags':[{'page':1,'role':'H1'}]})
            report=pdf_standards.validate_pdf(target,root/'validation.json',{'flavour':'ua1'},standard='pdfua')
            self.assertTrue(report['accessibility_preflight']['has_structure_tree'])
            self.assertTrue(report['accessibility_preflight']['marked'])
            self.assertEqual(report['accessibility_preflight']['document_language'],'en')
            self.assertFalse(report['compliant'])
            self.assertGreater(report['counts']['failedRules'],0)
            self.assertTrue(report['manual_review_required'])
            self.assertFalse(report['accessibility_certified'])
            self.assertIn('veraPDF',report['validator']['name'])

if __name__=='__main__':unittest.main()
