"""Synthetic negative checks for cross-OS binary provenance; no macOS needed."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

import portable_compatibility as gate


class PortableCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-cross-evidence-')
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.commit = 'a' * 40
        self.repository = 'owner/PDF-'
        self.run = {'id': 123, 'status': 'completed', 'conclusion': 'success',
                    'head_sha': self.commit, 'path': '.github/workflows/macos.yml',
                    'repository': {'full_name': self.repository},
                    'head_repository': {'full_name': self.repository}}
        self.jobs = [{'name': 'native-application (' + runner + ')',
                      'status': 'completed', 'conclusion': 'success'}
                     for runner in ('macos-26', 'xcode-27')]
        self.artifacts = [{'id': 456, 'name': gate.ARTIFACT, 'size_in_bytes': 1234,
                           'expired': False, 'workflow_run': {'id': 123, 'head_sha': self.commit}}]
        self.origin = gate.validate_origin(self.run, self.jobs, self.artifacts,
                                           '123', self.commit, self.repository)
        self.manifest = {'schemaVersion': 1, 'architecture': 'arm64', 'commit': self.commit,
                         'files': {'PDF.app/fixture.txt': {'type': 'file', 'size': 4,
                            'mode': 384, 'sha256': hashlib.sha256(b'test').hexdigest()}}}
        self.validation = dict.fromkeys(gate.REQUIRED_CHECKS, True)
        self.validation.update(schemaVersion=1, commit=self.commit, runner='macos-26',
                               developerToolsOnDestinationRequired=False, appleNotarized=False,
                               signing='ad-hoc', manifestEntries=1, applicationVersion='0.6.0')
        self.make_archive()

    def make_archive(self, manifests=None):
        manifests = [self.manifest] if manifests is None else manifests
        archive = self.root / gate.ARCHIVE
        with tarfile.open(archive, 'w:gz') as tar:
            for manifest in manifests:
                data = json.dumps(manifest).encode()
                member = tarfile.TarInfo('PDF-distribution/manifest.json'); member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.origin['expectedArchiveSHA256'] = sha
        (self.root / (gate.ARCHIVE + '.sha256')).write_text(sha + '  ' + gate.ARCHIVE + '\n')
        self.write_sidecars()

    def write_sidecars(self):
        (self.root / 'distribution-manifest.json').write_text(json.dumps(self.manifest))
        (self.root / 'distribution-validation.json').write_text(json.dumps(self.validation))

    def test_exact_source_and_archive_are_bound_before_execution(self):
        result = gate.verify_archive(self.root, self.origin)
        self.assertEqual(result['sourceArtifactID'], 456)
        self.assertEqual(result['archiveSHA256'], self.origin['expectedArchiveSHA256'])
        self.assertTrue(result['archiveManifestMatched'])
        self.assertTrue(result['sourceValidationMatched'])
        self.assertNotIn('crossOSTestPassed', result)

    def test_inputs_reject_ref_names_partial_hashes_and_shell_text(self):
        valid = ('123', self.commit, 'b' * 64, self.repository)
        gate.validate_inputs(*valid)
        for index, bad in ((0, '123;echo secret'), (0, '-1'), (1, 'main'),
                           (1, 'a' * 39), (2, 'b' * 63), (3, 'owner/repo/../../other')):
            with self.subTest(index=index, bad=bad):
                values = list(valid); values[index] = bad
                with self.assertRaises(ValueError): gate.validate_inputs(*values)

    def test_source_requires_whole_success_exact_commit_and_same_repository(self):
        changes = [('status', 'in_progress'), ('conclusion', 'failure'),
                   ('head_sha', 'b' * 40), ('path', '.github/workflows/other.yml'),
                   ('head_repository', {'full_name': 'other/PDF-'})]
        for key, value in changes:
            with self.subTest(key=key):
                run = copy.deepcopy(self.run); run[key] = value
                with self.assertRaises(ValueError):
                    gate.validate_origin(run, self.jobs, self.artifacts, '123', self.commit, self.repository)
        jobs = copy.deepcopy(self.jobs); jobs[1]['conclusion'] = 'failure'
        with self.assertRaises(ValueError):
            gate.validate_origin(self.run, jobs, self.artifacts, '123', self.commit, self.repository)

    def test_artifact_cannot_be_expired_unvalidated_duplicated_or_from_another_run(self):
        variants = []
        for key, value in [('expired', True), ('name', 'PDF-binary-unvalidated-macos-26'),
                           ('workflow_run', {'id': 124, 'head_sha': self.commit})]:
            artifacts = copy.deepcopy(self.artifacts); artifacts[0][key] = value; variants.append(artifacts)
        variants.append(self.artifacts * 2)
        for artifacts in variants:
            with self.subTest(artifacts=artifacts):
                with self.assertRaises(ValueError):
                    gate.validate_origin(self.run, self.jobs, artifacts, '123', self.commit, self.repository)

    def test_archive_bytes_cannot_be_changed_after_expected_hash(self):
        with (self.root / gate.ARCHIVE).open('ab') as stream: stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            gate.verify_archive(self.root, self.origin)

    def test_checksum_sidecar_cannot_replace_independent_expected_hash(self):
        (self.root / (gate.ARCHIVE + '.sha256')).write_text('0' * 64 + '  ' + gate.ARCHIVE + '\n')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            gate.verify_archive(self.root, self.origin)

    def test_sidecar_manifest_must_match_the_sole_internal_manifest(self):
        self.manifest['commit'] = 'b' * 40
        self.write_sidecars()
        with self.assertRaisesRegex(ValueError, 'manifest'):
            gate.verify_archive(self.root, self.origin)
        self.make_archive([self.manifest, self.manifest])
        with self.assertRaisesRegex(ValueError, 'sole archive manifest'):
            gate.verify_archive(self.root, self.origin)

    def test_report_must_identify_the_same_source_and_actual_passes(self):
        baseline = self.validation.copy()
        for key, value in [('commit', 'b' * 40), ('runner', 'xcode-27'),
                           ('isolatedRuntimePassed', False), ('appIntentsMetadataVerified', False),
                           ('appleNotarized', True), ('manifestEntries', 2)]:
            with self.subTest(key=key):
                self.validation = dict(baseline, **{key: value}); self.write_sidecars()
                with self.assertRaises(ValueError): gate.verify_archive(self.root, self.origin)

    def test_special_evidence_never_blocks_or_follows_symlinks(self):
        path = self.root / 'distribution-validation.json'; path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, 'regular'):
            gate.verify_archive(self.root, self.origin)
        path.unlink(); path.symlink_to(self.root / 'distribution-manifest.json')
        with self.assertRaises(OSError): gate.verify_archive(self.root, self.origin)


if __name__ == '__main__':
    unittest.main()
