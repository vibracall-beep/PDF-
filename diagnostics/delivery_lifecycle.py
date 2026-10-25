"""Authenticate separately retained window diagnostics under the new delivery policy.

The legacy native/preview/cross inventories stay unchanged. This module never
executes code from downloaded artifacts, constructs a window, or authenticates
a declared source commit without the enclosing exact-run/job artifact gates.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re

import delivery_archives
import retain_evidence as evidence

ROOT = Path(__file__).resolve().parent.parent
POLICY = 'window-lifecycle-v1'
SOURCE_NAMES = ('PDF-window-lifecycle-macos-26', 'PDF-window-lifecycle-xcode-27')
CROSS_NAME = 'PDF-cross-lifecycle'
SOURCE_STEPS = (
    'Audit the real window early without installing the engine runtime',
    'Audit the real window in the complete installed application',
    'Retain separate window lifecycle diagnostics even on failure',
)
CROSS_STEPS = (
    'Audit the unchanged binary real window before GUI capture',
    'Retain separate cross-OS window lifecycle diagnostics',
)
VALIDATOR = 'scripts/check_window_lifecycle.py'
PRODUCTION_PLIST = 'scripts/PDF-Info.plist'
REQUIRED_SOURCE_FILES = (VALIDATOR, PRODUCTION_PLIST, 'scripts/prepare-window-audit-bundle.py')
MAX_REPORT = 2 * 1024 ** 2
MAX_RECEIPT = 64 * 1024
MAX_LOG = 64 * 1024 ** 2
BUNDLE_LIMITS = {'Contents/MacOS/PDF': 256 * 1024 ** 2, 'Contents/Info.plist': 65536}
require = evidence.require


def contents(cross=False):
    return {prefix + suffix: limit
            for prefix in (('cross',) if cross else ('early', 'installed'))
            for suffix, limit in (('.json', MAX_REPORT), ('-receipt.json', MAX_RECEIPT), ('.log', MAX_LOG))}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Lifecycle JSON contains a duplicate key.')
        result[key] = value
    return result


def _json(data):
    def invalid(_):
        raise evidence.EvidenceFailure('Lifecycle JSON contains a non-finite number.')
    return json.loads(data, object_pairs_hook=_unique, parse_constant=invalid)


def _bytes(path, limit):
    return delivery_archives._small(path, limit)


def record(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def _fingerprint(value, limit):
    require(isinstance(value, dict) and set(value) == {'bytes', 'sha256'}
            and type(value.get('bytes')) is int and 0 < value['bytes'] <= limit
            and isinstance(value.get('sha256'), str)
            and re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None,
            'Invalid lifecycle byte fingerprint.')
    return value


def _moment(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z', value),
            'Lifecycle timestamp must use the original canonical UTC representation.')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def trusted_validator(source_verification):
    """Load only our checked-out controller, after matching authenticated source bytes."""
    raw = _bytes(ROOT / VALIDATOR, MAX_REPORT)
    require(source_verification.get('additionalSourceFiles', {}).get(VALIDATOR) == record(raw),
            'Lifecycle validator differs from the authenticated application source.')
    spec = importlib.util.spec_from_file_location('pdf_delivery_window_lifecycle_validator', ROOT / VALIDATOR)
    require(spec is not None and spec.loader is not None, 'Lifecycle validator is unavailable.')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(directory, *, source_commit, job, source_verification, manifest=None):
    """Check complete reports/receipts/logs; only cross must match the delivered tar."""
    try:
        return _verify(Path(directory), source_commit, job, source_verification, manifest)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as error:
        if isinstance(error, evidence.EvidenceFailure):
            raise
        raise evidence.EvidenceFailure('Lifecycle evidence is malformed or inconsistent.') from None


def _verify(directory, source_commit, job, source_verification, manifest):
    cross = manifest is not None
    expected = contents(cross)
    require(not directory.is_symlink() and directory.is_dir()
            and {path.name for path in directory.iterdir()} == set(expected),
            'Complete separate lifecycle inventory required.')
    require(re.fullmatch('[0-9a-f]{40}', source_commit) is not None
            and source_verification.get('sourceCommit') == source_commit
            and source_verification.get('sourceManifestVerified') is True,
            'Lifecycle requires an authenticated original source archive.')
    validator = trusted_validator(source_verification)
    plist = _fingerprint(source_verification.get('additionalSourceFiles', {}).get(PRODUCTION_PLIST),
                         BUNDLE_LIMITS['Contents/Info.plist'])
    scopes = (('cross', 'cross-installed-binary'),) if cross else (
        ('early', 'minimal-diagnostic'), ('installed', 'installed-application'))
    raw_files = {name: _bytes(directory / name, limit) for name, limit in expected.items()}
    files = {name: record(raw) for name, raw in raw_files.items()}
    if cross:
        require(type(manifest.get('schemaVersion')) is int and manifest['schemaVersion'] == 1
                and manifest.get('commit') == source_commit and manifest.get('architecture') == 'arm64',
                'Cross lifecycle manifest identity differs.')
    results = []
    for prefix, scope in scopes:
        report_raw = raw_files[prefix + '.json']
        report = validator.validate(_json(report_raw))
        require(_moment(job.get('started_at')) <= _moment(report.get('createdAt')) <= _moment(job.get('completed_at')),
                'Lifecycle report belongs to another job interval.')
        receipt = _json(raw_files[prefix + '-receipt.json'])
        require(isinstance(receipt, dict) and set(receipt) == {
            'schemaVersion', 'scope', 'sourceCommit', 'sourceCommitAuthenticatedByThisValidator',
            'status', 'report', 'installedBundleFiles', 'nativeDiagnosticDeadlineSeconds',
            'nativeCleanupMaximumSeconds', 'externalDeadlineSeconds', 'sampleOnTimeout',
            'completeApplicationApproved', 'historicalTimeoutCauseDemonstrated', 'humanVoiceOverTested',
            'previewArtifactsValidatedByThisReport'}, 'Lifecycle receipt schema differs.')
        require(type(receipt['schemaVersion']) is int and receipt['schemaVersion'] == 1
                and receipt['scope'] == scope and receipt['sourceCommit'] == source_commit
                and receipt['status'] == 'passed', 'Lifecycle receipt scope/source/status differs.')
        for key in ('sourceCommitAuthenticatedByThisValidator', 'completeApplicationApproved',
                    'historicalTimeoutCauseDemonstrated', 'humanVoiceOverTested', 'previewArtifactsValidatedByThisReport'):
            require(receipt[key] is False, 'Lifecycle receipt claims unsupported approval: ' + key)
        require(receipt['sampleOnTimeout'] is True, 'Lifecycle timeout sampling contract differs.')
        for key, expected_value in (('nativeDiagnosticDeadlineSeconds', 55), ('nativeCleanupMaximumSeconds', 3),
                                    ('externalDeadlineSeconds', 60)):
            require(type(receipt[key]) is int and receipt[key] == expected_value,
                    'Lifecycle deadline contract differs: ' + key)
        require(_fingerprint(receipt['report'], MAX_REPORT) == record(report_raw),
                'Lifecycle receipt does not bind the original report bytes.')
        bundle = receipt['installedBundleFiles']
        require(isinstance(bundle, dict) and set(bundle) == set(BUNDLE_LIMITS), 'Incomplete lifecycle bundle identity.')
        for name, limit in BUNDLE_LIMITS.items():
            _fingerprint(bundle[name], limit)
            if cross:
                entry = manifest.get('files', {}).get('PDF.app/' + name, {})
                require(entry.get('type') == 'file' and type(entry.get('size')) is int
                        and bundle[name] == {'bytes': entry['size'], 'sha256': entry.get('sha256')},
                        'Cross lifecycle executable/plist differs from the authenticated delivered binary.')
        require(bundle['Contents/Info.plist'] == plist,
                'Lifecycle app metadata differs from the authenticated production source plist.')
        # early and native installed precede portable relocation/signing. Their
        # executable hashes must not be falsely equated to the delivered tar.
        results.append({'scope': scope, 'report': prefix + '.json', 'receipt': prefix + '-receipt.json',
                        'log': prefix + '.log', 'installedBundleFiles': bundle,
                        'deliveredBundleIdentityVerified': cross, 'operatingSystem': report['operatingSystem'],
                        'hardware': report['hardware'], 'checksPassed': len(report['checks'])})
    return {'policy': POLICY, 'sourceCommit': source_commit, 'jobID': job['id'],
            'files': files, 'reports': results, 'completeApplicationApproved': False,
            'historicalTimeoutCauseDemonstrated': False, 'humanVoiceOverTested': False,
            'sourceAuthentication': 'enclosing exact same-repository run/job/artifact and verified source archive',
            'sourceCommitAuthenticatedByReportValidator': False}
