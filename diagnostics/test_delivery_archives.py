"""Real ZIP/TAR fixtures for delivery validation; no network or execution."""
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import delivery_archives as gate


class DeliveryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-delivery-archives-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / 'transport.zip'
        self.destination = self.root / 'extracted'
        self.source = self.root / 'source'; self.source.mkdir()
        self.binary = self.root / 'binary'; self.binary.mkdir()
        self.commit = 'a' * 40
        self.installer = b'#!/bin/bash\nexit 99 # fixture must never run\n'
        (self.binary / 'install-binary.sh').write_bytes(self.installer)
        self.manifest = {'schemaVersion': 1, 'architecture': 'arm64', 'commit': self.commit,
                         'files': {'install-binary.sh': {'type': 'file', 'size': len(self.installer),
                             'sha256': hashlib.sha256(self.installer).hexdigest(), 'mode': 0o755}}}

    def zip(self, members, compression=zipfile.ZIP_DEFLATED):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.archive, 'w', compression=compression) as archive:
                for name, content in members:
                    archive.writestr(name, content)

    def source_tar(self, *, build=None, changes=None, extra=(), sums=None):
        build = ({'source_archive_format': 1, 'commit': self.commit, 'working_tree_dirty': False}
                 if build is None else build)
        files = {'README.md': b'Synthetic source archive\n',
                 'scripts/install-binary.sh': self.installer,
                 'BUILD-INFO.json': json.dumps(build).encode() if isinstance(build, dict) else build}
        files.update(changes or {})
        files['SHA256SUMS'] = (''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                                     for name, data in files.items()).encode() if sums is None else sums)
        output = self.source / 'PDF-source.tar.gz'
        with tarfile.open(output, 'w:gz', format=tarfile.PAX_FORMAT) as archive:
            for name, data in files.items():
                member = tarfile.TarInfo('PDF/' + name); member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            for member, data in extra:
                archive.addfile(member, io.BytesIO(data))
        self.checksum()
        return files

    def checksum(self):
        archive = self.source / 'PDF-source.tar.gz'
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (self.source / 'PDF-source.tar.gz.sha256').write_text(digest + '  PDF-source.tar.gz\n')

    def verify(self, manifest=None):
        return gate.verify_source_and_installer(self.source, self.binary, self.commit,
                                               self.manifest if manifest is None else manifest)

    def test_extracts_only_exact_flat_inventory_with_private_permissions(self):
        contents = [('PDF-arm64.tar.gz', b'opaque authenticated binary bytes'), ('manifest.json', b'{}'), ('empty', b'')]
        for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            with self.subTest(compression=compression):
                self.zip(contents, compression)
                destination = self.root / ('extracted-' + str(compression))
                paths = gate.extract_zip(self.archive, destination, {name: 100 for name, _ in contents})
                self.assertEqual(set(paths), {name for name, _ in contents})
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
                for name, data in contents:
                    self.assertEqual(paths[name].read_bytes(), data)
                    self.assertEqual(stat.S_IMODE(paths[name].stat().st_mode), 0o600)

    def test_zip64_directory_is_supported_without_large_allocation(self):
        self.zip([('one', b'ZIP64 original bytes')])
        data = self.archive.read_bytes(); offset = data.rfind(b'PK\x05\x06')
        values = struct.unpack('<4s4H2IH', data[offset:offset + 22])
        record = struct.pack('<4sQ2H2I4Q', b'PK\x06\x06', 44, 45, 45, 0, 0, 1, 1, values[5], values[6])
        locator = struct.pack('<4sIQI', b'PK\x06\x07', 0, offset, 1)
        end = struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, 0xffff, 0xffff, 0xffffffff, 0xffffffff, 0)
        self.archive.write_bytes(data[:offset] + record + locator + end)
        result = gate.extract_zip(self.archive, self.destination, {'one': 100})
        self.assertEqual(result['one'].read_bytes(), b'ZIP64 original bytes')

    def test_traversal_absolute_backslash_nul_and_extra_entries_are_rejected(self):
        for name in ('../outside', '/absolute', 'nested/file', 'bad\\name', 'name:stream', '.', 'name.'):
            with self.subTest(name=name):
                self.zip([(name, b'payload')])
                with self.assertRaises(ValueError): gate.extract_zip(self.archive, self.destination, {'safe': 100})
                self.assertFalse(self.destination.exists())
        self.zip([('badXname', b'payload')])
        self.archive.write_bytes(self.archive.read_bytes().replace(b'badXname', b'bad\0name'))
        with self.assertRaises(ValueError): gate.extract_zip(self.archive, self.destination, {'bad': 100})
        self.zip([('safe', b'payload'), ('extra', b'payload')])
        with self.assertRaises(ValueError): gate.extract_zip(self.archive, self.destination, {'safe': 100})

    def test_duplicate_casefold_and_unicode_aliases_are_refused(self):
        for names in (('same', 'same'), ('Name', 'name'), ('é', 'e\u0301')):
            with self.subTest(names=names):
                self.zip([(name, b'payload') for name in names])
                with self.assertRaises(ValueError):
                    gate.extract_zip(self.archive, self.destination, {name: 100 for name in names})

    def test_links_special_files_encryption_and_other_compression_are_refused(self):
        for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFDIR):
            entry = zipfile.ZipInfo('safe'); entry.create_system = 3; entry.external_attr = (kind | 0o600) << 16
            self.zip([(entry, b'target')])
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                gate.extract_zip(self.archive, self.destination, {'safe': 100})
        self.zip([('safe', b'data')], zipfile.ZIP_BZIP2)
        with self.assertRaises(ValueError): gate.extract_zip(self.archive, self.destination, {'safe': 100})
        self.zip([('safe', b'data')])
        data = bytearray(self.archive.read_bytes())
        struct.pack_into('<H', data, data.index(b'PK\x03\x04') + 6, 1)
        struct.pack_into('<H', data, data.index(b'PK\x01\x02') + 8, 1)
        self.archive.write_bytes(data)
        with self.assertRaises(ValueError): gate.extract_zip(self.archive, self.destination, {'safe': 100})

    def test_limits_and_disk_preflight_fail_before_output_is_created(self):
        self.zip([('one', b'12345'), ('two', b'67890')])
        for expected, total in [({'one': 4, 'two': 8}, 8), ({'one': 8, 'two': 8}, 8)]:
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                gate.extract_zip(self.archive, self.destination, expected, total_limit=total)
            self.assertFalse(self.destination.exists())
        with patch.object(gate.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 0})()):
            with self.assertRaisesRegex(ValueError, 'free space'):
                gate.extract_zip(self.archive, self.destination, {'one': 100, 'two': 100})
        self.assertFalse(self.destination.exists())

    def test_crc_failure_removes_only_its_new_destination(self):
        self.zip([('one', b'UNIQUE PAYLOAD')], zipfile.ZIP_STORED)
        self.archive.write_bytes(self.archive.read_bytes().replace(b'UNIQUE PAYLOAD', b'CHANGED BYTES!'))
        with self.assertRaises((ValueError, zipfile.BadZipFile)):
            gate.extract_zip(self.archive, self.destination, {'one': 100})
        self.assertFalse(self.destination.exists())
        self.destination.mkdir(); sentinel = self.destination / 'existing'; sentinel.write_bytes(b'preserve')
        with self.assertRaises(ValueError): gate.extract_zip(self.archive, self.destination, {'one': 100})
        self.assertEqual(sentinel.read_bytes(), b'preserve')

    def test_central_directory_limits_precede_zip_allocation(self):
        self.zip([('one', b'data')]); original = self.archive.read_bytes()
        for relative, format_, value in [(10, '<H', 5000), (12, '<I', 0x7fffffff), (16, '<I', 0x7fffffff)]:
            data = bytearray(original); offset = data.rfind(b'PK\x05\x06')
            struct.pack_into(format_, data, offset + relative, value); self.archive.write_bytes(data)
            with self.subTest(relative=relative), patch.object(gate.zipfile, 'ZipFile', side_effect=AssertionError('must not allocate')):
                with self.assertRaises(ValueError): gate.extract_zip(self.archive, self.destination, {'one': 100})
        self.assertFalse(self.destination.exists())

    def test_archive_change_and_nonregular_inputs_are_refused_without_clobber(self):
        self.zip([('one', b'data')]); original_fsync = os.fsync
        def changed(fd):
            original_fsync(fd)
            with self.archive.open('ab') as stream: stream.write(b'x')
        with patch.object(gate.os, 'fsync', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed'):
                gate.extract_zip(self.archive, self.destination, {'one': 100})
        self.assertFalse(self.destination.exists())
        self.archive.unlink(); os.mkfifo(self.archive)
        with self.assertRaises(ValueError): gate.extract_zip(self.archive, self.destination, {'one': 100})
        self.archive.unlink(); self.zip([('one', b'data')])
        existing = self.root / 'existing'; existing.mkdir(); (existing / 'keep').write_bytes(b'preserve')
        self.destination.symlink_to(existing, target_is_directory=True)
        with self.assertRaises(ValueError): gate.extract_zip(self.archive, self.destination, {'one': 100})
        self.assertEqual((existing / 'keep').read_bytes(), b'preserve')

    def test_source_and_installer_authenticate_without_extracting_or_running(self):
        files = self.source_tar(changes={'docs/introdução.md': 'Fonte Unicode preservada.\n'.encode()})
        result = self.verify()
        self.assertEqual(result['sourceCommit'], self.commit)
        self.assertTrue(result['sourceManifestVerified'])
        self.assertEqual(result['sourceFileCount'], len(files))
        self.assertEqual(result['installerSHA256'], hashlib.sha256(self.installer).hexdigest())
        self.assertEqual(result['sourceArchiveSHA256'], hashlib.sha256((self.source / 'PDF-source.tar.gz').read_bytes()).hexdigest())
        self.assertEqual(set(path.name for path in self.source.iterdir()), {'PDF-source.tar.gz', 'PDF-source.tar.gz.sha256'})

    def test_source_hash_build_identity_and_dirty_tree_are_mandatory(self):
        self.source_tar()
        checksum = self.source / 'PDF-source.tar.gz.sha256'
        checksum.write_text('0' * 64 + '  PDF-source.tar.gz\n')
        with self.assertRaisesRegex(ValueError, 'SHA-256'): self.verify()
        for change in ({'commit': 'b' * 40}, {'working_tree_dirty': True}, {'working_tree_dirty': 0}):
            build = {'source_archive_format': 1, 'commit': self.commit, 'working_tree_dirty': False}; build.update(change)
            self.source_tar(build=build)
            with self.subTest(change=change), self.assertRaises(ValueError): self.verify()
        self.source_tar(build=b'{"source_archive_format":1,"commit":"' + self.commit.encode() + b'","working_tree_dirty":true,"working_tree_dirty":false}')
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.verify()

    def test_source_manifest_must_cover_all_files_with_exact_hashes(self):
        files = self.source_tar()
        original = files['SHA256SUMS']
        cases = [original.replace(b'README.md', b'missing.md'), original + original.splitlines(keepends=True)[0],
                 b'0' * 64 + original[64:], original + b'0' * 64 + b'  SHA256SUMS\n']
        for sums in cases:
            self.source_tar(sums=sums)
            with self.subTest(sums=sums[:70]), self.assertRaises(ValueError): self.verify()

    def test_source_tar_refuses_links_paths_duplicates_and_oversized_expansion(self):
        for name, kind in [('PDF/../escape', tarfile.REGTYPE), ('/PDF/escape', tarfile.REGTYPE),
                           ('PDF/link', tarfile.SYMTYPE), ('PDF/hard', tarfile.LNKTYPE),
                           ('PDF/fifo', tarfile.FIFOTYPE), ('PDF/folder', tarfile.DIRTYPE),
                           ('PDF/README.md', tarfile.REGTYPE), ('PDF/readme.md', tarfile.REGTYPE)]:
            member = tarfile.TarInfo(name); member.type = kind; member.linkname = 'README.md'
            self.source_tar(extra=[(member, b'')])
            with self.subTest(name=name, kind=kind), self.assertRaises(ValueError): self.verify()
        self.source_tar(changes={'large.txt': b'0' * 8192})
        with patch.object(gate, 'MAX_SOURCE', 2048):
            with self.assertRaises(ValueError): self.verify()
        with patch.object(gate, 'MAX_FILE', 4096):
            with self.assertRaises(ValueError): self.verify()

    def test_source_truncation_and_nonregular_archive_are_refused(self):
        self.source_tar(); archive = self.source / 'PDF-source.tar.gz'
        archive.write_bytes(archive.read_bytes()[:-8]); self.checksum()
        with self.assertRaises((ValueError, EOFError, tarfile.TarError)): self.verify()
        archive.unlink(); os.mkfifo(archive)
        with self.assertRaises(ValueError): self.verify()
        archive.unlink(); archive.symlink_to(self.binary / 'install-binary.sh')
        with self.assertRaises(OSError): self.verify()

    def test_source_inventory_rejects_prefetched_tail_and_concatenated_archives(self):
        self.source_tar(); archive = self.source / 'PDF-source.tar.gz'
        original = archive.read_bytes(); first_tar = gzip.decompress(original)
        with tarfile.open(fileobj=io.BytesIO(first_tar), mode='r:') as source:
            last = source.getmembers()[-1]
            member_end = last.offset_data + ((last.size + 511) // 512) * 512
        hidden = io.BytesIO()
        with tarfile.open(fileobj=hidden, mode='w') as source:
            member = tarfile.TarInfo('PDF/undeclared.py'); member.size = 6
            source.addfile(member, io.BytesIO(b'unsafe'))
        second_tar = hidden.getvalue()
        cases = {
            'same-gzip-second-tar': gzip.compress(first_tar + second_tar),
            'concatenated-gzip': original + gzip.compress(second_tar),
            'buffered-nonzero-tail': gzip.compress(first_tar[:member_end + 1024] + b'UNDECLARED'),
            # TarFile.next can silently stop at this invalid header; it must
            # not approve the earlier inventory even if the rest is zero.
            'invalid-header': gzip.compress(first_tar[:member_end] + b'X' * 512 + b'\0' * 1024),
            'missing-terminator': gzip.compress(first_tar[:member_end]),
            'one-zero-block': gzip.compress(first_tar[:member_end + 512]),
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                archive.write_bytes(data); self.checksum()
                with self.assertRaises(ValueError): self.verify()
        # Standard zero padding, including extra gzip-compressed padding, is
        # still valid and is included in the bounded expanded-byte count.
        for data in (original, original + gzip.compress(b'\0' * 512)):
            archive.write_bytes(data); self.checksum()
            self.assertTrue(self.verify()['sourceManifestVerified'])
        self.assertFalse((self.source / 'PDF').exists())

    def test_installer_must_match_source_bytes_and_authenticated_manifest(self):
        self.source_tar()
        external = self.binary / 'install-binary.sh'
        external.write_bytes(self.installer.replace(b'exit 99', b'exit 00'))
        with self.assertRaisesRegex(ValueError, 'installer differs'): self.verify()
        external.write_bytes(self.installer)
        for field, value in [('size', len(self.installer) + 1), ('sha256', '0' * 64), ('type', 'symlink')]:
            manifest = copy.deepcopy(self.manifest); manifest['files']['install-binary.sh'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.verify(manifest)


if __name__ == '__main__':
    unittest.main()
