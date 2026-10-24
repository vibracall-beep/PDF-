"""Offline evidence contracts, not a native GUI execution or human review."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

import cross_gui_evidence as gui


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def record(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def source_scripts():
    return {'scripts/' + name: (gui.ROOT / 'scripts' / name).read_bytes() for name in gui.SCRIPT_NAMES}


def synthetic_originals():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(data, zlib.crc32(kind)) & 0xffffffff)
    pixels = (b'\0' + b'\xff\xff\xff' * 101) * 102
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 101, 102, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')
    files = dict.fromkeys(gui.PNG_NAMES, png)
    checker = gui.script_module(gui.ROOT, 'check_preview_artifacts')
    for name, identifiers in checker.REQUIRED_AX.items():
        files[name] = encoded({'version': 1, 'scope': 'current-process-own-window', 'findings': [],
            'traversalLimited': False, 'missingRequiredIdentifiers': [],
            'nodes': [{'index': index, 'role': 'AXButton', 'identifier': value, 'name': 'Synthetic test label'}
                      for index, value in enumerate(sorted(identifiers))]})
    files[gui.OCR_PDF] = b'%PDF-1.7\n% synthetic provenance fixture, not OCR quality proof\n%%EOF\n'
    analysis = {'version': 1, 'source_sha256': record(files[gui.OCR_PDF])['sha256'],
                'page_count': 1, 'backend': 'tesseract', 'language': 'eng', 'review_required': True,
                'settings': {'language': 'eng', 'ocr_dpi': 200, 'ocr_psm': 3, 'min_confidence': 0},
                'pages': [{'page': 1, 'width': 595.0, 'height': 842.0, 'rotation': 0}],
                'words': [{'id': 'd' * 64, 'text': 'fixture', 'page': 1, 'rect': [10, 10, 60, 25], 'confidence': 0.9}]}
    analysis['review_sha256'] = hashlib.sha256(json.dumps(analysis, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    files[gui.OCR_JSON] = encoded(analysis)
    return files


def synthetic_gui_files(verified, manifest):
    originals = synthetic_originals()
    binding = dict(schemaVersion=1, **{key: verified[key] for key in gui.IDENTITY_KEYS},
        sourceScripts={name: record(data) for name, data in ((name, source_scripts()['scripts/' + name]) for name in gui.SCRIPT_NAMES)},
        installedBinary={name: {'bytes': manifest['files'][name]['size'], 'sha256': manifest['files'][name]['sha256']}
                         for name in gui.BINARY_KEYS}, captureDeadlineSeconds=300, captureAttempts=1,
        guiOutsideDependencySandbox=True, dependencyIsolationSeparate=True, rebuiltOnDestination=False)
    before = encoded(binding)
    logs = {gui.CAPTURE_LOG: b'Synthetic capture exit0; not a real Mac execution.\n',
            gui.VALIDATION_LOG: b'Synthetic validator log.\n'}
    receipt = dict(binding, installedBundleManifestMatchedBeforeAndAfter=True, archiveUnchanged=True,
        guiCapturePassed=True, pngCount=32, ownWindowAXCount=6, originalOCRFileCount=2,
        humanVisualReview=False, humanVoiceOverTested=False,
        originals={name: record(data) for name, data in originals.items()},
        logs={name: record(data) for name, data in logs.items()}, beforeSHA256=record(before)['sha256'])
    return dict(originals, **logs, **{gui.BEFORE: before, gui.RECEIPT: encoded(receipt)})


class CrossGUIEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='PDF cross GUI ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / 'evidence'; self.directory.mkdir()
        self.archive = self.root / 'PDF-arm64.tar.gz'; self.archive.write_bytes(b'unchanged source archive fixture')
        self.verified = {'repository': 'owner/PDF-', 'sourceRunID': 123, 'sourceCommit': 'a' * 40,
            'sourceArtifactID': 456, 'archiveSHA256': record(self.archive.read_bytes())['sha256'],
            'archiveBytes': self.archive.stat().st_size}
        self.app = self.root / 'PDF.app'
        self.files = {'Contents/MacOS/PDF': b'synthetic executable identity',
                      'Contents/Info.plist': plistlib.dumps({'CFBundleIdentifier': 'local.pdf.desktop'})}
        self.manifest = {'commit': self.verified['sourceCommit'], 'files': {}}
        for name, data in self.files.items():
            path = self.app / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            self.manifest['files']['PDF.app/' + name] = dict(type='file', size=len(data),
                sha256=record(data)['sha256'], mode=path.stat().st_mode & 0o777)
        self.verified['manifestSHA256'] = gui.portable.manifest_digest(self.manifest)
        self.gui_files = synthetic_gui_files(self.verified, self.manifest)
        for name in gui.BASE_CONTENTS: (self.directory / name).write_bytes(b'original cross evidence\n')

    def populate(self):
        for name, data in self.gui_files.items(): (self.directory / name).write_bytes(data)

    def check(self):
        return gui.verify_receipt(self.directory, self.verified, self.manifest)

    def test_complete_originals_are_bound_to_binary_and_source_without_human_claims(self):
        self.populate(); result = self.check()
        self.assertEqual(len(result['originals']), 40)
        self.assertTrue(result['guiOutsideDependencySandbox'])
        self.assertFalse(result['humanVisualReview']); self.assertFalse(result['humanVoiceOverTested'])
        self.assertEqual(result['captureAttempts'], 1)

    def test_every_original_is_mandatory_and_extras_are_refused(self):
        self.populate()
        for name in gui.ORIGINALS:
            with self.subTest(name=name):
                path = self.directory / name; original = path.read_bytes(); path.unlink()
                with self.assertRaises(ValueError): self.check()
                path.write_bytes(original)
        (self.directory / 'PDF-preview.foreign.png').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'unexpected'): self.check()

    def test_corrupt_png_ax_and_ocr_are_refused_even_with_recomputed_receipt_hashes(self):
        for name, data in ((gui.PNG_NAMES[0], b'bad PNG'), (gui.AX_NAMES[0], b'{}'),
                           (gui.OCR_JSON, encoded({'version': 1, 'source_sha256': '0' * 64})),
                           (gui.OCR_PDF, b'not PDF')):
            with self.subTest(name=name):
                self.populate(); (self.directory / name).write_bytes(data)
                receipt = json.loads(self.gui_files[gui.RECEIPT]); receipt['originals'][name] = record(data)
                (self.directory / gui.RECEIPT).write_bytes(encoded(receipt))
                with self.assertRaises(ValueError): self.check()

    def test_ocr_observation_structure_is_checked_even_with_recomputed_hashes(self):
        baseline = json.loads(self.gui_files[gui.OCR_JSON])
        for field, value in (('words', [None]), ('pages', [None]), ('settings', {}),
                             ('review_sha256', '0' * 64), ('review_required', False)):
            with self.subTest(field=field):
                self.populate(); analysis = dict(baseline, **{field: value})
                data = encoded(analysis); (self.directory / gui.OCR_JSON).write_bytes(data)
                receipt = json.loads(self.gui_files[gui.RECEIPT]); receipt['originals'][gui.OCR_JSON] = record(data)
                (self.directory / gui.RECEIPT).write_bytes(encoded(receipt))
                with self.assertRaises(ValueError): self.check()

    def test_modified_original_log_identity_and_capture_claims_are_rejected(self):
        self.populate(); (self.directory / gui.PNG_NAMES[0]).write_bytes(synthetic_originals()[gui.PNG_NAMES[0]] + b'changed')
        with self.assertRaises(ValueError): self.check()
        self.populate(); (self.directory / gui.CAPTURE_LOG).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'log changed'): self.check()
        for key, value in (('captureAttempts', 2), ('captureDeadlineSeconds', 301), ('pngCount', 31),
                           ('ownWindowAXCount', 5), ('originalOCRFileCount', 0), ('guiCapturePassed', False),
                           ('guiOutsideDependencySandbox', False), ('rebuiltOnDestination', True),
                           ('humanVisualReview', True), ('sourceCommit', 'b' * 40)):
            self.populate(); receipt = json.loads(self.gui_files[gui.RECEIPT]); receipt[key] = value
            (self.directory / gui.RECEIPT).write_bytes(encoded(receipt))
            with self.subTest(key=key), self.assertRaises(ValueError): self.check()
        self.populate(); self.manifest['files'][gui.BINARY_KEYS[0]]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'tar manifest'): self.check()

    def test_prepare_and_finish_preserve_bundle_tar_and_refuse_stale_capture_or_mutation(self):
        scripts = {name: record(data) for name, data in ((name, source_scripts()['scripts/' + name]) for name in gui.SCRIPT_NAMES)}
        with patch.object(gui, 'source_identity', return_value=scripts):
            gui.prepare(self.directory, gui.ROOT, self.app, self.archive, self.manifest, self.verified)
            for name, data in self.gui_files.items():
                if name not in (gui.BEFORE, gui.RECEIPT): (self.directory / name).write_bytes(data)
            result = gui.finish(self.directory, gui.ROOT, self.app, self.archive, self.manifest, self.verified)
            self.assertTrue(result['archiveUnchanged']); self.check()
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                gui.prepare(self.directory, gui.ROOT, self.app, self.archive, self.manifest, self.verified)
            (self.directory / gui.RECEIPT).unlink()
            target = self.app / 'Contents/MacOS/PDF'; target.write_bytes(b'other executable')
            with self.assertRaisesRegex(ValueError, 'manifesto'):
                gui.finish(self.directory, gui.ROOT, self.app, self.archive, self.manifest, self.verified)
            self.assertFalse((self.directory / gui.RECEIPT).exists())
        self.assertEqual(self.archive.read_bytes(), b'unchanged source archive fixture')
        self.assertEqual((self.app / 'Contents/Info.plist').read_bytes(), self.files['Contents/Info.plist'])

    def test_archive_mutation_and_stale_capture_fail_before_receipt_or_marker(self):
        scripts = {name: record(data) for name, data in ((name, source_scripts()['scripts/' + name]) for name in gui.SCRIPT_NAMES)}
        with patch.object(gui, 'source_identity', return_value=scripts):
            (self.directory / gui.PNG_NAMES[0]).write_bytes(b'stale capture')
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                gui.prepare(self.directory, gui.ROOT, self.app, self.archive, self.manifest, self.verified)
            self.assertFalse((self.directory / gui.BEFORE).exists())
            (self.directory / gui.PNG_NAMES[0]).unlink()
            gui.prepare(self.directory, gui.ROOT, self.app, self.archive, self.manifest, self.verified)
            for name, data in self.gui_files.items():
                if name not in (gui.BEFORE, gui.RECEIPT): (self.directory / name).write_bytes(data)
            self.archive.write_bytes(b'changed archive fixture')
            with self.assertRaisesRegex(ValueError, 'source tar changed'):
                gui.finish(self.directory, gui.ROOT, self.app, self.archive, self.manifest, self.verified)
            self.assertFalse((self.directory / gui.RECEIPT).exists())

    def test_final_report_is_impossible_without_complete_gui_evidence(self):
        output = self.directory / 'PDF-cross-platform.json'
        with self.assertRaises(ValueError): gui.portable.report(self.verified, output, self.directory)
        self.assertFalse(output.exists())
        self.populate()
        def hardware(arguments, **kwargs):
            return {('/usr/bin/uname', '-m'): 'arm64',
                    ('/usr/bin/sw_vers', '-productVersion'): '27.0.1',
                    ('/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string'): 'Synthetic hardware fixture',
                    ('/usr/sbin/sysctl', '-n', 'hw.ncpu'): '6'}[tuple(arguments)]
        with patch.object(gui.portable.subprocess, 'check_output', side_effect=hardware), patch('builtins.print'):
            gui.portable.report(self.verified, output, self.directory)
        result = json.loads(output.read_bytes())
        self.assertTrue(result['installedBinaryGUIPassed']); self.assertTrue(result['isolatedRuntimePassed'])
        self.assertTrue(result['guiOutsideDependencySandbox'])
        self.assertEqual(result['guiReceiptSHA256'], record((self.directory / gui.RECEIPT).read_bytes())['sha256'])
        self.assertFalse(result['humanVoiceOverTested']); self.assertFalse(result['rebuiltOnDestination'])

    def test_resource_and_sidecar_cannot_change_together_after_archive_authentication(self):
        # The original tar/executable/plist stay unchanged. A coherent but new
        # resource+sidecar must not masquerade as the authenticated installed app.
        path = self.app / 'Contents/Resources/config.json'; path.parent.mkdir(); path.write_bytes(b'{"original":true}')
        key = 'PDF.app/Contents/Resources/config.json'
        self.manifest['files'][key] = dict(type='file', size=path.stat().st_size, mode=path.stat().st_mode & 0o777,
                                           sha256=record(path.read_bytes())['sha256'])
        self.verified['manifestSHA256'] = gui.portable.manifest_digest(self.manifest)
        path.write_bytes(b'{"altered":true}')
        self.manifest['files'][key].update(size=path.stat().st_size, sha256=record(path.read_bytes())['sha256'])
        with self.assertRaisesRegex(ValueError, 'complete archive manifest'):
            gui.prepare(self.directory, gui.ROOT, self.app, self.archive, self.manifest, self.verified)
        self.assertFalse((self.directory / gui.BEFORE).exists())

    def test_source_checkout_must_be_exact_and_clean(self):
        source = self.root / 'source'; source.mkdir(); (source / 'scripts').mkdir()
        for path, data in source_scripts().items(): (source / path).write_bytes(data)
        def git(*arguments):
            return subprocess.check_output(['git', '-C', str(source), *arguments], stderr=subprocess.DEVNULL).decode().strip()
        git('init', '-q'); git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture')
        commit = git('rev-parse', 'HEAD')
        self.assertEqual(set(gui.source_identity(source, commit)), set(gui.SCRIPT_NAMES))
        with self.assertRaisesRegex(ValueError, 'authenticated source'): gui.source_identity(source, '0' * 40)
        (source / 'scripts' / gui.SCRIPT_NAMES[0]).write_bytes(b'modified')
        with self.assertRaises(subprocess.CalledProcessError): gui.source_identity(source, commit)

    def test_symlinks_and_fifo_originals_never_follow_or_block(self):
        self.populate(); path = self.directory / gui.PNG_NAMES[0]; path.unlink()
        path.symlink_to(self.directory / gui.PNG_NAMES[1])
        with self.assertRaises(OSError): self.check()
        path.unlink(); os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, 'regular'): self.check()


if __name__ == '__main__':
    unittest.main()
