"""Bounded local delivery validation. No network, code loading or execution."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import tarfile
import unicodedata
import zipfile
import zlib

MAX_DELIVERY = 12 * 1024 ** 3
MAX_SOURCE = 256 * 1024 ** 2
MAX_SOURCE_PAYLOAD = 240 * 1024 ** 2
# Source transport also contains three bounded JSON reports and a checksum.
# Keep its ZIP framing allowance separate from unrelated artifact limits.
MAX_SOURCE_TRANSPORT = 272 * 1024 ** 2
MAX_FILE = 32 * 1024 ** 2
MAX_MEMBERS = 10_000
CHUNK = 1024 * 1024


class ArchiveFailure(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ArchiveFailure(message)


def _name(name, *, flat=False):
    require(isinstance(name, str) and name and len(name.encode('utf-8')) <= 4096,
            'Invalid archive member name.')
    require(not any(ord(char) < 32 or ord(char) == 127 for char in name)
            and '\\' not in name and ':' not in name and not name.startswith('/'),
            'Unsafe archive member name.')
    parts = name.split('/')
    require(all(part not in ('', '.', '..') and part == part.strip() and not part.endswith('.') for part in parts)
            and (not flat or len(parts) == 1), 'Unsafe archive member path.')
    return unicodedata.normalize('NFC', name).casefold()


def _open_regular(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    stream = os.fdopen(fd, 'rb')
    try:
        metadata = os.fstat(fd)
        require(stat.S_ISREG(metadata.st_mode) and 0 < metadata.st_size <= limit,
                'Input is not a bounded regular file.')
        return stream, metadata
    except BaseException:
        stream.close()
        raise


def _unchanged(stream, before):
    after = os.fstat(stream.fileno())
    require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Input changed during verification.')


def _small(path, limit):
    stream, before = _open_regular(path, limit)
    with stream:
        data = stream.read(limit + 1)
        require(len(data) == before.st_size, 'Incomplete input.')
        _unchanged(stream, before)
        return data


def _zip_directory(stream, size, count):
    """Bound central-directory allocation before constructing ZipFile (ZIP64 too)."""
    length = min(size, 65_557)
    stream.seek(size - length)
    tail = stream.read(length)
    position = tail.rfind(b'PK\x05\x06')
    require(position >= 0 and position + 22 <= len(tail), 'ZIP end record is missing.')
    values = struct.unpack('<4s4H2IH', tail[position:position + 22])
    _, disk, directory_disk, disk_entries, entries, directory_size, directory_offset, comment = values
    require(position + 22 + comment == len(tail) and disk == directory_disk == 0,
            'Multipart or ambiguous ZIP is refused.')
    end_offset = size - length + position
    boundary = end_offset
    if entries == 0xffff or disk_entries == 0xffff or directory_size == 0xffffffff or directory_offset == 0xffffffff:
        require(end_offset >= 20, 'ZIP64 locator is missing.')
        stream.seek(end_offset - 20)
        locator = stream.read(20)
        require(len(locator) == 20, 'ZIP64 locator is truncated.')
        signature, disk64, offset64, disks = struct.unpack('<4sIQI', locator)
        require(signature == b'PK\x06\x07' and disk64 == 0 and disks == 1
                and offset64 + 56 <= end_offset - 20, 'Invalid ZIP64 locator.')
        stream.seek(offset64)
        record = stream.read(56)
        require(len(record) == 56, 'ZIP64 end record is truncated.')
        signature, record_size, _, _, disk, directory_disk, disk_entries, entries, directory_size, directory_offset = struct.unpack('<4sQ2H2I4Q', record)
        require(signature == b'PK\x06\x06' and 44 <= record_size <= MAX_FILE
                and offset64 + 12 + record_size == end_offset - 20 and disk == directory_disk == 0,
                'Invalid ZIP64 end record.')
        boundary = offset64
    require(entries == disk_entries == count and 0 < entries <= MAX_MEMBERS
            and 0 < directory_size <= MAX_FILE and directory_offset + directory_size == boundary,
            'ZIP central directory or inventory exceeds the declared bounds.')
    stream.seek(0)


def extract_zip(archive: Path, destination: Path, expected: dict[str, int], total_limit=MAX_DELIVERY) -> dict[str, Path]:
    """Extract exactly the flat allowlist; expected values are per-file byte caps."""
    require(type(total_limit) is int and 0 < total_limit <= MAX_DELIVERY
            and isinstance(expected, dict) and 0 < len(expected) <= MAX_MEMBERS,
            'Invalid ZIP extraction limits.')
    normalized = [_name(name, flat=True) for name in expected]
    require(len(set(normalized)) == len(expected)
            and all(type(value) is int and 0 < value <= total_limit for value in expected.values()),
            'Ambiguous allowlist or invalid member limit.')
    destination = Path(destination)
    parent = destination.parent.resolve(strict=True)
    target = parent / destination.name
    _name(destination.name, flat=True)
    require(not os.path.lexists(target), 'Extraction destination already exists.')
    stream, before = _open_regular(archive, total_limit + MAX_FILE + 65_557)
    created = None
    directory_fd = None
    try:
        with stream:
            _zip_directory(stream, before.st_size, len(expected))
            with zipfile.ZipFile(stream) as source:
                entries = source.infolist()
                require(len(entries) == len(expected), 'ZIP inventory differs from the allowlist.')
                names = set(); total = 0
                for item in entries:
                    name = item.orig_filename
                    key = _name(name, flat=True)
                    require(name == item.filename and key not in names and name in expected,
                            'Duplicate or unexpected ZIP member.')
                    names.add(key)
                    mode = (item.external_attr >> 16) & 0xffff
                    require(stat.S_IFMT(mode) in (0, stat.S_IFREG) and not item.is_dir()
                            and not item.external_attr & 0x10 and not item.flag_bits & (1 | 0x40 | 0x2000)
                            and item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                            'ZIP links, special files, encryption or compression are refused.')
                    require(0 <= item.file_size <= expected[name] and 0 <= item.compress_size <= before.st_size,
                            'ZIP member exceeds its size limit.')
                    total += item.file_size
                    require(total <= total_limit, 'ZIP expanded size exceeds the limit.')
                require(shutil.disk_usage(parent).free >= total + CHUNK + len(entries) * 4096,
                        'Insufficient free space for bounded ZIP extraction.')
                target.mkdir(mode=0o700)
                created = target.lstat()
                directory_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                require((os.fstat(directory_fd).st_dev, os.fstat(directory_fd).st_ino) == (created.st_dev, created.st_ino),
                        'Extraction destination changed.')
                for item in entries:
                    fd = os.open(item.filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=directory_fd)
                    with os.fdopen(fd, 'wb') as output, source.open(item) as input_:
                        count = 0
                        while block := input_.read(CHUNK):
                            count += len(block)
                            require(count <= item.file_size and count <= expected[item.filename],
                                    'ZIP member exceeded its declared size while reading.')
                            output.write(block)
                        require(count == item.file_size, 'ZIP member has an incomplete payload.')
                        output.flush(); os.fsync(output.fileno())
                _unchanged(stream, before)
                require((target.lstat().st_dev, target.lstat().st_ino) == (created.st_dev, created.st_ino),
                        'Extraction destination changed.')
                return {name: target / name for name in expected}
    except BaseException as error:
        if created is not None:
            try:
                current = target.lstat()
                if stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                    shutil.rmtree(target)
            except FileNotFoundError:
                pass
        if isinstance(error, (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, zlib.error, NotImplementedError, UnicodeError)):
            raise ArchiveFailure('ZIP structure, compression or CRC validation failed.') from None
        raise
    finally:
        stream.close()
        if directory_fd is not None:
            os.close(directory_fd)


class _BoundedReader:
    def __init__(self, stream, limit):
        self.stream = stream; self.limit = limit; self.count = 0

    def read(self, size=-1):
        allowed = self.limit - self.count + 1
        data = self.stream.read(min(allowed, size) if size >= 0 else allowed)
        self.count += len(data)
        require(self.count <= self.limit, 'Uncompressed source TAR exceeds its byte limit.')
        return data


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Source build metadata has duplicate keys.')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def _verify_source_and_installer(source_directory, binary_directory, commit, distribution_manifest, required_source_files=()) -> dict:
    """Inspect/hash the source TAR in memory streams; never extract or execute it."""
    require(isinstance(commit, str) and re.fullmatch('[0-9a-f]{40}', commit) is not None,
            'An exact source commit is required.')
    source_directory, binary_directory = Path(source_directory), Path(binary_directory)
    checksum = _small(source_directory / 'PDF-source.tar.gz.sha256', 256)
    match = re.fullmatch(rb'([0-9a-f]{64})  PDF-source\.tar\.gz\n', checksum)
    require(match is not None, 'Source archive checksum sidecar is invalid.')
    archive_hash = match.group(1).decode('ascii')
    stream, before = _open_regular(source_directory / 'PDF-source.tar.gz', MAX_SOURCE)
    hashes = {}; sizes = {}; normalized = set(); captured = {}; count = 0; member_end = 0; payload_bytes = 0
    with stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(CHUNK), b''):
            digest.update(block)
        require(digest.hexdigest() == archive_hash, 'Source archive SHA-256 mismatch.')
        stream.seek(0)
        with gzip.GzipFile(fileobj=stream, mode='rb') as compressed:
            bounded = _BoundedReader(compressed, MAX_SOURCE)
            with tarfile.open(fileobj=bounded, mode='r|') as source:
                for item in source:
                    count += 1
                    require(count <= MAX_MEMBERS and item.isfile() and item.sparse is None
                            and not any(key.startswith('GNU.sparse') for key in item.pax_headers)
                            and 0 <= item.size <= MAX_FILE, 'Source TAR member type, size or count is invalid.')
                    payload_bytes += item.size
                    require(payload_bytes <= MAX_SOURCE_PAYLOAD, 'Source TAR payload exceeds its byte limit.')
                    key = _name(item.name)
                    require(item.name.startswith('PDF/') and key not in normalized,
                            'Source TAR has a foreign or duplicate member.')
                    normalized.add(key)
                    name = item.name[4:]
                    content_hash = hashlib.sha256(); length = 0; pieces = []
                    keep = name in ('BUILD-INFO.json', 'SHA256SUMS', 'scripts/install-binary.sh')
                    with source.extractfile(item) as content:
                        while block := content.read(CHUNK):
                            length += len(block)
                            require(length <= item.size, 'Source member exceeded its declared size.')
                            content_hash.update(block)
                            if keep: pieces.append(block)
                    require(length == item.size, 'Source TAR member is truncated.')
                    hashes[name] = content_hash.hexdigest()
                    if name in required_source_files: sizes[name] = length
                    if keep: captured[name] = b''.join(pieces)
                    member_end = item.offset_data + ((item.size + 511) // 512) * 512
        # TarFile may prefetch past its first zero header, and may silently stop
        # at a later invalid header. Re-read the same authenticated descriptor,
        # bounded, so neither prefetched bytes nor a second gzip/TAR can escape
        # the exact inventory. Only zero end-of-archive padding is allowed.
        stream.seek(0)
        with gzip.GzipFile(fileobj=stream, mode='rb') as compressed:
            bounded = _BoundedReader(compressed, MAX_SOURCE)
            remaining = member_end
            while remaining:
                block = bounded.read(min(CHUNK, remaining))
                require(bool(block), 'Source TAR member data is truncated.')
                remaining -= len(block)
            padding = 0
            while block := bounded.read(CHUNK):
                require(block.count(0) == len(block), 'Source TAR has data outside its verified inventory.')
                padding += len(block)
            require(padding >= 1024, 'Source TAR end-of-archive padding is incomplete.')
            expanded = bounded.count
        _unchanged(stream, before)
    require(set(captured) == {'BUILD-INFO.json', 'SHA256SUMS', 'scripts/install-binary.sh'},
            'Source archive lacks its build metadata, checksums or installer.')
    build = _json(captured['BUILD-INFO.json'])
    require(isinstance(build, dict) and type(build.get('source_archive_format')) is int
            and build['source_archive_format'] == 1 and build.get('commit') == commit
            and build.get('working_tree_dirty') is False, 'Source build identity or clean-tree evidence differs.')
    manifest_bytes = captured['SHA256SUMS']
    require(manifest_bytes.endswith(b'\n'), 'Source checksum inventory is incomplete.')
    manifest = {}
    for line in manifest_bytes.splitlines():
        require(len(line) > 66 and re.fullmatch(rb'[0-9a-f]{64}', line[:64]) is not None and line[64:66] == b'  ',
                'Source checksum record is invalid.')
        name = line[66:].decode('utf-8')
        _name(name)
        require(name not in manifest and name != 'SHA256SUMS', 'Duplicate or self-referential source checksum.')
        manifest[name] = line[:64].decode('ascii')
    require(manifest == {name: value for name, value in hashes.items() if name != 'SHA256SUMS'},
            'Source checksum inventory differs from actual source files.')
    require(isinstance(distribution_manifest, dict) and type(distribution_manifest.get('schemaVersion')) is int
            and distribution_manifest['schemaVersion'] == 1
            and distribution_manifest.get('commit') == commit and distribution_manifest.get('architecture') == 'arm64'
            and isinstance(distribution_manifest.get('files'), dict), 'Authenticated distribution manifest identity differs.')
    entry = distribution_manifest['files'].get('install-binary.sh')
    require(isinstance(entry, dict) and entry.get('type') == 'file' and type(entry.get('size')) is int
            and 0 < entry['size'] <= MAX_FILE and isinstance(entry.get('sha256'), str)
            and re.fullmatch('[0-9a-f]{64}', entry['sha256']) is not None, 'Installer manifest entry is invalid.')
    installer = _small(binary_directory / 'install-binary.sh', MAX_FILE)
    installer_hash = hashlib.sha256(installer).hexdigest()
    require(installer == captured['scripts/install-binary.sh'] and len(installer) == entry['size']
            and installer_hash == entry['sha256'], 'External installer differs from authenticated source or binary manifest.')
    require(set(sizes) == set(required_source_files), 'Source archive lacks required validation files.')
    return {'additionalSourceFiles': {name: {'bytes': sizes[name], 'sha256': hashes[name]} for name in sizes},
            'sourceArchiveSHA256': archive_hash, 'sourceArchiveBytes': before.st_size,
            'installerSHA256': installer_hash, 'installerBytes': len(installer),
            'sourceCommit': commit, 'sourceFileCount': count,
            'sourceUncompressedBytes': expanded, 'sourceManifestVerified': True, 'sourceWorkingTreeDirty': False}


def verify_source_and_installer(source_directory, binary_directory, commit, distribution_manifest, *, required_source_files=()) -> dict:
    """Validate source/installer with controlled diagnostics for malformed archives."""
    try:
        return _verify_source_and_installer(source_directory, binary_directory, commit, distribution_manifest, required_source_files)
    except (tarfile.TarError, gzip.BadGzipFile, EOFError, zlib.error, UnicodeError, json.JSONDecodeError, RecursionError):
        raise ArchiveFailure('Source TAR, gzip stream or build metadata is invalid.') from None
