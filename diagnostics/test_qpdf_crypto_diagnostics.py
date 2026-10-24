"""Receipt/privacy controls only; native crypto causality requires the Mac run."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import qpdf_crypto_diagnostics as diagnostic


class CryptoDiagnosticTests(unittest.TestCase):
    def test_legacy_cause_requires_exact_error_completed_exit_and_cleanup(self):
        valid = {'exit': 2, 'errorType': None, 'cleanupConfirmed': True, 'stderr': 'qpdf: unable to load openssl legacy provider'}
        self.assertTrue(diagnostic.legacy_failure(valid))
        for changed in ({'exit': True}, {'exit': 3}, {'errorType': 'TimeoutExpired'},
                        {'cleanupConfirmed': False}, {'stderr': 'invalid password'}):
            self.assertFalse(diagnostic.legacy_failure(dict(valid, **changed)))

    def test_encryption_whitelist_drops_credentials_and_requires_typed_parameters(self):
        parameters = {'bits': 256, 'V': 5, 'R': 6, 'P': -4,
                      **{key: 'AESv3' for key in ('method', 'streammethod', 'stringmethod', 'filemethod')}}
        encrypted = {'encrypted': True, 'userpasswordmatched': True, 'ownerpasswordmatched': False,
                     'parameters': parameters, 'recovereduserpassword': diagnostic.READER, 'unknown': diagnostic.OWNER}
        result = diagnostic.encryption_summary(json.dumps({'version': 2, 'encrypt': encrypted}).encode())
        self.assertTrue(diagnostic.aes256_expected(result))
        self.assertNotIn(diagnostic.READER, json.dumps(result)); self.assertNotIn(diagnostic.OWNER, json.dumps(result))
        for changed in ({'bits': True}, {'V': False}, {'method': diagnostic.READER}):
            with self.assertRaises(ValueError):
                diagnostic.encryption_summary(json.dumps({'version': 2, 'encrypt': dict(encrypted, parameters=dict(parameters, **changed))}).encode())

    def test_real_stdin_and_stderr_do_not_leave_credentials_in_retained_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runner = diagnostic.Measurement(root)
            code = 'import sys;data=sys.stdin.buffer.read();sys.stdout.buffer.write(data);sys.stderr.buffer.write(data);raise SystemExit(2)'
            payload = json.dumps({'password': diagnostic.READER, 'owner': diagnostic.OWNER, 'wrong': diagnostic.WRONG}).encode()
            record, stdout = runner.run('synthetic-private-transport', [sys.executable, '-c', code], payload=payload)
            self.assertEqual(stdout, payload); self.assertTrue(diagnostic.completed(record, (2,)))
            saved = (root / 'synthetic-private-transport.json').read_text()
            for credential in diagnostic.CREDENTIALS: self.assertNotIn(credential, saved)
            self.assertEqual([path.name for path in root.iterdir()], ['synthetic-private-transport.json'])

    def test_cleanup_failure_preserves_original_timeout_and_receipt_is_not_complete(self):
        class RefusedCleanup:
            pid = 123
            cleanup_confirmed = False
            def __init__(self, *args, **kwargs): pass
            def communicate(self, *args, **kwargs): raise subprocess.TimeoutExpired(['synthetic'], 1)
            def close(self): raise ChildProcessError('synthetic collection refused')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.object(diagnostic, 'OwnedProcess', RefusedCleanup):
                with self.assertRaises(subprocess.TimeoutExpired): diagnostic.Measurement(root).run('failure', ['synthetic'])
            record = json.loads((root / 'failure.json').read_text())
            self.assertEqual(record['errorType'], 'TimeoutExpired')
            self.assertEqual(record['cleanupErrorType'], 'ChildProcessError')
            self.assertFalse(record['cleanupConfirmed'])


if __name__ == '__main__': unittest.main()
