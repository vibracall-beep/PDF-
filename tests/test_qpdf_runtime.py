"""The encrypted runtime smoke must fail closed without exposing its stdin."""
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'engine')]
from check_runtime import check_qpdf_crypto


class QPDFRuntimeFailureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='PDF crypto private stdin ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'plain.pdf'
        with fitz.open() as document:
            document.new_page().insert_text((72, 72), 'PDF portable verification')
            document.save(self.source)

    def test_actual_child_receives_private_regular_stdin_and_failure_never_echoes_credentials(self):
        script = self.root / 'fake backend.py'
        report = self.root / 'transport.json'
        script.write_text('import json,os,stat,sys\nfrom pathlib import Path\n'
            'options=json.load(sys.stdin)\n'
            'Path(' + repr(str(report)) + ').write_text(json.dumps({"argv":sys.argv[1:],'
            '"regularStdin":stat.S_ISREG(os.fstat(0).st_mode),'
            '"stdinPermissions":stat.S_IMODE(os.fstat(0).st_mode),'
            '"credentialInEnvironment":options["password"] in os.environ.values()}))\n'
            'sys.stderr.write(options["password"])\nraise SystemExit(2)\n')
        executable = self.root / 'fake qpdf'
        executable.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' '
                              + shlex.quote(str(script)) + ' "$@"\n')
        executable.chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, r'verification failed \(status 2\)') as caught:
            check_qpdf_crypto(self.root, self.source, executable)
        self.assertNotIn('portable-synthetic', str(caught.exception))
        self.assertEqual(json.loads(report.read_text()), {
            'argv': ['--job-json-file=/dev/stdin'], 'regularStdin': True,
            'stdinPermissions': 0o600, 'credentialInEnvironment': False})
        self.assertFalse((self.root / 'qpdf-aes256.pdf').exists())
        self.assertFalse(any(path.name.startswith('tmp') for path in self.root.iterdir()))

    def test_preexisting_synthetic_output_is_preserved_without_spawning(self):
        occupied = self.root / 'qpdf-aes256.pdf'
        occupied.write_bytes(b'preserve existing bytes')
        with self.assertRaisesRegex(RuntimeError, 'occupied output'):
            check_qpdf_crypto(self.root, self.source, self.root / 'must not execute')
        self.assertEqual(occupied.read_bytes(), b'preserve existing bytes')
        self.assertFalse((self.root / 'qpdf-aes128.pdf').exists())


if __name__ == '__main__': unittest.main()
