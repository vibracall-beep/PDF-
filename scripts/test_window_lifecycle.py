"""Offline rejection/binding tests; these fixtures are not a native GUI run."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

import check_window_lifecycle as validator

SCRIPT = Path(__file__).with_name('prepare-window-audit-bundle.py')
spec = importlib.util.spec_from_file_location('minimal_window_bundle', SCRIPT)
bundle = importlib.util.module_from_spec(spec); spec.loader.exec_module(bundle)


def synthetic_report():
    report = dict(schemaVersion=1, createdAt='2026-10-25T22:00:00Z', status='passed',
                  operatingSystem='Synthetic OS fixture', hardware='Synthetic hardware fixture',
                  bundleIdentifier='local.pdf.desktop', automaticPresentationDeliberatelySuppressed=True,
                  restorationDeliberatelyDisabled=True, realSwiftUIWindowGroup=True,
                  previewCaptureEnabled=False, privateState=True, privateStateCleaned=True,
                  presentationRequests=24, readyActionsExecuted=24, maximumAttachedWorkspaceWindows=1,
                  guardCloseRequests=1, observedWindowCloses=1, totalMilliseconds=1000,
                  methodology='Offline parser fixture only; no real window was created.',
                  limitations=['Synthetic fixture', 'No native execution', 'No application approval'],
                  checks=[dict(id=name, passed=True, detail='Synthetic assertion') for name in validator.CHECKS], events=[])
    def event(phase, windows=0, real=False):
        item = dict(phase=phase, milliseconds=len(report['events']) * 10,
                    workspaceWindows=windows, visibleWorkspaceWindows=windows, applicationWindows=windows)
        if real: item.update(windowNumber=7, contentViewClass='Synthetic content', sameWorkspace=True)
        report['events'].append(item)
    for phase in validator.ORDERED_PHASES[:3]: event(phase)
    event('real-window-attached', 1, True)
    for _ in range(16):
        event('shared-presentation-requested', 1); event('shared-presentation-action-ready', 1)
    for phase in validator.ORDERED_PHASES[3:6]: event(phase, 1, True)
    event('last-workspace-closed')
    event('real-window-attached', 1, True)
    for _ in range(8):
        event('shared-presentation-requested', 1); event('shared-presentation-action-ready', 1)
    event('lifecycle-checks-completed', 1, True)
    return report


class WindowLifecycleContractTests(unittest.TestCase):
    def test_complete_controlled_fixture_schema_is_accepted_without_claiming_native_execution(self):
        value = synthetic_report()
        self.assertIs(validator.validate(value), value)

    def test_failure_missing_checks_duplicate_checks_and_contradictory_summaries_rejected(self):
        variants = []
        for key, value in [('status', 'failed'), ('failure', 'native timeout'), ('privateStateCleaned', False),
                           ('restorationDeliberatelyDisabled', False), ('realSwiftUIWindowGroup', False),
                           ('previewCaptureEnabled', True), ('readyActionsExecuted', 23),
                           ('observedWindowCloses', 0), ('maximumAttachedWorkspaceWindows', 2),
                           ('schemaVersion', True), ('totalMilliseconds', float('nan'))]:
            report = synthetic_report(); report[key] = value; variants.append(report)
        report = synthetic_report(); report['checks'].pop(); variants.append(report)
        report = synthetic_report(); report['checks'][1] = report['checks'][0]; variants.append(report)
        report = synthetic_report(); report['checks'][0]['passed'] = False; variants.append(report)
        for report in variants:
            with self.subTest(keys=report.keys()), self.assertRaises(ValueError): validator.validate(report)

    def test_event_evidence_cannot_be_missing_reordered_or_claim_ready_without_a_window(self):
        for mode in ('missing-ready', 'backwards-time', 'closed-still-visible', 'ready-empty', 'wrong-workspace', 'duplicate-window'):
            report = synthetic_report(); events = report['events']
            if mode == 'missing-ready': events.pop(next(i for i, event in enumerate(events) if event['phase'] == 'shared-presentation-action-ready'))
            elif mode == 'backwards-time': events[-1]['milliseconds'] = 0
            elif mode == 'closed-still-visible':
                event = next(event for event in events if event['phase'] == 'last-workspace-closed')
                event.update(workspaceWindows=1, visibleWorkspaceWindows=1, applicationWindows=1)
            elif mode == 'ready-empty':
                event = next(event for event in events if event['phase'] == 'shared-presentation-action-ready')
                event.update(workspaceWindows=0, visibleWorkspaceWindows=0)
            elif mode == 'wrong-workspace': events[-1]['sameWorkspace'] = False
            else: events[-1].update(workspaceWindows=2, visibleWorkspaceWindows=2, applicationWindows=2)
            with self.subTest(mode=mode), self.assertRaises(ValueError): validator.validate(report)

    def test_json_duplicate_keys_and_nonregular_or_symlink_reports_refused(self):
        with self.assertRaises(ValueError): json.loads('{"status":"passed","status":"failed"}', object_pairs_hook=validator.unique_object)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); regular = root / 'regular'; regular.write_bytes(b'{}')
            link = root / 'link'; link.symlink_to(regular)
            with self.assertRaises(OSError): validator.read_regular(link, 100)
            with self.assertRaises((OSError, ValueError)): validator.read_regular(root, 100)

    def test_minimal_bundle_has_exact_production_metadata_lease_and_no_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); binary = root / 'compiled'; binary.write_bytes(b'Synthetic executable; never executed.')
            app = bundle.assemble(binary, root / 'diagnostic/PDF.app')
            self.assertEqual((app / 'Contents/Info.plist').read_bytes(), bundle.PRODUCTION_PLIST.read_bytes())
            self.assertEqual((app / 'Contents/MacOS/PDF').read_bytes(), binary.read_bytes())
            lock = app / 'Contents/Resources/installation.lock'
            self.assertEqual(lock.read_bytes(), b''); self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o444)
            self.assertEqual({path.relative_to(app).as_posix() for path in app.rglob('*') if path.is_file()},
                             {'Contents/Info.plist', 'Contents/MacOS/PDF', 'Contents/Resources/installation.lock'})
            with self.assertRaises(FileExistsError): bundle.assemble(binary, app)
            self.assertEqual((app / 'Contents/MacOS/PDF').read_bytes(), binary.read_bytes())

    def test_minimal_bundle_refuses_symlink_input_and_cleans_only_its_own_new_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); binary = root / 'compiled'; binary.write_bytes(b'preserved')
            link = root / 'link'; link.symlink_to(binary)
            app = root / 'PDF.app'
            with self.assertRaises(OSError): bundle.assemble(link, app)
            self.assertFalse(app.exists()); self.assertEqual(binary.read_bytes(), b'preserved')

    def test_cli_binds_exact_bytes_refuses_overwriting_receipt_and_does_not_authenticate_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); binary = root / 'compiled'; binary.write_bytes(b'Synthetic executable; never executed.')
            app = bundle.assemble(binary, root / 'PDF.app')
            report = root / 'report.json'; report.write_text(json.dumps(synthetic_report()))
            receipt = root / 'receipt.json'
            command = [sys.executable, str(Path(validator.__file__)), str(report), '--app', str(app),
                       '--source-commit', 'a' * 40, '--scope', 'minimal-diagnostic', '--receipt', str(receipt)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            result_receipt = json.loads(receipt.read_text())
            self.assertEqual(result_receipt['report']['sha256'], hashlib.sha256(report.read_bytes()).hexdigest())
            self.assertEqual(result_receipt['installedBundleFiles']['Contents/MacOS/PDF']['sha256'], hashlib.sha256(binary.read_bytes()).hexdigest())
            self.assertFalse(result_receipt['sourceCommitAuthenticatedByThisValidator'])
            self.assertFalse(result_receipt['completeApplicationApproved'])
            previous = receipt.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True, timeout=10).returncode, 0)
            self.assertEqual(receipt.read_bytes(), previous)
            receipt.unlink(); broken = synthetic_report(); broken['status'] = 'failed'; report.write_text(json.dumps(broken))
            self.assertNotEqual(subprocess.run(command, capture_output=True, timeout=10).returncode, 0)
            self.assertFalse(receipt.exists())


if __name__ == '__main__': unittest.main()
