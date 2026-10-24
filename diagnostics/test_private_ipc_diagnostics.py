"""Report/policy invariants; these do not emulate the macOS sandbox."""
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from private_ipc_diagnostics import access_expectation, browser_receipt_matches, manifest_identity, private_profile, worker_expectation
from package_binary import write_manifest


class PrivateIPCReportTests(unittest.TestCase):
    def test_candidate_retains_every_base_rule_and_only_opens_private_unix_paths(self):
        with tempfile.TemporaryDirectory(prefix='pdi-', dir='/tmp') as temporary:
            root = Path(temporary).resolve()
            base = '(version 1)(allow default)(deny network*)(deny file-read* (subpath "/opt/homebrew"))'
            profile = private_profile(base, root)
            self.assertTrue(profile.startswith(base + '\n'))
            self.assertEqual(profile.count('(allow network-'), 1)
            self.assertIn('(subpath ' + json.dumps(str(root)) + ')', profile)
            self.assertIn('(literal ' + json.dumps(str(Path('/tmp').resolve())) + ')', profile)
            self.assertNotIn('remote ip', profile)
            root.chmod(0o755)
            with self.assertRaises(ValueError): private_profile(base, root)

    def test_symlink_root_is_not_a_private_policy_namespace(self):
        with tempfile.TemporaryDirectory(prefix='pdi-', dir='/tmp') as temporary:
            root = Path(temporary).resolve(); directory = root / 'actual'; directory.mkdir(mode=0o700)
            linked = root / 'linked'; linked.symlink_to(directory, target_is_directory=True)
            with self.assertRaises(ValueError): private_profile('base', linked)

    def test_access_denial_requires_completed_wok_errno(self):
        result = {'exit': 0, 'stoppedBecause': None}
        self.assertTrue(access_expectation(result, {'writable': False, 'accessErrno': errno.EPERM}, False))
        self.assertTrue(access_expectation(result, {'writable': True, 'accessErrno': 0}, True))
        for changed in ({'exit': True}, {'stoppedBecause': 'deadline'}):
            self.assertFalse(access_expectation(dict(result, **changed), {'writable': False, 'accessErrno': errno.EPERM}, False))
        for value in (errno.ENOENT, True, 0):
            self.assertFalse(access_expectation(result, {'writable': False, 'accessErrno': value}, False))

    def test_manifest_detects_mutation_new_file_and_external_link(self):
        with tempfile.TemporaryDirectory(prefix='pdi-', dir='/tmp') as temporary:
            parent = Path(temporary).resolve(); root = parent / 'runtime'; root.mkdir()
            item = root / 'original'; item.write_bytes(b'original')
            write_manifest(root, 'a' * 40)
            before = manifest_identity(root)
            moved = parent / 'moved runtime'; root.rename(moved)
            self.assertEqual(manifest_identity(moved), before)
            item = moved / 'original'; item.write_bytes(b'mutated')
            with self.assertRaises(ValueError): manifest_identity(moved)
            item.write_bytes(b'original'); extra = moved / 'extra'; extra.write_bytes(b'new')
            with self.assertRaises(ValueError): manifest_identity(moved)
            extra.unlink(); extra.symlink_to(parent)
            with self.assertRaises(ValueError): manifest_identity(moved)

    def test_worker_success_requires_real_result_and_cleanup(self):
        result = {'exit': 0, 'stoppedBecause': None}
        data = {'schemaVersion': 1, 'mode': 'multiprocessing', 'passed': True, 'parentPID': 101,
                'managerPID': 102, 'childPID': 103, 'value': 42, 'childExitCode': 0,
                'managerExitCode': 0, 'managerShutdown': True, 'socketRemoved': True}
        self.assertTrue(worker_expectation(result, data, 'multiprocessing'))
        for changed in ({'managerPID': 101}, {'value': True}, {'managerExitCode': False},
                        {'socketRemoved': False}, {'passed': False}):
            self.assertFalse(worker_expectation(result, dict(data, **changed), 'multiprocessing'))
        self.assertFalse(worker_expectation(dict(result, stoppedBecause='deadline'), data, 'multiprocessing'))
        self.assertFalse(worker_expectation(dict(result, exit=False), data, 'multiprocessing'))
        self.assertFalse(worker_expectation(result, dict(data, schemaVersion=True), 'multiprocessing'))
        browser = {'schemaVersion': 1, 'mode': 'browser', 'passed': True, 'pageCount': 1,
                   'recognizedTextMatched': True, 'browserClosed': True, 'browserPDFBytes': 5000, 'browserPDFSHA256': 'a' * 64}
        self.assertTrue(worker_expectation(result, browser, 'browser'))
        self.assertFalse(worker_expectation(result, dict(browser, mode='unknown'), 'unknown'))
        for changed in ({'recognizedTextMatched': False}, {'browserClosed': False}, {'browserPDFBytes': 0},
                        {'pageCount': True}, {'browserPDFSHA256': 'not-a-hash'}):
            self.assertFalse(worker_expectation(result, dict(browser, **changed), 'browser'))

    def test_browser_receipt_requires_matching_real_bytes_not_only_success(self):
        with tempfile.TemporaryDirectory(prefix='pdi-', dir='/tmp') as temporary:
            root = Path(temporary); pdf = root / 'browser.pdf'
            content = b'%PDF-' + b'synthetic hash fixture' * 16; pdf.write_bytes(content)
            receipt = {'browserPDFBytes': len(content), 'browserPDFSHA256': hashlib.sha256(content).hexdigest()}
            self.assertTrue(browser_receipt_matches(pdf, receipt))
            self.assertFalse(browser_receipt_matches(pdf, dict(receipt, browserPDFBytes=1)))
            self.assertFalse(browser_receipt_matches(pdf, dict(receipt, browserPDFSHA256='a' * 64)))
            linked = root / 'linked'; linked.symlink_to(pdf)
            self.assertFalse(browser_receipt_matches(linked, receipt))
            pdf.write_bytes(content + b'mutated')
            self.assertFalse(browser_receipt_matches(pdf, receipt))


if __name__ == '__main__': unittest.main()
