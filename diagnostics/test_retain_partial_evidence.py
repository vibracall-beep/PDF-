"""Offline provenance, missing-preview and draft-only refusal controls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import retain_evidence as strict
import retain_partial_evidence as partial
from test_retain_evidence import MemoryGitHub


class PartialGitHub(MemoryGitHub):
    def __init__(self):
        super().__init__()
        self.fail_capture(1)
        self.artifacts = [item for item in self.artifacts if item['name'] != 'PDF-macOS-preview-xcode-27']

    def step(self, index, name):
        return next(step for step in self.jobs[index]['steps'] if step['name'] == name)

    def fail_capture(self, index):
        self.step(index, partial.CAPTURE)['conclusion'] = 'failure'
        self.step(index, partial.ACCESSIBILITY)['conclusion'] = 'skipped'

    def json(self, route, method='GET', payload=None):
        if route == '/actions/runs/123/attempts/1/jobs?per_page=100':
            return {'total_count': len(self.jobs), 'jobs': copy.deepcopy(self.jobs)}
        return super().json(route, method, payload)


class PartialEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf partial audit ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.api = PartialGitHub()

    def validate(self, api=None):
        api = api or self.api
        return partial.validate_origin(api.run, api.jobs, api.artifacts, '123', api.commit, api.repository)

    def retain(self, name='first', api=None):
        api = api or self.api
        return partial.retain(api, '123', api.commit, self.root / name)

    def test_missing_preview_is_explicit_and_original_zip_bytes_stay_opaque(self):
        result = self.retain()
        self.assertEqual(result['verifiedAssets'], 11)
        self.assertTrue(result['partialEvidence']); self.assertTrue(result['draft'])
        self.assertFalse(result['productApproved'])
        manifest = json.loads((self.root / 'first' / partial.MANIFEST).read_text())
        self.assertEqual(manifest['artifactCounts'], {'expected': 10, 'available': 9, 'missing': 1})
        self.assertEqual(manifest['previewArtifactCounts'], {'expected': 2, 'available': 1, 'missing': 1})
        self.assertEqual(manifest['missingArtifactNames'], ['PDF-macOS-preview-xcode-27'])
        self.assertIsNone(manifest['previewImageCount'])
        for flag in ('humanVisualReviewPerformed', 'productApproved', 'applicationApproved',
                     'binaryDistributionApproved', 'archiveContentsExtractedOrExecuted'):
            self.assertIs(manifest[flag], False)
        for runner, record in zip(strict.RUNNERS, manifest['jobs']):
            self.assertEqual(record['runner'], runner)
            self.assertEqual(record['requiredNativeGatesPassed'], list(partial.REQUIRED_STEPS))
            self.assertEqual(len(record['requiredNativeGatesPassed']), 13)
        visual = manifest['jobs'][1]['visualEvidence']
        self.assertEqual((visual['capture'], visual['accessibility']), ('failure', 'skipped'))
        self.assertIsNone(visual['artifactID']); self.assertFalse(visual['artifactPresent'])
        self.assertIsNone(visual['imageCount']); self.assertTrue(visual['visualGateFailed'])
        for item in self.api.artifacts:
            expected = self.api.payloads['/actions/artifacts/' + str(item['id']) + '/zip']
            self.assertEqual((self.root/'first'/(item['name']+'.zip')).read_bytes(), expected)
        logs = manifest['files'][-1]
        self.assertEqual(logs['sourceAPIPath'], '/actions/runs/123/attempts/1/logs')
        self.assertEqual(logs['jobIDs'], [100, 101])
        self.assertEqual((self.root/'first'/logs['name']).read_bytes(), self.api.payloads[logs['sourceAPIPath']])
        self.assertFalse((self.root/'first/PDF-macOS-preview-xcode-27.zip').exists())
        self.assertFalse((self.root/'must-not-be-extracted').exists())
        self.assertFalse((self.root/'must-not-extract-logs').exists())

    def test_failed_validation_with_present_preview_is_retained_without_labeling_it_passed(self):
        original = MemoryGitHub()
        self.api.artifacts = original.artifacts
        self.api.step(1, partial.CAPTURE)['conclusion'] = 'success'
        self.api.step(1, partial.ACCESSIBILITY)['conclusion'] = 'failure'
        _, selected, missing, visual = self.validate()
        self.assertEqual(len(selected), 10); self.assertEqual(missing, [])
        self.assertTrue(visual['xcode-27']['visualGateFailed'])
        self.assertTrue(visual['xcode-27']['artifactPresent'])
        self.assertIsNone(visual['xcode-27']['imageCount'])
        self.api.artifacts = [item for item in self.api.artifacts if item['name'] != 'PDF-macOS-preview-xcode-27']
        with self.assertRaises(strict.EvidenceFailure): self.validate()

    def test_both_failed_captures_can_lack_only_their_own_preview(self):
        self.api.fail_capture(0)
        self.api.artifacts = [item for item in self.api.artifacts if item['name'] != 'PDF-macOS-preview-macos-26']
        _, selected, missing, _ = self.validate()
        self.assertEqual(len(selected), 8); self.assertEqual(len(missing), 2)

    def test_partial_audit_does_not_change_strict_retention_contract(self):
        self.assertEqual(len(strict.REQUIRED_STEPS), 15)
        self.assertEqual(len(strict.ARTIFACT_NAMES), 10)
        with self.assertRaises(strict.EvidenceFailure):
            strict.validate_origin(self.api.run, self.api.jobs, self.api.artifacts, '123', self.api.commit, self.api.repository)
        healthy = MemoryGitHub()
        with self.assertRaisesRegex(strict.EvidenceFailure, 'actual failed capture'):
            partial.validate_origin(healthy.run, healthy.jobs, healthy.artifacts, '123', healthy.commit, healthy.repository)

    def test_wrong_source_identity_attempt_and_required_gate_are_refused(self):
        variants = []
        for field, value in [('id', 124), ('status', 'in_progress'), ('conclusion', 'success'),
                             ('head_sha', 'b'*40), ('path', '.github/workflows/other.yml')]:
            api = copy.deepcopy(self.api); api.run[field] = value; variants.append(api)
        api = copy.deepcopy(self.api); api.run['head_repository']['id'] = 99; variants.append(api)
        api = copy.deepcopy(self.api); api.run['head_repository']['full_name'] = 'fork/PDF-'; variants.append(api)
        for field, value in [('run_attempt', 2), ('run_id', 124), ('head_sha', 'b'*40), ('id', 100)]:
            api = copy.deepcopy(self.api); api.jobs[1][field] = value; variants.append(api)
        for name in partial.REQUIRED_STEPS:
            api = copy.deepcopy(self.api); api.step(0, name)['conclusion'] = 'failure'; variants.append(api)
        api = copy.deepcopy(self.api); api.jobs[1]['steps'].append(api.step(1, partial.CAPTURE)); variants.append(api)
        for api in variants:
            with self.subTest(run=api.run, jobs=api.jobs), self.assertRaises(strict.EvidenceFailure):
                self.validate(api)
            self.assertEqual(api.create_count, 0); self.assertEqual(api.upload_count, 0)

    def test_inconsistent_preview_states_or_nonfailed_job_are_refused(self):
        for capture, accessibility, job in [('success', 'success', 'failure'), ('skipped', 'skipped', 'failure'),
                                             ('failure', 'success', 'failure'), ('failure', 'failure', 'failure'),
                                             ('failure', 'skipped', 'success'), ('failure', 'skipped', 'cancelled')]:
            api = copy.deepcopy(self.api)
            api.step(1, partial.CAPTURE)['conclusion'] = capture
            api.step(1, partial.ACCESSIBILITY)['conclusion'] = accessibility
            api.jobs[1]['conclusion'] = job
            with self.subTest(capture=capture, accessibility=accessibility, job=job), self.assertRaises(strict.EvidenceFailure):
                self.validate(api)

    def test_missing_foreign_duplicate_expired_and_malformed_artifacts_are_refused(self):
        variants = []
        for field, value in [('expired', True), ('digest', 'sha256:bad'), ('size_in_bytes', strict.MAX_ARTIFACT+1),
                             ('created_at', '2026-10-23T10:30:00Z'), ('created_at', '2026-99-99T10:30:00Z')]:
            api = copy.deepcopy(self.api); api.artifacts[0][field] = value; variants.append(api)
        for field, value in [('id', 124), ('head_sha', 'b'*40), ('repository_id', 99), ('head_repository_id', 99)]:
            api = copy.deepcopy(self.api); api.artifacts[0]['workflow_run'][field] = value; variants.append(api)
        api = copy.deepcopy(self.api); api.artifacts.append(api.artifacts[0]); variants.append(api)
        api = copy.deepcopy(self.api); api.artifacts[1]['id'] = api.artifacts[0]['id']; variants.append(api)
        for name in ['PDF-native-checks-xcode-27', 'PDF-macOS-preview-macos-26']:
            api = copy.deepcopy(self.api); api.artifacts = [item for item in api.artifacts if item['name'] != name]; variants.append(api)
        for api in variants:
            with self.subTest(artifacts=api.artifacts), self.assertRaises(strict.EvidenceFailure): self.validate(api)

    def test_wrong_download_digest_and_missing_logs_prevent_any_draft_creation(self):
        api = copy.deepcopy(self.api); api.artifacts[0]['digest'] = 'sha256:'+'0'*64
        with self.assertRaises(strict.EvidenceFailure): self.retain('wrong-digest', api)
        self.assertIsNone(api.release); self.assertEqual(api.upload_count, 0)
        api = copy.deepcopy(self.api); del api.payloads['/actions/runs/123/attempts/1/logs']
        with self.assertRaises(KeyError): self.retain('missing-logs', api)
        self.assertIsNone(api.release); self.assertEqual(api.upload_count, 0)

    def test_rerun_is_byte_identical_and_adds_only_missing_assets(self):
        first = self.retain(); second = self.retain('second')
        self.assertEqual(first, second); self.assertEqual(self.api.create_count, 1)
        self.assertEqual(self.api.upload_count, 11)
        self.assertEqual((self.root/'first'/partial.MANIFEST).read_bytes(), (self.root/'second'/partial.MANIFEST).read_bytes())
        removed = self.api.assets.pop(); del self.api.payloads['/releases/assets/'+str(removed['id'])]
        self.retain('third'); self.assertEqual(self.api.upload_count, 12)

    def test_published_modified_draft_or_asset_is_never_overwritten(self):
        self.retain()
        for field, value in [('draft', False), ('target_commitish', 'b'*40), ('body', 'owner edited notes')]:
            api = copy.deepcopy(self.api); api.release[field] = value
            with self.subTest(field=field), self.assertRaises(strict.EvidenceFailure): self.retain(field, api)
            self.assertEqual(api.upload_count, 11); self.assertEqual(api.create_count, 1)
        api = copy.deepcopy(self.api); asset = api.assets[0]; asset.pop('digest')
        api.payloads['/releases/assets/'+str(asset['id'])] = b'x'*asset['size']
        with self.assertRaises(strict.EvidenceFailure): self.retain('changed-bytes', api)
        self.assertEqual(api.upload_count, 11)
        api = copy.deepcopy(self.api); api.assets.append({'id': 999, 'name': 'owner-file'})
        with self.assertRaises(strict.EvidenceFailure): self.retain('foreign-asset', api)
        self.assertEqual(api.upload_count, 11)

    def test_final_readback_detects_release_published_during_verification(self):
        download = self.api.download
        def changed(route, *args, **kwargs):
            result = download(route, *args, **kwargs)
            if self.api.assets and route == '/releases/assets/'+str(self.api.assets[-1]['id']):
                self.api.release['draft'] = False
            return result
        with patch.object(self.api, 'download', side_effect=changed), self.assertRaises(strict.EvidenceFailure):
            self.retain()

    def test_incomplete_api_inventory_and_existing_local_output_are_refused(self):
        original = self.api.json
        def incomplete(route, *args, **kwargs):
            value = original(route, *args, **kwargs)
            if route.endswith('/jobs?per_page=100'): value['total_count'] += 1
            return value
        with patch.object(self.api, 'json', side_effect=incomplete), self.assertRaises(strict.EvidenceFailure): self.retain()
        self.assertIsNone(self.api.release)
        existing = self.root/'first'; existing.mkdir(); keep = existing/'owner.txt'; keep.write_bytes(b'unchanged')
        with self.assertRaises(FileExistsError): self.retain()
        self.assertEqual(keep.read_bytes(), b'unchanged'); self.assertIsNone(self.api.release)


if __name__ == '__main__':
    unittest.main()
