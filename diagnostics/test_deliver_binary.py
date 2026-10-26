"""Offline delivery contract: immutable origins, exact bytes and draft-only writes."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import deliver_binary as gate
import delivery_archives
import retain_evidence as evidence
from test_cross_gui_evidence import source_scripts, synthetic_gui_files, record
from test_delivery_lifecycle import source_files as lifecycle_source_files, synthetic_files as lifecycle_files


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def tar_bytes(files):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode='w:gz') as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return result.getvalue()


def zip_bytes(files):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items(): archive.writestr(name, data)
    return result.getvalue()


def source_files(installer, commit, dirty=False):
    files = {**source_scripts(), **lifecycle_source_files(), 'scripts/install-binary.sh': installer,
             'BUILD-INFO.json': encoded({'source_archive_format': 1, 'commit': commit, 'working_tree_dirty': dirty})}
    sums = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n' for name, data in files.items())
    archive = tar_bytes(dict({'PDF/' + name: data for name, data in files.items()},
                             **{'PDF/SHA256SUMS': sums.encode()}))
    return {'PDF-source.tar.gz': archive,
            'PDF-source.tar.gz.sha256': (hashlib.sha256(archive).hexdigest() + '  PDF-source.tar.gz\n').encode(),
            'PDF-vision-audit.json': b'{}', 'PDF-benchmark.json': b'{}', 'PDF-local-ai.json': b'{}'}


class MemoryGitHub:
    repository = 'owner/PDF-'

    def __init__(self):
        self.commit, self.control = 'a' * 40, 'b' * 40
        self.runs, self.jobs, self.artifacts, self.payloads = {}, {}, {}, {}
        for identifier, commit, workflow, names, steps in (
                (123, self.commit, gate.SOURCE_WORKFLOW, gate.SOURCE_JOBS, gate.SOURCE_STEPS),
                (456, self.control, gate.CROSS_WORKFLOW, ('compatible-binary',), gate.CROSS_STEPS)):
            self.runs[identifier] = {'id': identifier, 'head_sha': commit, 'path': workflow,
                'status': 'completed', 'conclusion': 'success', 'run_attempt': 1,
                'repository': {'id': 45, 'full_name': self.repository},
                'head_repository': {'id': 45, 'full_name': self.repository}}
            self.jobs[identifier] = [{'id': identifier * 10 + index, 'name': name,
                'run_id': identifier, 'run_attempt': 1, 'head_sha': commit, 'status': 'completed',
                'conclusion': 'success', 'started_at': '2026-10-24T10:00:00Z', 'completed_at': '2026-10-24T11:00:00Z',
                'steps': [{'name': step, 'status': 'completed', 'conclusion': 'success'} for step in steps]}
                for index, name in enumerate(names)]
            self.artifacts[identifier] = []
            self.payloads['/actions/runs/' + str(identifier) + '/attempts/1/logs'] = zip_bytes({'original.log': b'complete original log'})
        self.installer = b'#!/bin/bash\n# original reviewed installer\nexit 0\n'
        original_files = {'install-binary.sh': self.installer,
                         'PDF.app/Contents/MacOS/PDF': b'Synthetic executable fixture',
                         'PDF.app/Contents/Info.plist': lifecycle_source_files()[gate.lifecycle.PRODUCTION_PLIST],
                         'PDF.app/Contents/Resources/runtime/THIRD-PARTY.json': b'{}',
                         'PDF.app/Contents/Resources/runtime/THIRD-PARTY.txt': b'Original notices retained.\n'}
        self.manifest = {'schemaVersion': 1, 'architecture': 'arm64', 'commit': self.commit,
            'files': {name: {'type': 'file', 'size': len(data), 'mode': 0o644,
                            'sha256': hashlib.sha256(data).hexdigest()} for name, data in original_files.items()}}
        self.tar = tar_bytes(dict({'PDF-distribution/' + name: data for name, data in original_files.items()},
                                 **{'PDF-distribution/manifest.json': encoded(self.manifest)}))
        self.sha = hashlib.sha256(self.tar).hexdigest()
        validation = {'schemaVersion': 1, 'commit': self.commit, 'runner': 'macos-26',
            'developerToolsOnDestinationRequired': False, 'appleNotarized': False, 'signing': 'ad-hoc',
            'manifestEntries': len(self.manifest['files']), 'applicationVersion': '0.6.0',
            'localAIStatus': 'unavailable', 'physicalM4Measured': False, 'humanVoiceOverTested': False}
        validation.update({name: True for name in gate.portable.REQUIRED_CHECKS})
        self.binary_files = {'PDF-arm64.tar.gz': self.tar,
            'PDF-arm64.tar.gz.sha256': (self.sha + '  PDF-arm64.tar.gz\n').encode(),
            'install-binary.sh': self.installer, 'distribution-manifest.json': encoded(self.manifest),
            'distribution-validation.json': encoded(validation)}
        binary = self.add_artifact(123, gate.portable.ARTIFACT, zip_bytes(self.binary_files))
        self.add_artifact(123, 'PDF-binary-validated-xcode-27', b'other approved package metadata')
        self.source_files = source_files(self.installer, self.commit)
        self.add_artifact(123, gate.SOURCE_NAMES[0], zip_bytes(self.source_files))
        for name in evidence.ARTIFACT_NAMES: self.add_artifact(123, name, zip_bytes({'original.json': b'{}'}))
        origin = gate.portable.validate_origin(self.runs[123], self.jobs[123], self.artifacts[123], '123', self.commit, self.repository)
        origin['expectedArchiveSHA256'] = self.sha
        verified = dict(origin, archiveSHA256=self.sha, archiveBytes=len(self.tar), archiveManifestMatched=True,
                        sourceValidationMatched=True, manifestSHA256=gate.portable.manifest_digest(self.manifest),
                        manifestEntries=len(self.manifest['files']), applicationVersion='0.6.0')
        report = dict(verified, crossOSTestPassed=True, targetRunner='xcode-27', targetOperatingSystem='27.0.1',
            targetProcessor='Apple Silicon runner', targetLogicalCPUs=6, architecture='arm64',
            freshInstallPassed=True, isolatedRuntimePassed=True, appIntentsMetadataVerified=True,
            nativeSmokePassed=True, rebuiltOnDestination=False, developerToolsOnDestinationRequired=False,
            appleNotarized=False, signing='ad-hoc', physicalM4Measured=False,
            neuralEngineMeasured=False, humanVoiceOverTested=False)
        self.cross_files = {'PDF-cross-origin.json': encoded(origin), 'PDF-cross-verified.json': encoded(verified),
                            'PDF-cross-platform.json': encoded(report), 'PDF-cross-isolation.log': b'Original complete isolation log\n'}
        self.cross_files.update(synthetic_gui_files(verified, self.manifest))
        report.update(installedBinaryGUIPassed=True, guiOutsideDependencySandbox=True,
                      guiCaptureAttempts=1, guiCaptureDeadlineSeconds=300, guiPNGCount=33,
                      guiOwnWindowAXCount=7, guiOriginalOCRFileCount=2,
                      guiReceiptSHA256=record(self.cross_files[gate.gui.RECEIPT])['sha256'])
        self.cross_files['PDF-cross-platform.json'] = encoded(report)
        self.add_artifact(456, 'PDF-cross-platform-validated', zip_bytes(self.cross_files))
        self.lifecycle_files = {}
        for name in gate.lifecycle.SOURCE_NAMES:
            self.lifecycle_files[name] = lifecycle_files(self.commit)
            self.add_artifact(123, name, zip_bytes(self.lifecycle_files[name]))
        self.lifecycle_files[gate.lifecycle.CROSS_NAME] = lifecycle_files(self.commit, self.manifest)
        self.add_artifact(456, gate.lifecycle.CROSS_NAME, zip_bytes(self.lifecycle_files[gate.lifecycle.CROSS_NAME]))
        self.release = None; self.assets = []; self.upload_count = 0; self.create_count = 0

    def add_artifact(self, run_id, name, data):
        identifier = 1000 + sum(len(items) for items in self.artifacts.values())
        item = {'id': identifier, 'name': name, 'expired': False, 'size_in_bytes': len(data),
            'digest': 'sha256:' + hashlib.sha256(data).hexdigest(), 'created_at': '2026-10-24T10:30:00Z',
            'workflow_run': {'id': run_id, 'head_sha': self.runs[run_id]['head_sha'], 'repository_id': 45, 'head_repository_id': 45}}
        self.artifacts[run_id].append(item)
        self.payloads['/actions/artifacts/' + str(identifier) + '/zip'] = data
        return item

    def replace_artifact(self, run_id, name, data):
        item = next(item for item in self.artifacts[run_id] if item['name'] == name)
        item['size_in_bytes'] = len(data); item['digest'] = 'sha256:' + hashlib.sha256(data).hexdigest()
        self.payloads['/actions/artifacts/' + str(item['id']) + '/zip'] = data

    def json(self, route, method='GET', payload=None):
        for identifier in self.runs:
            base = '/actions/runs/' + str(identifier)
            if route == base: return copy.deepcopy(self.runs[identifier])
            if route == base + '/attempts/1/jobs?per_page=100':
                return {'total_count': len(self.jobs[identifier]), 'jobs': copy.deepcopy(self.jobs[identifier])}
            if route == base + '/artifacts?per_page=100':
                return {'total_count': len(self.artifacts[identifier]), 'artifacts': copy.deepcopy(self.artifacts[identifier])}
        if route == '/releases' and method == 'POST':
            assert payload['draft'] is True and payload['make_latest'] == 'false'
            self.create_count += 1; self.release = dict(payload, id=789); return copy.deepcopy(self.release)
        if route == '/releases/789': return copy.deepcopy(self.release)
        raise AssertionError('Unexpected API route')

    def listing(self, route, maximum=2000):
        if route == '/releases': return [] if self.release is None else [copy.deepcopy(self.release)]
        if route == '/releases/789/assets': return copy.deepcopy(self.assets)
        raise AssertionError('Unexpected listing')

    def download(self, route, destination, limit, expected_bytes=None, expected_sha=None, timeout=300):
        data = self.payloads[route]; sha = hashlib.sha256(data).hexdigest()
        evidence.require(0 < len(data) <= limit and (expected_bytes is None or len(data) == expected_bytes)
                         and (expected_sha is None or sha == expected_sha), 'Authenticated download mismatch')
        with destination.open('xb') as output: output.write(data)
        return {'name': destination.name, 'bytes': len(data), 'sha256': sha}

    def upload(self, tag, path, timeout=300):
        assert self.release['draft'] and self.release['tag_name'] == tag
        assert path.name not in {asset['name'] for asset in self.assets}
        data = path.read_bytes(); self.upload_count += 1; identifier = 3000 + self.upload_count
        self.assets.append({'id': identifier, 'name': path.name, 'size': len(data), 'state': 'uploaded',
                            'digest': 'sha256:' + hashlib.sha256(data).hexdigest()})
        self.payloads['/releases/assets/' + str(identifier)] = data


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-delivery-test-')
        self.addCleanup(self.temporary.cleanup); self.root = Path(self.temporary.name)
        self.api = MemoryGitHub()

    def deliver(self, api=None, name='delivery'):
        api = api or self.api
        return gate.deliver(api, '123', api.commit, api.sha, '456', api.control, self.root / name,
                            policy=gate.lifecycle.POLICY)

    def test_exact_binary_original_sources_and_limits_are_retained_in_a_draft(self):
        result = self.deliver()
        self.assertTrue(result['draft']); self.assertEqual(result['verifiedAssets'], 76)
        self.assertEqual(result['archiveSHA256'], self.api.sha)
        self.assertNotIn('applicationApproved', result)
        provenance = json.loads((self.root / 'delivery/payload' / gate.PROVENANCE).read_text())
        self.assertEqual(provenance['cross']['commit'], self.api.control)
        self.assertEqual(provenance['source']['commit'], self.api.commit)
        self.assertEqual(provenance['schemaVersion'], 2)
        self.assertEqual(provenance['deliveryPolicy'], gate.lifecycle.POLICY)
        self.assertTrue(result['windowLifecycleChecksPassed'])
        self.assertEqual(len(provenance['windowLifecycleEvidence']), 3)
        self.assertEqual(len(gate.CROSS_CONTENTS), 50)
        self.assertEqual(len(gate.gui.ORIGINALS), 42)
        self.assertEqual(len(evidence.ARTIFACT_NAMES), 10)
        self.assertFalse(provenance['applicationLicenseAdded']); self.assertFalse(provenance['publicRelease'])
        self.assertEqual(provenance['originalSourceValidation']['localAIStatus'], 'unavailable')
        self.assertIn('VoiceOver', provenance['limitations'])
        self.assertEqual(self.api.create_count, 1)

    def test_wrong_run_attempt_repository_gates_and_artifact_origin_are_rejected(self):
        variants = []
        for identifier, field, value in [(123, 'conclusion', 'failure'), (456, 'head_sha', 'c' * 40),
                                         (456, 'path', gate.SOURCE_WORKFLOW)]:
            api = copy.deepcopy(self.api); api.runs[identifier][field] = value; variants.append(api)
        api = copy.deepcopy(self.api); api.runs[123]['head_repository']['id'] = 99; variants.append(api)
        for field, value in [('run_attempt', 2), ('run_id', 999), ('head_sha', 'c' * 40)]:
            api = copy.deepcopy(self.api); api.jobs[123][0][field] = value; variants.append(api)
        api = copy.deepcopy(self.api); api.jobs[456][0]['steps'][5]['conclusion'] = 'skipped'; variants.append(api)
        for field, value in [('digest', None), ('created_at', '2026-10-23T10:30:00Z'), ('expired', True)]:
            api = copy.deepcopy(self.api); api.artifacts[456][0][field] = value; variants.append(api)
        api = copy.deepcopy(self.api); api.artifacts[123][0]['workflow_run']['head_repository_id'] = 99; variants.append(api)
        for index, api in enumerate(variants):
            with self.subTest(index=index):
                with self.assertRaises(evidence.EvidenceFailure): self.deliver(api, str(index))
                self.assertEqual(api.create_count, 0); self.assertEqual(api.upload_count, 0)

    def test_source_transport_allowance_does_not_expand_other_artifact_limits(self):
        api = copy.deepcopy(self.api)
        source = next(item for item in api.artifacts[123] if item['name'] == gate.SOURCE_NAMES[0])
        # This exercises only authenticated metadata selection with synthetic
        # data. The download must still measure the actual ZIP against it.
        source['size_in_bytes'] = evidence.MAX_ARTIFACT + 1
        origins = gate.collect_origins(api, '123', api.commit, api.sha, '456', api.control)
        self.assertEqual(origins['sourceArtifact']['id'], source['id'])
        source['size_in_bytes'] = delivery_archives.MAX_SOURCE_TRANSPORT + 1
        with self.assertRaises(evidence.EvidenceFailure):
            gate.collect_origins(api, '123', api.commit, api.sha, '456', api.control)
        source['size_in_bytes'] = evidence.MAX_ARTIFACT + 1
        other = next(item for item in api.artifacts[123] if item['name'] == evidence.ARTIFACT_NAMES[0])
        other['size_in_bytes'] = evidence.MAX_ARTIFACT + 1
        with self.assertRaises(evidence.EvidenceFailure):
            gate.collect_origins(api, '123', api.commit, api.sha, '456', api.control)
        self.assertEqual(api.create_count, 0); self.assertEqual(api.upload_count, 0)

    def test_cross_report_cannot_relabel_another_binary_or_rebuild(self):
        for field, value in [('archiveSHA256', '0' * 64), ('archiveBytes', 1), ('sourceArtifactID', 999),
                             ('rebuiltOnDestination', True), ('targetOperatingSystem', '26.0'), ('nativeSmokePassed', False),
                             ('installedBinaryGUIPassed', False), ('guiOutsideDependencySandbox', False),
                             ('guiCaptureAttempts', 2), ('guiPNGCount', 31), ('guiReceiptSHA256', '0' * 64)]:
            with self.subTest(field=field):
                api = copy.deepcopy(self.api)
                report = json.loads(api.cross_files['PDF-cross-platform.json']); report[field] = value
                api.cross_files['PDF-cross-platform.json'] = encoded(report)
                api.replace_artifact(456, 'PDF-cross-platform-validated', zip_bytes(api.cross_files))
                with self.assertRaises(evidence.EvidenceFailure): self.deliver(api, field)
                self.assertEqual(api.create_count, 0)

    def test_gui_gates_originals_receipt_and_source_scripts_are_mandatory_before_draft(self):
        variants = []
        for step in gate.CROSS_STEPS[7:10]:
            api = copy.deepcopy(self.api)
            next(item for item in api.jobs[456][0]['steps'] if item['name'] == step)['conclusion'] = 'skipped'
            variants.append(api)
        for name in (gate.gui.RECEIPT, gate.gui.BEFORE, gate.gui.PNG_NAMES[0], gate.gui.AX_NAMES[0], gate.gui.OCR_JSON):
            api = copy.deepcopy(self.api); del api.cross_files[name]
            api.replace_artifact(456, 'PDF-cross-platform-validated', zip_bytes(api.cross_files)); variants.append(api)
        for name, data in ((gate.gui.PNG_NAMES[0], b'corrupt PNG'), ('extra.json', b'{}')):
            api = copy.deepcopy(self.api); api.cross_files[name] = data
            api.replace_artifact(456, 'PDF-cross-platform-validated', zip_bytes(api.cross_files)); variants.append(api)
        api = copy.deepcopy(self.api)
        receipt = json.loads(api.cross_files[gate.gui.RECEIPT])
        before = json.loads(api.cross_files[gate.gui.BEFORE])
        receipt['sourceScripts'][gate.gui.SCRIPT_NAMES[0]]['sha256'] = '0' * 64
        before['sourceScripts'] = receipt['sourceScripts']
        api.cross_files[gate.gui.BEFORE] = encoded(before)
        receipt['beforeSHA256'] = record(api.cross_files[gate.gui.BEFORE])['sha256']
        api.cross_files[gate.gui.RECEIPT] = encoded(receipt)
        report = json.loads(api.cross_files['PDF-cross-platform.json'])
        report['guiReceiptSHA256'] = record(api.cross_files[gate.gui.RECEIPT])['sha256']
        api.cross_files['PDF-cross-platform.json'] = encoded(report)
        api.replace_artifact(456, 'PDF-cross-platform-validated', zip_bytes(api.cross_files)); variants.append(api)
        for index, api in enumerate(variants):
            with self.subTest(index=index), self.assertRaises((evidence.EvidenceFailure, delivery_archives.ArchiveFailure)):
                self.deliver(api, 'gui-' + str(index))
            self.assertEqual(api.create_count, 0); self.assertEqual(api.upload_count, 0)

    def test_installer_and_dirty_sources_cannot_be_delivered(self):
        api = copy.deepcopy(self.api); api.binary_files['install-binary.sh'] = b'altered installer\n'
        api.replace_artifact(123, gate.portable.ARTIFACT, zip_bytes(api.binary_files))
        with self.assertRaises(delivery_archives.ArchiveFailure): self.deliver(api, 'installer')
        self.assertEqual(api.create_count, 0)
        api = copy.deepcopy(self.api)
        api.replace_artifact(123, gate.SOURCE_NAMES[0], zip_bytes(source_files(api.installer, api.commit, dirty=True)))
        with self.assertRaises(delivery_archives.ArchiveFailure): self.deliver(api, 'dirty')
        self.assertEqual(api.create_count, 0)

    def test_lifecycle_policy_is_explicit_and_legacy_absence_never_enables_fallback(self):
        for policy in (None, '', 'legacy', 'window-lifecycle-v0'):
            with self.subTest(policy=policy), patch.object(self.api, 'json', side_effect=AssertionError('must refuse before API')):
                with self.assertRaises(evidence.EvidenceFailure):
                    gate.deliver(self.api, '123', self.api.commit, self.api.sha, '456', self.api.control,
                                 self.root / 'invalid-policy', policy=policy)
        # The old ten-artifact inventory and original 0.6 validation report
        # remain representable, but do not satisfy the new mandatory policy.
        self.assertEqual(json.loads(self.api.binary_files['distribution-validation.json'])['applicationVersion'], '0.6.0')
        for run_id in (123, 456):
            self.api.artifacts[run_id] = [item for item in self.api.artifacts[run_id]
                if item['name'] not in (*gate.lifecycle.SOURCE_NAMES, gate.lifecycle.CROSS_NAME)]
        with self.assertRaises(evidence.EvidenceFailure): self.deliver(name='legacy-missing')
        self.assertEqual(self.api.create_count, 0); self.assertEqual(self.api.upload_count, 0)
        self.assertEqual(len(evidence.ARTIFACT_NAMES), 10)

    def test_three_lifecycle_zips_are_original_assets_and_internal_files_do_not_pollute_existing_inventories(self):
        self.deliver()
        names = (*gate.lifecycle.SOURCE_NAMES, gate.lifecycle.CROSS_NAME)
        assets = {item['name']: item for item in self.api.assets}
        provenance = json.loads((self.root / 'delivery/payload' / gate.PROVENANCE).read_text())
        retained = provenance['windowLifecycleEvidence']
        self.assertEqual([item['artifact']['name'] for item in retained], list(names))
        self.assertEqual([len(item['validation']['files']) for item in retained], [6, 6, 3])
        self.assertTrue(provenance['binaryChecksPassed']['requiredWindowLifecycleDiagnostics'])
        for name in names:
            run_id = 456 if name == gate.lifecycle.CROSS_NAME else 123
            artifact = next(item for item in self.api.artifacts[run_id] if item['name'] == name)
            original = self.api.payloads['/actions/artifacts/' + str(artifact['id']) + '/zip']
            asset = assets[name + '.zip']
            self.assertEqual(self.api.payloads['/releases/assets/' + str(asset['id'])], original)
        self.assertTrue(all(name not in assets for name in ('early.json', 'installed.json', 'cross.json')))
        self.assertEqual(len(gate.CROSS_CONTENTS), 50); self.assertEqual(len(gate.gui.ORIGINALS), 42)

    def test_lifecycle_missing_ambiguous_foreign_expired_and_wrong_attempt_artifacts_fail_before_draft(self):
        variants = []
        for name in (*gate.lifecycle.SOURCE_NAMES, gate.lifecycle.CROSS_NAME):
            run_id = 456 if name == gate.lifecycle.CROSS_NAME else 123
            api = copy.deepcopy(self.api)
            api.artifacts[run_id] = [item for item in api.artifacts[run_id] if item['name'] != name]
            variants.append(api)
            api = copy.deepcopy(self.api)
            artifact = next(item for item in api.artifacts[run_id] if item['name'] == name)
            api.artifacts[run_id].append(copy.deepcopy(artifact)); variants.append(api)
        for field, value in [('expired', True), ('digest', 'sha256:' + '0' * 64),
                             ('created_at', '2026-10-23T10:30:00Z')]:
            api = copy.deepcopy(self.api)
            next(item for item in api.artifacts[456] if item['name'] == gate.lifecycle.CROSS_NAME)[field] = value
            variants.append(api)
        api = copy.deepcopy(self.api)
        next(item for item in api.artifacts[123] if item['name'] == gate.lifecycle.SOURCE_NAMES[1])['workflow_run']['head_sha'] = 'c' * 40
        variants.append(api)
        for index, api in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(evidence.EvidenceFailure):
                self.deliver(api, 'lifecycle-origin-' + str(index))
            self.assertEqual(api.create_count, 0); self.assertEqual(api.upload_count, 0)

    def test_each_new_lifecycle_step_and_complete_zip_inventory_is_mandatory(self):
        variants = []
        for run_id, steps in ((123, gate.lifecycle.SOURCE_STEPS), (456, gate.lifecycle.CROSS_STEPS)):
            for job_index in range(len(self.api.jobs[run_id])):
                for step in steps:
                    api = copy.deepcopy(self.api)
                    next(item for item in api.jobs[run_id][job_index]['steps'] if item['name'] == step)['conclusion'] = 'skipped'
                    variants.append(api)
        for name in (*gate.lifecycle.SOURCE_NAMES, gate.lifecycle.CROSS_NAME):
            run_id = 456 if name == gate.lifecycle.CROSS_NAME else 123
            api = copy.deepcopy(self.api); files = dict(api.lifecycle_files[name])
            del files['cross.json' if run_id == 456 else 'installed.json']
            api.replace_artifact(run_id, name, zip_bytes(files)); variants.append(api)
        for extra in ('extra.json', '../escaped.log'):
            api = copy.deepcopy(self.api); files = dict(api.lifecycle_files[gate.lifecycle.CROSS_NAME])
            files[extra] = b'No output outside extraction allowed.'
            api.replace_artifact(456, gate.lifecycle.CROSS_NAME, zip_bytes(files)); variants.append(api)
        for index, api in enumerate(variants):
            with self.subTest(index=index), self.assertRaises((evidence.EvidenceFailure, delivery_archives.ArchiveFailure)):
                self.deliver(api, 'lifecycle-inventory-' + str(index))
            self.assertEqual(api.create_count, 0); self.assertEqual(api.upload_count, 0)

    def test_cross_lifecycle_report_bytes_and_exact_delivered_bundle_are_checked_before_any_release_write(self):
        variants = []
        name = gate.lifecycle.CROSS_NAME
        for field in ('Contents/MacOS/PDF', 'Contents/Info.plist'):
            api = copy.deepcopy(self.api); files = dict(api.lifecycle_files[name])
            receipt = json.loads(files['cross-receipt.json'])
            receipt['installedBundleFiles'][field]['sha256'] = '0' * 64
            files['cross-receipt.json'] = encoded(receipt)
            api.replace_artifact(456, name, zip_bytes(files)); variants.append(api)
        for key, value in [('scope', 'installed-application'), ('sourceCommit', 'c' * 40),
                           ('sourceCommitAuthenticatedByThisValidator', True), ('completeApplicationApproved', True)]:
            api = copy.deepcopy(self.api); files = dict(api.lifecycle_files[name])
            receipt = json.loads(files['cross-receipt.json']); receipt[key] = value
            files['cross-receipt.json'] = encoded(receipt)
            api.replace_artifact(456, name, zip_bytes(files)); variants.append(api)
        api = copy.deepcopy(self.api); files = dict(api.lifecycle_files[name]); files['cross.json'] += b' '
        api.replace_artifact(456, name, zip_bytes(files)); variants.append(api)
        for index, api in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(evidence.EvidenceFailure):
                self.deliver(api, 'lifecycle-bundle-' + str(index))
            self.assertEqual(api.create_count, 0); self.assertEqual(api.upload_count, 0)

    def test_lifecycle_validator_missing_or_different_in_authenticated_source_refuses_delivery(self):
        original = lifecycle_source_files()
        for mode in ('missing', 'substituted'):
            api = copy.deepcopy(self.api); changed = dict(original)
            if mode == 'missing': del changed[gate.lifecycle.VALIDATOR]
            else: changed[gate.lifecycle.VALIDATOR] = b'raise RuntimeError("Downloaded validator must never execute")\n'
            with patch(__name__ + '.lifecycle_source_files', return_value=changed):
                source = source_files(api.installer, api.commit)
            api.replace_artifact(123, gate.SOURCE_NAMES[0], zip_bytes(source))
            with self.subTest(mode=mode), self.assertRaises((evidence.EvidenceFailure, delivery_archives.ArchiveFailure)):
                self.deliver(api, 'lifecycle-source-' + mode)
            self.assertEqual(api.create_count, 0); self.assertEqual(api.upload_count, 0)

    def test_idempotent_rerun_compares_bytes_and_published_or_changed_assets_are_refused(self):
        first = self.deliver(); second = self.deliver(name='second')
        self.assertEqual(first, second); self.assertEqual(self.api.upload_count, 76)
        api = copy.deepcopy(self.api); api.release['draft'] = False
        with self.assertRaises(evidence.EvidenceFailure): self.deliver(api, 'published')
        self.assertEqual(api.upload_count, 76)
        api = copy.deepcopy(self.api); asset = api.assets[0]; asset.pop('digest')
        api.payloads['/releases/assets/' + str(asset['id'])] = b'x' * asset['size']
        with self.assertRaises(evidence.EvidenceFailure): self.deliver(api, 'tampered')
        self.assertEqual(api.upload_count, 76)

    def test_interrupted_draft_is_completed_without_replacing_existing_assets(self):
        self.deliver(); missing = self.api.assets.pop()
        self.api.payloads.pop('/releases/assets/' + str(missing['id']))
        self.deliver(name='resumed')
        self.assertEqual(self.api.upload_count, 77); self.assertEqual(len(self.api.assets), 76)

    def test_state_changed_during_final_download_is_not_reported_as_a_draft(self):
        original = self.api.download
        def changing(route, *args, **kwargs):
            record = original(route, *args, **kwargs)
            if self.api.assets and route == '/releases/assets/' + str(self.api.assets[-1]['id']):
                self.api.release['draft'] = False
            return record
        with patch.object(self.api, 'download', side_effect=changing):
            with self.assertRaises(evidence.EvidenceFailure): self.deliver()

    def test_byte_parts_preserve_the_original_independently_reviewed_whole_hash(self):
        real_plan = gate.delivery_parts.plan_parts
        with patch.object(gate.delivery_parts, 'plan_parts', side_effect=lambda path: real_plan(path, part_bytes=128, asset_limit=256)):
            result = self.deliver()
        provenance = json.loads((self.root / 'delivery/payload' / gate.PROVENANCE).read_text())
        self.assertEqual(provenance['archiveStorage']['mode'], 'byte-parts')
        self.assertNotIn(gate.portable.ARCHIVE, {asset['name'] for asset in self.api.assets})
        assets = {asset['name']: asset for asset in self.api.assets}
        data = b''.join(self.api.payloads['/releases/assets/' + str(assets[part['name']]['id'])]
                        for part in provenance['archiveStorage']['parts'])
        self.assertEqual(data, self.api.tar); self.assertEqual(hashlib.sha256(data).hexdigest(), result['archiveSHA256'])


if __name__ == '__main__':
    unittest.main()
