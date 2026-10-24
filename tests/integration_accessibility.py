"""Independent veraPDF check after manual tags; never infer semantic compliance."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
import pdf_accessibility
import pdf_standards


class AccessibilityIndependentValidation(unittest.TestCase):
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
