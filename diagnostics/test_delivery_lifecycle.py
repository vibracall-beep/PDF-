"""Real JSON/filesystem fixtures for lifecycle evidence; no native GUI approval."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import delivery_lifecycle as gate


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def source_files():
    return {name: (gate.ROOT / name).read_bytes() for name in gate.REQUIRED_SOURCE_FILES}


def source_verification(commit):
    return {'sourceCommit': commit, 'sourceManifestVerified': True,
            'additionalSourceFiles': {name: gate.record(data) for name, data in source_files().items()}}


def synthetic_report():
    validator = gate.trusted_validator(source_verification('a' * 40))
    report = dict(schemaVersion=1, createdAt='2026-10-24T10:30:00Z', status='passed',
        operatingSystem='Synthetic OS fixture', hardware='Synthetic hardware fixture',
        bundleIdentifier='local.pdf.desktop', automaticPresentationDeliberatelySuppressed=True,
        restorationDeliberatelyDisabled=True, realSwiftUIWindowGroup=True, previewCaptureEnabled=False,
        privateState=True, privateStateCleaned=True, presentationRequests=24, readyActionsExecuted=24,
        maximumAttachedWorkspaceWindows=1, guardCloseRequests=1, observedWindowCloses=1, totalMilliseconds=1000,
        methodology='Offline fixture only; never a native run or approval.',
        limitations=['Synthetic fixture', 'No native execution', 'No application approval'],
        checks=[dict(id=name, passed=True, detail='Synthetic assertion') for name in validator.CHECKS], events=[])
    def event(phase, windows=0, real=False):
        value = dict(phase=phase, milliseconds=len(report['events']) * 10,
                     workspaceWindows=windows, visibleWorkspaceWindows=windows, applicationWindows=windows)
        if real: value.update(windowNumber=7, contentViewClass='Synthetic content', sameWorkspace=True)
        report['events'].append(value)
    for phase in validator.ORDERED_PHASES[:3]: event(phase)
    event('real-window-attached', 1, True)
    for _ in range(16):
        event('shared-presentation-requested', 1); event('shared-presentation-action-ready', 1)
    for phase in validator.ORDERED_PHASES[3:6]: event(phase, 1, True)
    event('last-workspace-closed'); event('real-window-attached', 1, True)
    for _ in range(8):
        event('shared-presentation-requested', 1); event('shared-presentation-action-ready', 1)
    event('lifecycle-checks-completed', 1, True)
    return report


def synthetic_files(commit, manifest=None):
    result = {}
    scopes = (('cross', 'cross-installed-binary'),) if manifest is not None else (
        ('early', 'minimal-diagnostic'), ('installed', 'installed-application'))
    for prefix, scope in scopes:
        raw = encoded(synthetic_report())
        bundle = {'Contents/MacOS/PDF': gate.record(('Synthetic separately signed ' + prefix).encode()),
                  'Contents/Info.plist': gate.record(source_files()[gate.PRODUCTION_PLIST])}
        if manifest is not None:
            bundle = {name: {'bytes': manifest['files']['PDF.app/' + name]['size'],
                             'sha256': manifest['files']['PDF.app/' + name]['sha256']} for name in gate.BUNDLE_LIMITS}
        receipt = dict(schemaVersion=1, scope=scope, sourceCommit=commit,
            sourceCommitAuthenticatedByThisValidator=False, status='passed', report=gate.record(raw),
            installedBundleFiles=bundle, nativeDiagnosticDeadlineSeconds=55, nativeCleanupMaximumSeconds=3,
            externalDeadlineSeconds=60, sampleOnTimeout=True, completeApplicationApproved=False,
            historicalTimeoutCauseDemonstrated=False, humanVoiceOverTested=False, previewArtifactsValidatedByThisReport=False)
        result.update({prefix + '.json': raw, prefix + '-receipt.json': encoded(receipt),
                       prefix + '.log': b'Synthetic lifecycle log; no native execution.\n'})
    return result


class LifecycleEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-lifecycle-delivery-')
        self.addCleanup(self.temporary.cleanup); self.root = Path(self.temporary.name)
        self.commit = 'a' * 40
        self.job = {'id': 1234, 'started_at': '2026-10-24T10:00:00Z', 'completed_at': '2026-10-24T11:00:00Z'}
        self.source = source_verification(self.commit)
        self.manifest = {'schemaVersion': 1, 'commit': self.commit, 'architecture': 'arm64', 'files': {
            'PDF.app/' + name: {'type': 'file', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for name, data in {'Contents/MacOS/PDF': b'Synthetic delivered executable',
                               'Contents/Info.plist': source_files()[gate.PRODUCTION_PLIST]}.items()}}

    def verify(self, files, *, cross=False, source=None, manifest=None):
        for path in self.root.iterdir(): path.unlink()
        for name, data in files.items(): (self.root / name).write_bytes(data)
        return gate.verify(self.root, source_commit=self.commit, job=self.job,
            source_verification=source or self.source, manifest=(manifest or self.manifest) if cross else None)

    def test_source_scopes_preserve_separately_signed_bytes_and_cross_matches_delivered_bytes(self):
        source = self.verify(synthetic_files(self.commit))
        self.assertEqual([item['scope'] for item in source['reports']], ['minimal-diagnostic', 'installed-application'])
        self.assertTrue(all(item['deliveredBundleIdentityVerified'] is False for item in source['reports']))
        self.assertNotEqual(source['reports'][0]['installedBundleFiles']['Contents/MacOS/PDF'],
                            source['reports'][1]['installedBundleFiles']['Contents/MacOS/PDF'])
        cross = self.verify(synthetic_files(self.commit, self.manifest), cross=True)
        self.assertTrue(cross['reports'][0]['deliveredBundleIdentityVerified'])
        self.assertEqual(cross['reports'][0]['checksPassed'], 12)
        self.assertFalse(cross['completeApplicationApproved']); self.assertFalse(cross['sourceCommitAuthenticatedByReportValidator'])

    def test_receipt_scope_identity_false_claims_types_and_report_bytes_are_mandatory(self):
        for key, value in [('schemaVersion', True), ('sourceCommit', 'b' * 40), ('scope', 'cross-installed-binary'),
                           ('sourceCommitAuthenticatedByThisValidator', True), ('completeApplicationApproved', True),
                           ('humanVoiceOverTested', True), ('historicalTimeoutCauseDemonstrated', True),
                           ('previewArtifactsValidatedByThisReport', True), ('sampleOnTimeout', False),
                           ('externalDeadlineSeconds', 60.0), ('nativeDiagnosticDeadlineSeconds', 300)]:
            files = synthetic_files(self.commit); value_receipt = json.loads(files['installed-receipt.json'])
            value_receipt[key] = value; files['installed-receipt.json'] = encoded(value_receipt)
            with self.subTest(key=key), self.assertRaises(ValueError): self.verify(files)
        files = synthetic_files(self.commit); files['installed.json'] += b' '
        with self.assertRaisesRegex(ValueError, 'original report'): self.verify(files)

    def test_raw_failed_missing_and_false_ready_reports_are_rejected_even_with_refreshed_digest(self):
        for mutation in ('failed', 'old-time', 'missing-check', 'false-ready', 'nan'):
            files = synthetic_files(self.commit); report = json.loads(files['early.json'])
            if mutation == 'failed': report['status'] = 'failed'
            elif mutation == 'old-time': report['createdAt'] = '2026-10-23T10:30:00Z'
            elif mutation == 'missing-check': report['checks'].pop()
            elif mutation == 'false-ready': report['readyActionsExecuted'] = 23
            else: report['totalMilliseconds'] = float('nan')
            files['early.json'] = encoded(report)
            receipt = json.loads(files['early-receipt.json']); receipt['report'] = gate.record(files['early.json'])
            files['early-receipt.json'] = encoded(receipt)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.verify(files)

    def test_duplicate_json_keys_and_missing_extra_empty_or_symlink_files_are_refused(self):
        base = synthetic_files(self.commit)
        for missing in base:
            files = dict(base); del files[missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError): self.verify(files)
        files = dict(base, extra=b'x')
        with self.assertRaises(ValueError): self.verify(files)
        files = dict(base); files['early.log'] = b''
        with self.assertRaises(ValueError): self.verify(files)
        files = dict(base); files['early-receipt.json'] = files['early-receipt.json'].replace(b'{', b'{"status":"failed",', 1)
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.verify(files)
        self.verify(base)
        target = self.root / 'early.log'; target.unlink(); target.symlink_to(self.root / 'installed.log')
        with self.assertRaises(ValueError):
            gate.verify(self.root, source_commit=self.commit, job=self.job, source_verification=self.source)

    def test_delivered_hashes_plist_and_authenticated_validator_cannot_be_substituted(self):
        for name in gate.BUNDLE_LIMITS:
            files = synthetic_files(self.commit, self.manifest); receipt = json.loads(files['cross-receipt.json'])
            receipt['installedBundleFiles'][name]['sha256'] = '0' * 64
            files['cross-receipt.json'] = encoded(receipt)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'delivered binary'): self.verify(files, cross=True)
        source = copy.deepcopy(self.source); source['additionalSourceFiles'][gate.VALIDATOR]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'validator differs'): self.verify(synthetic_files(self.commit), source=source)
        source = copy.deepcopy(self.source); source['additionalSourceFiles'][gate.PRODUCTION_PLIST]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'production source plist'): self.verify(synthetic_files(self.commit), source=source)
        for key, value in [('commit', 'b' * 40), ('architecture', 'x86_64'), ('schemaVersion', True)]:
            manifest = copy.deepcopy(self.manifest); manifest[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(synthetic_files(self.commit, self.manifest), cross=True, manifest=manifest)


if __name__ == '__main__': unittest.main()
