#!/usr/bin/env python3
"""Validate the bounded real-window diagnostic, not the complete application."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import stat


CHECKS = (
    'isolated-state', 'automatic-presentation-suppressed', 'first-real-window',
    'queued-actions-use-attached-window', 'existing-window-no-duplicates',
    'close-without-modal-data-loss', 'last-window-closed-through-product-guard',
    'reopened-real-window', 'workspace-and-private-preferences-preserved',
    'all-requests-no-duplicate-windows', 'background-work-drained', 'private-state-cleanup',
)
ORDERED_PHASES = (
    'diagnostic-created', 'application-did-finish-launching',
    'suppressed-launch-observed-without-window', 'perform-close-on-last-workspace',
    'product-close-guard-entered', 'appkit-window-will-close',
    'last-workspace-closed', 'lifecycle-checks-completed',
)


def require(condition, detail):
    if not condition:
        raise ValueError('Invalid window lifecycle report: ' + detail)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def read_regular(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit, 'bounded regular input required')
        data = stream.read(limit + 1); after = os.fstat(stream.fileno())
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (len(data), after.st_mtime_ns, after.st_ctime_ns) and len(data) == after.st_size,
                'input changed while reading')
        return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def validate(report):
    require(isinstance(report, dict), 'object required')
    require(type(report.get('schemaVersion')) is int and report['schemaVersion'] == 1, 'unsupported schema')
    require(report.get('status') == 'passed' and report.get('failure') is None, 'native diagnostic did not pass')
    require(report.get('bundleIdentifier') == 'local.pdf.desktop', 'production bundle identity required')
    for key in ('automaticPresentationDeliberatelySuppressed', 'restorationDeliberatelyDisabled',
                'realSwiftUIWindowGroup', 'privateState', 'privateStateCleaned'):
        require(report.get(key) is True, key + ' must be true')
    require(report.get('previewCaptureEnabled') is False, 'diagnostic must remain independent of preview capture')
    for key, expected in (('presentationRequests', 24), ('readyActionsExecuted', 24),
                          ('maximumAttachedWorkspaceWindows', 1), ('guardCloseRequests', 1), ('observedWindowCloses', 1)):
        require(type(report.get(key)) is int and report[key] == expected, key + ' contradicts the lifecycle contract')
    for key in ('operatingSystem', 'hardware', 'methodology'):
        require(nonempty(report.get(key)), key + ' required')
    created = report.get('createdAt')
    require(nonempty(created), 'timestamp required')
    try:
        instant = datetime.fromisoformat(created.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('Invalid window lifecycle report: invalid timestamp') from error
    require(instant.tzinfo is not None, 'timestamp must specify a timezone')
    limitations = report.get('limitations')
    require(isinstance(limitations, list) and len(limitations) >= 3 and all(nonempty(value) for value in limitations),
            'controlled diagnostic limitations must remain explicit')
    duration = report.get('totalMilliseconds')
    require(finite(duration) and 0 < duration < 60000, 'duration outside the external deadline')
    checks = report.get('checks')
    require(isinstance(checks, list) and len(checks) == len(CHECKS) and all(isinstance(value, dict) for value in checks),
            'all twelve lifecycle checks required')
    require([value.get('id') for value in checks] == list(CHECKS), 'missing, reordered or duplicate checks')
    for item in checks:
        require(item.get('passed') is True and nonempty(item.get('detail')), item['id'] + ' did not pass with an assertion')
    events = report.get('events')
    require(isinstance(events, list) and 10 <= len(events) <= 1000 and all(isinstance(value, dict) for value in events),
            'bounded observed events required')
    phases = []; last_time = -1; maximum = 0
    for item in events:
        phase = item.get('phase'); milliseconds = item.get('milliseconds')
        require(nonempty(phase) and finite(milliseconds) and last_time <= milliseconds <= duration,
                'event identity or monotonic timing invalid')
        last_time = milliseconds; phases.append(phase)
        for key in ('workspaceWindows', 'visibleWorkspaceWindows', 'applicationWindows'):
            require(type(item.get(key)) is int and item[key] >= 0, 'invalid observed window count')
        require(item['visibleWorkspaceWindows'] <= item['workspaceWindows'] <= 1
                and item['workspaceWindows'] <= item['applicationWindows'], 'event contradicts window counts')
        maximum = max(maximum, item['workspaceWindows'])
        if phase in ('real-window-attached', 'product-close-guard-entered', 'lifecycle-checks-completed'):
            require(item.get('sameWorkspace') is True, 'event attached to an unexpected workspace')
        if phase in ('shared-presentation-action-ready', 'lifecycle-checks-completed'):
            require(item['workspaceWindows'] == 1 and item['visibleWorkspaceWindows'] == 1,
                    'ready action lacked a visible real workspace window')
        if phase in ('suppressed-launch-observed-without-window', 'last-workspace-closed'):
            require(item['workspaceWindows'] == 0, 'empty lifecycle phase retained a workspace window')
        if phase in ('perform-close-on-last-workspace', 'lifecycle-checks-completed'):
            require(type(item.get('windowNumber')) is int and item['windowNumber'] > 0 and nonempty(item.get('contentViewClass')),
                    'real AppKit window identity/content view missing')
    require(maximum == report['maximumAttachedWorkspaceWindows'], 'event maximum contradicts summary')
    require(phases.count('shared-presentation-requested') == 24 and phases.count('shared-presentation-action-ready') == 24,
            'the 24 requests and completed actions were not individually observed')
    require(phases.count('real-window-attached') >= 1, 'no actual attached WindowGroup observed')
    positions = []
    for phase in ORDERED_PHASES:
        require(phases.count(phase) == 1, 'missing or repeated phase: ' + phase)
        positions.append(phases.index(phase))
    require(positions == sorted(positions), 'real launch/guard/close/reopen phases are out of order')
    return report


def file_record(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--scope', choices=('minimal-diagnostic', 'installed-application', 'cross-installed-binary'), required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.source_commit) is not None, 'exact declared source commit required')
    require(args.app.is_dir() and not args.app.is_symlink(), 'regular app bundle required')
    raw = read_regular(args.report, 2 * 1024**2)
    report = validate(json.loads(raw, object_pairs_hook=unique_object))
    data = {name: read_regular(args.app / name, limit) for name, limit in
            (('Contents/MacOS/PDF', 256 * 1024**2), ('Contents/Info.plist', 65536))}
    metadata = plistlib.loads(data['Contents/Info.plist'])
    require(metadata.get('CFBundleIdentifier') == report['bundleIdentifier'] and metadata.get('CFBundleExecutable') == 'PDF',
            'bundle metadata contradicts the observed application identity')
    files = {name: file_record(value) for name, value in data.items()}
    receipt = {'schemaVersion': 1, 'scope': args.scope, 'sourceCommit': args.source_commit,
               'sourceCommitAuthenticatedByThisValidator': False, 'status': 'passed',
               'report': file_record(raw), 'installedBundleFiles': files,
               'nativeDiagnosticDeadlineSeconds': 55, 'nativeCleanupMaximumSeconds': 3,
               'externalDeadlineSeconds': 60, 'sampleOnTimeout': True,
               'completeApplicationApproved': False, 'historicalTimeoutCauseDemonstrated': False,
               'humanVoiceOverTested': False, 'previewArtifactsValidatedByThisReport': False}
    # The execution/control provenance belongs to the workflow and authenticated
    # source/cross receipts. These hashes bind this independently checked report
    # to the concrete bundle observed here without rewriting their schemas.
    with args.receipt.open('x') as destination:
        json.dump(receipt, destination, ensure_ascii=False, indent=2, allow_nan=False)
        destination.write('\n')
    print('All 12 real-window diagnostic checks passed:', args.scope)
    print('Controlled automatic-presentation/restoration suppression; no full application or historical-cause approval.')
    print('Hardware:', report['hardware'], '|', report['operatingSystem'])


if __name__ == '__main__':
    main()
