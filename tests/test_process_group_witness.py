"""Fail-closed native witness protocol and fixed, unprivileged helper selection."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
import owned_process


def report(members=None):
    members = members if members is not None else [{'pid': 42, 'pgid': 42, 'status': 5}]
    return {'schemaVersion': 1, 'pgid': 42, 'zombieState': 5, 'libprocComplete': True,
            'sysctlComplete': True, 'stable': True, 'leaderPresent': True,
            'allZombies': all(item['status'] == 5 for item in members), 'members': members}


class ProcessGroupWitnessTests(unittest.TestCase):
    def test_consensus_zombie_group_and_live_descendant_have_distinct_results(self):
        self.assertTrue(owned_process._validate_group_snapshot(json.dumps(report()).encode(), 42))
        value = report([{'pid': 42, 'pgid': 42, 'status': 5}, {'pid': 43, 'pgid': 42, 'status': 2}])
        self.assertFalse(owned_process._validate_group_snapshot(json.dumps(value).encode(), 42))

    def test_missing_ambiguous_changed_or_forged_member_snapshots_are_not_proof(self):
        variants = []
        for key in ('libprocComplete', 'sysctlComplete', 'stable', 'leaderPresent'):
            value = report(); value[key] = False; variants.append(value)
        for members in ([], [{'pid': 43, 'pgid': 42, 'status': 5}],
                        [{'pid': 42, 'pgid': 42, 'status': 5}] * 2,
                        [{'pid': 42, 'pgid': 99, 'status': 5}],
                        [{'pid': True, 'pgid': 42, 'status': 5}],
                        [{'pid': 42, 'pgid': 42, 'status': 9}]):
            variants.append(report(members))
        for key, invalid in [('schemaVersion', True), ('pgid', 99), ('zombieState', 2), ('allZombies', False)]:
            value = report(); value[key] = invalid; variants.append(value)
        forged = report([{'pid': 42, 'pgid': 42, 'status': 5}, {'pid': 43, 'pgid': 42, 'status': 2}])
        forged['allZombies'] = True; variants.append(forged)
        for value in variants:
            with self.subTest(snapshot=value), self.assertRaises((RuntimeError, ValueError)):
                owned_process._validate_group_snapshot(json.dumps(value).encode(), 42)

    def test_protocol_size_duplicate_keys_and_unknown_fields_are_rejected(self):
        encoded = json.dumps(report()).encode()
        with self.assertRaises(ValueError):
            owned_process._validate_group_snapshot(encoded.replace(b'"pgid": 42', b'"pgid": 42, "pgid": 42', 1), 42)
        with self.assertRaises(RuntimeError): owned_process._validate_group_snapshot(b' ' * (1024 * 1024 + 1), 42)
        extra = report(); extra['untrusted'] = True
        with self.assertRaises(RuntimeError): owned_process._validate_group_snapshot(json.dumps(extra).encode(), 42)
        many = report([{'pid': index, 'pgid': 42, 'status': 5} for index in range(1, 4098)])
        with self.assertRaises(RuntimeError): owned_process._validate_group_snapshot(json.dumps(many).encode(), 42)

    def test_bundle_requires_fixed_regular_unprivileged_executable_without_path_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = Path(temporary) / 'PDF.app/Contents/Resources'
            engine = resources / 'engine'; engine.mkdir(parents=True)
            helper = resources / 'runtime/bin/pdf-process-group-check'; helper.parent.mkdir(parents=True)
            alias = Path(temporary) / 'bundle folder alias'
            alias.symlink_to(resources.parent.parent, target_is_directory=True)
            for module in (engine / 'owned_process.py', alias / 'Contents/Resources/engine/owned_process.py'):
                with self.subTest(module=module), \
                     mock.patch.object(owned_process, '__file__', str(module)), \
                     mock.patch.dict(os.environ, {'PDF_PROCESS_HELPER': '/bin/true', 'PATH': '/bin'}):
                    with self.assertRaisesRegex(RuntimeError, 'missing'): owned_process._group_snapshot_helper()
                    helper.write_bytes(b'fixture'); helper.chmod(0o755)
                    selected = owned_process._group_snapshot_helper()
                    # macOS /var is an alias of /private/var. Canonicalizing the
                    # parent folder must still name this exact regular leaf.
                    self.assertEqual(selected, helper.resolve(strict=True))
                    self.assertTrue(selected.samefile(helper))
                    for mode in (0o777, 0o4755, 0o2755, 0o644):
                        helper.chmod(mode)
                        with self.subTest(mode=mode), self.assertRaises(RuntimeError): owned_process._group_snapshot_helper()
                    helper.unlink(); helper.symlink_to('/bin/true')
                    with self.assertRaises(RuntimeError): owned_process._group_snapshot_helper()
                    helper.unlink()

    def test_only_identified_source_checkout_can_use_absent_helper_ps_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root/'engine').mkdir(); (root/'scripts').mkdir()
            with mock.patch.object(owned_process, '__file__', str(root/'engine/owned_process.py')):
                with self.assertRaises(RuntimeError): owned_process._group_snapshot_helper()
                (root/'Package.swift').write_text('// source marker')
                (root/'scripts/ProcessGroupSnapshot.c').write_text('/* source marker */')
                self.assertIsNone(owned_process._group_snapshot_helper())
                helper=root/'.build/pdf-process-group-check'; helper.parent.mkdir(); helper.write_bytes(b'bad')
                with self.assertRaises(RuntimeError): owned_process._group_snapshot_helper()

    def test_native_failure_never_uses_ps_and_original_permission_error_survives(self):
        process=mock.Mock(pid=42,returncode=None); observation=mock.Mock(); observation.exited.return_value=True
        with mock.patch.object(owned_process.sys,'platform','darwin'), \
             mock.patch.object(owned_process,'_group_snapshot_helper',return_value=Path('/fixed/pdf-process-group-check')), \
             mock.patch.object(owned_process.subprocess,'run',side_effect=subprocess.CalledProcessError(2,'witness')) as run, \
             mock.patch.object(owned_process.os,'killpg',side_effect=PermissionError(errno.EPERM,'original denial')):
            with self.assertRaisesRegex(PermissionError,'original denial') as caught:
                owned_process.signal_owned_group(process,observation,15)
        self.assertEqual(run.call_count,1)
        self.assertEqual(run.call_args.args[0],['/fixed/pdf-process-group-check','42'])
        self.assertTrue(any('CalledProcessError' in note for note in caught.exception.__notes__))


if __name__ == '__main__': unittest.main()
