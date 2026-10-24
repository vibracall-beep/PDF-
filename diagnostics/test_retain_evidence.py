"""Exercise origin binding, opaque downloads and draft-only idempotency offline."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import retain_evidence as gate


class MemoryGitHub:
    repository = 'owner/PDF-'

    def __init__(self):
        self.commit = 'a' * 40
        self.run = {'id': 123, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure',
                    'head_sha': self.commit, 'path': '.github/workflows/macos.yml',
                    'repository': {'id': 45, 'full_name': self.repository},
                    'head_repository': {'id': 45, 'full_name': self.repository}}
        self.jobs = [{'id': 100 + index, 'run_id': 123, 'run_attempt': 1, 'head_sha': self.commit,
                      'name': 'native-application (' + runner + ')', 'status': 'completed',
                      'conclusion': 'failure', 'started_at': '2026-10-24T10:00:00Z',
                      'completed_at': '2026-10-24T11:00:00Z',
                      'steps': [{'name': step, 'status': 'completed', 'conclusion': 'success'}
                                for step in gate.REQUIRED_STEPS] + [{'name': 'Assemble relocatable binary distribution', 'status': 'completed', 'conclusion': 'failure'}]}
                     for index, runner in enumerate(gate.RUNNERS)]
        self.artifacts, self.payloads = [], {}
        for index, name in enumerate(gate.ARTIFACT_NAMES):
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w') as archive:
                archive.writestr('../../must-not-be-extracted', name)
            data = output.getvalue(); identifier = 200 + index
            self.payloads['/actions/artifacts/' + str(identifier) + '/zip'] = data
            self.artifacts.append({'id': identifier, 'name': name, 'size_in_bytes': len(data),
                'digest': 'sha256:' + hashlib.sha256(data).hexdigest(), 'expired': False,
                'created_at': '2026-10-24T10:30:00Z',
                'workflow_run': {'id': 123, 'head_sha': self.commit, 'repository_id': 45, 'head_repository_id': 45}})
        for job in self.jobs:
            self.payloads['/actions/jobs/' + str(job['id']) + '/logs'] = ('Complete log ' + str(job['id'])).encode()
        self.release = None; self.assets = []; self.upload_count = 0; self.create_count = 0

    def json(self, route, method='GET', payload=None):
        if route == '/actions/runs/123': return copy.deepcopy(self.run)
        if route == '/actions/runs/123/jobs?filter=latest&per_page=100':
            return {'total_count': len(self.jobs), 'jobs': copy.deepcopy(self.jobs)}
        if route == '/actions/runs/123/artifacts?per_page=100':
            return {'total_count': len(self.artifacts), 'artifacts': copy.deepcopy(self.artifacts)}
        if route == '/releases' and method == 'POST':
            self.create_count += 1
            assert payload['draft'] is True and payload['make_latest'] == 'false'
            self.release = dict(payload, id=789)
            return copy.deepcopy(self.release)
        if route == '/releases/789': return copy.deepcopy(self.release)
        raise AssertionError('Unexpected API request')

    def listing(self, route, maximum=2000):
        if route == '/releases': return [] if self.release is None else [copy.deepcopy(self.release)]
        if route == '/releases/789/assets': return copy.deepcopy(self.assets)
        raise AssertionError('Unexpected listing')

    def download(self, route, destination, limit, expected_bytes=None, expected_sha=None):
        data = self.payloads[route]
        gate.require(0 < len(data) <= limit, 'Size limit')
        gate.require(expected_bytes is None or len(data) == expected_bytes, 'Wrong download size')
        value = hashlib.sha256(data).hexdigest()
        gate.require(expected_sha is None or value == expected_sha, 'Wrong download SHA-256')
        with destination.open('xb') as stream: stream.write(data)
        return {'name': destination.name, 'bytes': len(data), 'sha256': value}

    def upload(self, tag, path):
        assert self.release['draft'] and self.release['tag_name'] == tag
        assert path.name not in {asset['name'] for asset in self.assets}
        self.upload_count += 1; identifier = 300 + self.upload_count
        data = path.read_bytes()
        self.assets.append({'id': identifier, 'name': path.name, 'size': len(data), 'state': 'uploaded',
                            'digest': 'sha256:' + hashlib.sha256(data).hexdigest()})
        self.payloads['/releases/assets/' + str(identifier)] = data


class EvidenceRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-retain-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.api = MemoryGitHub()

    def origin(self, api=None):
        api = api or self.api
        return gate.validate_origin(api.run, api.jobs, api.artifacts, '123', api.commit, api.repository)

    def test_failed_source_native_successes_are_retained_without_execution_or_approval(self):
        result = gate.retain(self.api, '123', self.api.commit, self.root / 'first')
        self.assertEqual(result['verifiedAssets'], 13)
        self.assertTrue(result['draft']); self.assertFalse(result['applicationApproved'])
        self.assertFalse((self.root / 'must-not-be-extracted').exists())
        self.assertTrue(all((self.root / 'first' / (name + '.zip')).is_file() for name in gate.ARTIFACT_NAMES))
        manifest = json.loads((self.root / 'first' / gate.MANIFEST).read_text())
        self.assertEqual(manifest['sourceConclusion'], 'failure')
        self.assertFalse(manifest['binaryDistributionApproved'])
        self.assertFalse(manifest['archiveContentsExtractedOrExecuted'])
        self.assertEqual(len(manifest['files']), 12)
        self.assertEqual(self.api.create_count, 1)

    def test_rerun_compares_existing_bytes_and_never_reuploads_them(self):
        first = gate.retain(self.api, '123', self.api.commit, self.root / 'first')
        second = gate.retain(self.api, '123', self.api.commit, self.root / 'second')
        self.assertEqual(first, second)
        self.assertEqual(self.api.upload_count, 13); self.assertEqual(self.api.create_count, 1)
        self.assertEqual((self.root / 'first' / gate.MANIFEST).read_bytes(), (self.root / 'second' / gate.MANIFEST).read_bytes())

    def test_interrupted_export_can_add_missing_assets_without_replacing_any(self):
        gate.retain(self.api, '123', self.api.commit, self.root / 'first')
        removed = self.api.assets.pop()
        self.api.payloads.pop('/releases/assets/' + str(removed['id']))
        gate.retain(self.api, '123', self.api.commit, self.root / 'second')
        self.assertEqual(self.api.upload_count, 14)
        self.assertEqual(len(self.api.assets), 13)

    def test_published_or_changed_release_is_refused_without_any_write(self):
        gate.retain(self.api, '123', self.api.commit, self.root / 'first')
        for field, value in [('draft', False), ('target_commitish', 'b' * 40), ('body', 'owner changed notes')]:
            with self.subTest(field=field):
                api = copy.deepcopy(self.api); api.release[field] = value
                with self.assertRaises(gate.EvidenceFailure):
                    gate.retain(api, '123', api.commit, self.root / field)
                self.assertEqual(api.upload_count, 13); self.assertEqual(api.create_count, 1)

    def test_changed_asset_bytes_and_foreign_assets_are_not_overwritten(self):
        gate.retain(self.api, '123', self.api.commit, self.root / 'first')
        api = copy.deepcopy(self.api)
        asset = api.assets[0]; asset.pop('digest')
        api.payloads['/releases/assets/' + str(asset['id'])] = b'x' * asset['size']
        with self.assertRaises(gate.EvidenceFailure): gate.retain(api, '123', api.commit, self.root / 'different')
        self.assertEqual(api.upload_count, 13)
        api = copy.deepcopy(self.api); api.assets.append({'name': 'owner-file', 'id': 999})
        with self.assertRaises(gate.EvidenceFailure): gate.retain(api, '123', api.commit, self.root / 'extra')
        self.assertEqual(api.upload_count, 13)

    def test_release_changed_during_final_verification_is_not_reported_as_a_draft(self):
        for field, value in [('draft', False), ('body', 'changed during final download')]:
            with self.subTest(field=field):
                api = copy.deepcopy(self.api)
                original_download = api.download
                def changed_download(route, *args, **kwargs):
                    record = original_download(route, *args, **kwargs)
                    if api.assets and route == '/releases/assets/' + str(api.assets[-1]['id']):
                        api.release[field] = value
                    return record
                with patch.object(api, 'download', side_effect=changed_download):
                    with self.assertRaises(gate.EvidenceFailure):
                        gate.retain(api, '123', api.commit, self.root / field)
                self.assertEqual(api.upload_count, 13)

    def test_foreign_run_commit_workflow_and_incomplete_gates_are_rejected(self):
        variants = []
        for field, value in [('status', 'in_progress'), ('conclusion', 'success'),
                             ('head_sha', 'b' * 40), ('path', '.github/workflows/other.yml')]:
            api = copy.deepcopy(self.api); api.run[field] = value; variants.append(api)
        api = copy.deepcopy(self.api); api.run['head_repository']['full_name'] = 'fork/PDF-'; variants.append(api)
        api = copy.deepcopy(self.api); api.jobs[0]['run_attempt'] = 2; variants.append(api)
        api = copy.deepcopy(self.api); api.jobs[0]['steps'][0]['conclusion'] = 'failure'; variants.append(api)
        api = copy.deepcopy(self.api); api.jobs[0]['steps'].append(api.jobs[0]['steps'][0]); variants.append(api)
        for api in variants:
            with self.subTest(run=api.run):
                with self.assertRaises(gate.EvidenceFailure): self.origin(api)

    def test_missing_duplicate_stale_expired_and_tampered_artifacts_are_rejected(self):
        variants = []
        for field, value in [('expired', True), ('digest', None), ('size_in_bytes', gate.MAX_ARTIFACT + 1),
                             ('created_at', '2026-10-23T10:00:00Z')]:
            api = copy.deepcopy(self.api); api.artifacts[0][field] = value; variants.append(api)
        api = copy.deepcopy(self.api); api.artifacts[0]['workflow_run']['repository_id'] = 99; variants.append(api)
        api = copy.deepcopy(self.api); api.artifacts.append(api.artifacts[0]); variants.append(api)
        api = copy.deepcopy(self.api); api.artifacts.pop(); variants.append(api)
        for api in variants:
            with self.subTest(artifacts=len(api.artifacts)):
                with self.assertRaises(gate.EvidenceFailure): self.origin(api)
        self.api.artifacts[0]['digest'] = 'sha256:' + '0' * 64
        with self.assertRaises(gate.EvidenceFailure):
            gate.retain(self.api, '123', self.api.commit, self.root / 'bad-bytes')
        self.assertIsNone(self.api.release)

    def test_input_shell_fragments_and_path_traversal_are_rejected(self):
        gate.validate_inputs('123', self.api.commit, self.api.repository)
        for run_id, commit, repo in [('123; echo token', self.api.commit, self.api.repository),
                                     ('123', 'main', self.api.repository),
                                     ('123', self.api.commit, '../repo')]:
            with self.assertRaises(gate.EvidenceFailure): gate.validate_inputs(run_id, commit, repo)

    def test_real_stream_enforces_hash_size_and_does_not_echo_process_errors(self):
        api = object.__new__(gate.GitHub); api.environment = os.environ.copy()
        data = b'PK opaque ZIP bytes'
        api.arguments = lambda *args, **kwargs: [sys.executable, '-c', 'import sys;sys.stdout.buffer.write(' + repr(data) + ')']
        target = self.root / 'stream.zip'
        record = api.download('/unused', target, 100, len(data), hashlib.sha256(data).hexdigest())
        self.assertEqual(record['sha256'], hashlib.sha256(data).hexdigest())
        for expected_size, digest in [(len(data) - 1, None), (len(data), '0' * 64)]:
            bad = self.root / ('bad-' + str(expected_size))
            with self.assertRaises(gate.EvidenceFailure): api.download('/unused', bad, 100, expected_size, digest)
            self.assertFalse(bad.exists())
        api.arguments = lambda *args, **kwargs: [sys.executable, '-c', 'import sys;sys.stderr.write("secret signed URL");sys.exit(1)']
        with self.assertRaisesRegex(gate.EvidenceFailure, '^GitHub evidence download was rejected\\.$'):
            api.download('/unused', self.root / 'error', 100)
        protected = self.root / 'already-present'
        protected.write_bytes(b'preserve original')
        with self.assertRaises(FileExistsError): api.download('/unused', protected, 100)
        self.assertEqual(protected.read_bytes(), b'preserve original')

    def test_token_is_used_only_through_job_environment_and_host_is_fixed(self):
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'private-test-token', 'GH_TOKEN': 'wrong-token', 'GH_DEBUG': 'api'}):
            api = gate.GitHub(self.api.repository)
        arguments = api.arguments('/actions/runs/123')
        self.assertNotIn('private-test-token', ' '.join(arguments))
        self.assertEqual(api.environment['GITHUB_TOKEN'], 'private-test-token')
        self.assertNotIn('GH_TOKEN', api.environment); self.assertNotIn('GH_DEBUG', api.environment)
        self.assertEqual(arguments[arguments.index('--hostname') + 1], 'github.com')


if __name__ == '__main__':
    unittest.main()
