"""Validate AX report failures independently of the producer's findings list."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import check_accessibility_report as accessibility


class AccessibilityReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf accessibility report ')
        self.root = Path(self.temporary.name)
        self.path = self.root / 'report.json'
        self.report = {
            'version': 1, 'scope': 'current-process-own-window',
            'traversalLimited': False, 'missingRequiredIdentifiers': [], 'findings': [],
            'nodes': [{'index': 0, 'role': 'AXButton', 'identifier': 'pdf.save', 'name': 'Salvar cópia'}],
        }
        self.path.write_text(json.dumps(self.report))

    def tearDown(self):
        self.temporary.cleanup()

    def check(self, report):
        with redirect_stdout(io.StringIO()):
            return accessibility.check(self.path, report=report)

    def test_complete_report_and_review_only_findings_remain_valid(self):
        self.assertTrue(self.check(self.report))
        self.report['findings'] = [{'code': 'unnamed-control-review', 'detail': 'Framework-owned control'}]
        self.assertTrue(self.check(self.report))

    def test_incomplete_or_malformed_report_cannot_be_accepted(self):
        changes = [
            ('version', True), ('traversalLimited', None), ('traversalLimited', 'false'),
            ('missingRequiredIdentifiers', None), ('missingRequiredIdentifiers', [1]),
            ('findings', None), ('findings', ['traversal-limit']), ('nodes', None),
            ('nodes', [{'index': 0, 'role': 'AXButton', 'identifier': 'pdf.save'}]),
            ('nodes', self.report['nodes'] * 2),
        ]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                report = dict(self.report); report[key] = value
                with self.assertRaises(ValueError): self.check(report)
        for key in ('traversalLimited', 'missingRequiredIdentifiers', 'findings', 'nodes'):
            with self.subTest(missing=key):
                report = dict(self.report); del report[key]
                with self.assertRaises(ValueError): self.check(report)

    def test_empty_tree_and_failure_flags_fail_without_findings(self):
        for key, value in [('nodes', []), ('traversalLimited', True), ('missingRequiredIdentifiers', ['pdf.save'])]:
            with self.subTest(key=key):
                report = dict(self.report); report[key] = value
                self.assertFalse(self.check(report))

    def test_cli_rejects_symlink_and_fifo_without_blocking(self):
        linked = self.root / 'linked.json'; linked.symlink_to(self.path)
        fifo = self.root / 'pipe.json'; os.mkfifo(fifo)
        script = str(Path(accessibility.__file__).resolve())
        for path in (linked, fifo):
            with self.subTest(path=path.name):
                result = subprocess.run([sys.executable, script, str(path)], capture_output=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)

    def test_oversized_report_is_rejected_before_json_decoding(self):
        with self.path.open('wb') as stream:
            stream.truncate(accessibility.MAX_REPORT_BYTES + 1)
        with self.assertRaisesRegex(ValueError, '16 MB'):
            accessibility.read_report(self.path)


if __name__ == '__main__':
    unittest.main()
