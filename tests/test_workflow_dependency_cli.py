"""Exercise the real, bounded dependency-only CLI used by the native launcher."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ENGINE = Path(__file__).resolve().parents[1] / 'engine/pdf_engine.py'


class WorkflowDependencyCLITests(unittest.TestCase):
    def invoke(self, payload, *arguments):
        environment = dict(os.environ)
        environment.pop('PDF_OPTIONS_STDIN', None)
        return subprocess.run([sys.executable, str(ENGINE), '--check-workflow-dependencies', *arguments],
                              input=payload, capture_output=True, timeout=15, env=environment)

    def test_valid_steps_do_not_create_a_document(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'must-not-exist.pdf'
            result = self.invoke(json.dumps([{'operation': 'rotate', 'options': {'degrees': 90,
                'output': str(target)}}]).encode())
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(json.loads(result.stdout), {'ok': True, 'dependencies_checked': True})
            self.assertFalse(target.exists())

    def test_invalid_structure_and_recursive_or_review_bound_steps_are_refused(self):
        for payload in [None, {}, [], ['rotate'], [{'operation': 'unknown'}],
                        [{'operation': 'workflow'}], [{'operation': 'content-apply'}],
                        [{'operation': 'signature-request-send'}], [{'operation': 'rotate', 'options': []}]]:
            with self.subTest(payload=payload):
                result = self.invoke(json.dumps(payload).encode())
                self.assertEqual(result.returncode, 1)
                self.assertFalse(json.loads(result.stderr)['ok'])

    def test_export_must_be_terminal(self):
        result = self.invoke(b'[{"operation":"word"},{"operation":"rotate"}]')
        self.assertEqual(result.returncode, 1)

    def test_operation_or_output_cannot_be_combined_with_probe(self):
        for arguments in [('rotate',), ('--output', 'output.pdf'), ('--capabilities',),
                          ('--options', '[{"operation":"rotate"}]')]:
            with self.subTest(arguments=arguments):
                result = self.invoke(b'[{"operation":"rotate"}]', *arguments)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(json.loads(result.stderr)['ok'])

    def test_oversized_or_malformed_input_is_refused_without_echo(self):
        for payload in [b' ' * (1024 * 1024 + 1), b'not-json-private-value', b'\xff']:
            with self.subTest(size=len(payload)):
                result = self.invoke(payload)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(json.loads(result.stderr)['ok'])
                self.assertNotIn(b'private-value', result.stderr)


if __name__ == '__main__':
    unittest.main()
