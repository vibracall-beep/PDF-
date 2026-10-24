"""Source-bound review and external sending must never be generic stages."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run,TOOLS,PDF_OPERATIONS
from workflow_batch import validate_steps,output_type


class WorkflowReviewBoundaries(unittest.TestCase):
    def test_source_bound_edits_and_requests_are_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.pdf'
            with fitz.open() as doc: doc.new_page();doc.save(source)
            operations=['content-apply','ocr-apply','accessibility-remediate','dossier',
                'signature-request-prepare','signature-request-send','signature-request-status']
            for operation in operations:
                for batch in (False,True):
                    with self.subTest(operation=operation,batch=batch),patch('workflow_batch.check_dependencies') as dependencies,self.assertRaises(ValueError):
                        run('workflow',[source],root/'result',{'batch':batch,'steps':[{'operation':operation}]})
                    dependencies.assert_not_called();self.assertFalse((root/'result').exists())

    def test_new_pdf_operations_do_not_get_workflow_permission_implicitly(self):
        with self.assertRaisesRegex(ValueError,'contrato aprovado'):
            validate_steps([{'operation':'future-review-bound-tool'}],{*TOOLS,'future-review-bound-tool'},{*PDF_OPERATIONS,'future-review-bound-tool'})

    def test_inspection_reports_have_json_terminal_types(self):
        for operation in ('content-inspect','ocr-review','accessibility-inspect','print-preflight','measure'):
            with self.subTest(operation=operation):
                self.assertEqual(output_type(operation),('json',False))
                validate_steps([{'operation':'rotate'},{'operation':operation}],TOOLS,PDF_OPERATIONS)
                with self.assertRaises(ValueError): validate_steps([{'operation':operation},{'operation':'rotate'}],TOOLS,PDF_OPERATIONS)

    def test_batch_inspection_publishes_real_json_with_source_bound_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.pdf'
            with fitz.open() as doc: doc.new_page().insert_text((30,50),'Inspectable original');doc.save(source)
            output=root/'batch';run('workflow',[source],output,{'batch':True,'steps':[{'operation':'content-inspect'}]})
            manifest=json.loads((output/'batch-manifest.json').read_text())
            result=output/manifest['results'][0]['output'];self.assertEqual(result.suffix,'.json')
            report=json.loads(result.read_text());self.assertEqual(report['objects'][0]['text'],'Inspectable original')
