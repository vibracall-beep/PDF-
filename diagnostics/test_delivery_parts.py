from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

import delivery_parts as parts


class DeliveryPartsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf delivery parts ')
        self.root = Path(self.temporary.name)
        self.assets = self.root / 'assets with spaces'; self.assets.mkdir()
        self.output = self.root / 'new output'; self.output.mkdir()
        self.source = self.root / 'approved original.tar.gz'
        self.data = b'Original approved bytes: ' + bytes(range(64))
        self.source.write_bytes(self.data)

    def tearDown(self):
        self.assertFalse(list(self.root.rglob('.pdf-delivery-part-*')))
        self.assertFalse(list(self.root.rglob('.pdf-reassemble.*')))
        self.temporary.cleanup()

    def split(self, size=16, limit=32):
        return parts.plan_parts(self.source, part_bytes=size, asset_limit=limit)

    def script(self, plan=None):
        plan = plan or self.split()
        for record in plan['parts']:
            parts.materialize_part(self.source, record, self.assets / record['name'])
        script = self.assets / 'reassemble-binary.sh'
        script.write_bytes(parts.reassembly_script(plan))
        return plan, script

    def execute(self, script, output=True):
        arguments = ['/bin/bash', str(script)]
        if output:
            arguments.append(str(self.output))
        return subprocess.run(arguments, cwd=self.root, capture_output=True, text=True, timeout=20)

    def assert_failed_script(self, script):
        result = self.execute(script)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse((self.output / parts.ARCHIVE_NAME).exists())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_single_asset_below_limit_and_split_at_exact_limit(self):
        single = parts.plan_parts(self.source, part_bytes=16, asset_limit=len(self.data) + 1)
        self.assertEqual(single['mode'], 'single')
        expected = hashlib.sha256(self.data).hexdigest()
        self.assertEqual(single['sha256'], expected)
        self.assertEqual(single['parts'], [dict(name=parts.ARCHIVE_NAME, offset=0, bytes=len(self.data), sha256=expected)])
        target = self.output / parts.ARCHIVE_NAME
        parts.materialize_part(self.source, single['parts'][0], target)
        self.assertEqual(target.read_bytes(), self.data)
        split = parts.plan_parts(self.source, part_bytes=16, asset_limit=len(self.data))
        self.assertEqual(split['mode'], 'byte-parts')
        self.assertEqual(split['bytes'], len(self.data))
        self.assertEqual(split['sha256'], expected)
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_streaming_records_have_exact_ranges_and_hashes(self):
        with mock.patch.object(parts, 'READ_BYTES', 3):
            plan = self.split()
        assembled = bytearray()
        for index, record in enumerate(plan['parts']):
            self.assertEqual(record['name'], f'{parts.ARCHIVE_NAME}.part-{index + 1:06d}')
            self.assertEqual(record['offset'], len(assembled))
            segment = self.data[record['offset']:record['offset'] + record['bytes']]
            self.assertEqual(record['sha256'], hashlib.sha256(segment).hexdigest())
            target = self.assets / record['name']
            parts.materialize_part(self.source, record, target)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(target.read_bytes(), segment)
            assembled += target.read_bytes()
        self.assertEqual(bytes(assembled), self.data)

    def test_reassembly_runs_from_another_directory_and_preserves_parts(self):
        plan, script = self.script()
        before = {record['name']: (self.assets / record['name']).read_bytes() for record in plan['parts']}
        subprocess.run(['/bin/bash', '-n', str(script)], check=True, timeout=10)
        # Exercise the /var -> /private/var shape on every platform: the
        # delivered script intentionally reports its canonical output path.
        alias = self.root / 'output directory alias'
        alias.symlink_to(self.output, target_is_directory=True)
        self.output = alias
        result = self.execute(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.output / parts.ARCHIVE_NAME
        self.assertNotEqual(target, target.resolve())
        self.assertEqual(result.stdout.strip(), str(target.resolve()))
        self.assertEqual(target.read_bytes(), self.data)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), plan['sha256'])
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        for name, value in before.items():
            self.assertEqual((self.assets / name).read_bytes(), value)

    def test_default_output_is_beside_script_and_does_not_run_installer(self):
        _, script = self.script()
        installer = self.assets / 'install-binary.sh'
        installer.write_text('exit 77\n')
        result = self.execute(script, output=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.assets / parts.ARCHIVE_NAME).read_bytes(), self.data)
        self.assertEqual(installer.read_text(), 'exit 77\n')

    def test_reassembly_rejects_missing_part(self):
        plan, script = self.script()
        (self.assets / plan['parts'][1]['name']).unlink()
        self.assert_failed_script(script)

    def test_reassembly_rejects_swapped_parts(self):
        plan, script = self.script()
        first, second = (self.assets / record['name'] for record in plan['parts'][:2])
        a, b = first.read_bytes(), second.read_bytes()
        first.write_bytes(b); second.write_bytes(a)
        self.assert_failed_script(script)

    def test_reassembly_rejects_duplicate_payload_and_same_size_tampering(self):
        plan, script = self.script()
        first, second = (self.assets / record['name'] for record in plan['parts'][:2])
        original = second.read_bytes()
        second.write_bytes(first.read_bytes())
        self.assert_failed_script(script)
        second.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        self.assert_failed_script(script)

    def test_reassembly_checks_whole_hash_after_valid_parts(self):
        plan = self.split(); plan['sha256'] = '0' * 64
        _, script = self.script(plan)
        self.assert_failed_script(script)

    def test_reassembly_rejects_symbolic_link_and_fifo_parts(self):
        plan, script = self.script()
        target = self.assets / plan['parts'][0]['name']
        target.unlink(); target.symlink_to(self.source)
        self.assert_failed_script(script)
        target.unlink(); os.mkfifo(target)
        self.assert_failed_script(script)

    def test_existing_and_racing_outputs_are_never_replaced(self):
        _, script = self.script()
        target = self.output / parts.ARCHIVE_NAME
        target.write_bytes(b'Keep existing archive')
        result = self.execute(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), b'Keep existing archive')
        target.unlink()
        original_script = script.read_text()
        publication = 'ln -- "$temporary" "$output_dir/"'
        self.assertEqual(original_script.count(publication), 1)
        # Insert only the competing creator immediately before the unchanged
        # production publication command; no race timing or sleeps are needed.
        for creator in ('printf rival > "$output"', 'mkdir -- "$output"'):
            with self.subTest(creator=creator):
                script.write_text(original_script.replace(publication, creator + '\n' + publication))
                result = self.execute(script)
                self.assertNotEqual(result.returncode, 0)
                if target.is_dir():
                    self.assertEqual(list(target.iterdir()), [])
                    target.rmdir()
                else:
                    self.assertEqual(target.read_bytes(), b'rival')
                    target.unlink()

    def test_cleanup_preserves_foreign_directory_and_symbolic_replacements(self):
        _, script = self.script()
        original_script = script.read_text()
        publication = 'ln -- "$temporary" "$output_dir/"'
        self.assertEqual(original_script.count(publication), 1)
        foreign = self.root / 'foreign directory'; foreign.mkdir()
        foreign_archive = foreign / parts.ARCHIVE_NAME
        foreign_archive.write_bytes(b'Foreign archive must remain intact')
        for symbolic in (True, False):
            with self.subTest(symbolic=symbolic):
                stage_log = self.root / ('staging-path-' + str(symbolic))
                replace = 'mv -- "$temporary_dir" "$temporary_dir.original"\n'
                if symbolic:
                    replace += 'ln -s -- ' + shlex.quote(str(foreign)) + ' "$temporary_dir"\n'
                else:
                    replace += 'mkdir -- "$temporary_dir"\nprintf foreign > "$temporary_dir/PDF-arm64.tar.gz"\n'
                replace += "printf '%s\\n' \"$temporary_dir\" > " + shlex.quote(str(stage_log)) + '\nexit 43'
                script.write_text(original_script.replace(publication, replace))
                result = self.execute(script)
                self.assertEqual(result.returncode, 43, result.stderr)
                stage = Path(stage_log.read_text().strip())
                owned = Path(str(stage) + '.original')
                self.assertEqual((owned / parts.ARCHIVE_NAME).read_bytes(), self.data)
                self.assertEqual(foreign_archive.read_bytes(), b'Foreign archive must remain intact')
                self.assertFalse((self.output / parts.ARCHIVE_NAME).exists())
                if symbolic:
                    self.assertTrue(stage.is_symlink())
                    stage.unlink()
                else:
                    self.assertEqual((stage / parts.ARCHIVE_NAME).read_bytes(), b'foreign')
                    (stage / parts.ARCHIVE_NAME).unlink(); stage.rmdir()
                # Only the test's competing process owns these renamed paths.
                (owned / parts.ARCHIVE_NAME).unlink(); owned.rmdir()

    def test_materialization_rejects_existing_destination_and_corruption(self):
        record = self.split()['parts'][0]
        target = self.output / 'part'
        target.write_bytes(b'Keep this')
        with self.assertRaises(FileExistsError):
            parts.materialize_part(self.source, record, target)
        self.assertEqual(target.read_bytes(), b'Keep this')
        target.unlink(); bad = dict(record, sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            parts.materialize_part(self.source, bad, target)
        self.assertFalse(target.exists())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_materialization_refuses_racing_destination_without_leaving_partial(self):
        record = self.split()['parts'][0]
        target = self.output / 'part'
        real_link = os.link
        def race(source, destination, **kwargs):
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=kwargs['dst_dir_fd'])
            os.write(fd, b'Concurrent result'); os.close(fd)
            return real_link(source, destination, **kwargs)
        with mock.patch.object(parts.os, 'link', side_effect=race), self.assertRaises(FileExistsError):
            parts.materialize_part(self.source, record, target)
        self.assertEqual(target.read_bytes(), b'Concurrent result')

    def test_special_sources_links_limits_and_invalid_ranges_are_refused(self):
        for name, creator in (
            ('symbolic', lambda path: path.symlink_to(self.source)),
            ('fifo', os.mkfifo), ('directory', lambda path: path.mkdir()),
            ('empty', lambda path: path.touch()),
        ):
            with self.subTest(source=name):
                path = self.root / name; creator(path)
                with self.assertRaises((ValueError, OSError)):
                    parts.plan_parts(path, part_bytes=16, asset_limit=32)
                with self.assertRaises((ValueError, OSError)):
                    parts.materialize_part(path, self.split()['parts'][0], self.output / 'refused')
        oversized = self.root / 'oversized'
        with oversized.open('wb') as stream:
            stream.truncate(parts.MAX_BYTES + 1)
        with self.assertRaises(ValueError):
            parts.plan_parts(oversized)
        for size, limit in ((True, 32), (0, 32), (32, 32), (16, True), (16, parts.ASSET_LIMIT + 1)):
            with self.subTest(size=size, limit=limit), self.assertRaises(ValueError):
                parts.plan_parts(self.source, part_bytes=size, asset_limit=limit)
        with self.assertRaises(ValueError):
            parts.materialize_part(self.source, dict(self.split()['parts'][0], offset=len(self.data)), self.output / 'beyond')

    def test_source_change_during_hashing_is_detected(self):
        real_check = parts._unchanged
        def change(stream, path, before):
            with path.open('r+b') as writer:
                writer.write(b'X')
            return real_check(stream, path, before)
        with mock.patch.object(parts, '_unchanged', side_effect=change), self.assertRaisesRegex(ValueError, 'changed'):
            self.split()

    def test_plan_validation_refuses_duplicates_reordering_paths_and_wrong_totals(self):
        base = self.split()
        changes = []
        duplicate = copy.deepcopy(base); duplicate['parts'][1] = dict(duplicate['parts'][0]); changes.append(duplicate)
        reordered = copy.deepcopy(base); reordered['parts'][0], reordered['parts'][1] = reordered['parts'][1], reordered['parts'][0]; changes.append(reordered)
        path = copy.deepcopy(base); path['parts'][0]['name'] = '../part'; changes.append(path)
        command = copy.deepcopy(base); command['sha256'] = '$(touch unwanted)'; changes.append(command)
        total = copy.deepcopy(base); total['bytes'] += 1; changes.append(total)
        offset = copy.deepcopy(base); offset['parts'][0]['offset'] = True; changes.append(offset)
        extra = copy.deepcopy(base); extra['parts'][0]['unexpected'] = 'value'; changes.append(extra)
        for plan in changes:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                parts.reassembly_script(plan)
        many = self.root / 'many'; many.write_bytes(b'x' * 1001)
        with self.assertRaisesRegex(ValueError, '1,000'):
            parts.plan_parts(many, part_bytes=1, asset_limit=2)
        self.assertFalse((self.root / 'unwanted').exists())


if __name__ == '__main__':
    unittest.main()
