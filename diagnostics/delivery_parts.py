"""Bounded byte splitting and a local macOS reassembly script.

This module neither downloads nor uploads assets and never executes a package.
The approved archive is read through regular-file descriptors and stays intact.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
import stat


ARCHIVE_NAME = 'PDF-arm64.tar.gz'
MAX_BYTES = 12 * 1024 ** 3
ASSET_LIMIT = 2 * 1024 ** 3
PART_BYTES = 1024 ** 3
MAX_PARTS = 1000
READ_BYTES = 4 * 1024 ** 2


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f'{name} is outside the permitted range.')
    return value


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError('A lowercase SHA-256 digest is required.')
    return value


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_source(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
            raise ValueError('The archive must be a nonempty regular file of at most 12 GiB.')
        return os.fdopen(descriptor, 'rb'), info
    except BaseException:
        os.close(descriptor)
        raise


def _unchanged(stream, path, before):
    after = os.fstat(stream.fileno())
    current = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(current.st_mode) or _identity(before) != _identity(after) or _identity(before) != _identity(current):
        raise ValueError('The archive changed during the read.')


def plan_parts(path: Path, part_bytes=PART_BYTES, asset_limit=ASSET_LIMIT) -> dict:
    """Hash the whole archive and every planned part in one streaming pass."""
    asset_limit = _integer(asset_limit, 'Asset limit', 2, ASSET_LIMIT)
    part_bytes = _integer(part_bytes, 'Part size', 1, asset_limit - 1)
    path = Path(path)
    stream, before = _open_source(path)
    with stream:
        split = before.st_size >= asset_limit
        chunk_bytes = part_bytes if split else before.st_size
        count = (before.st_size + chunk_bytes - 1) // chunk_bytes
        if count > MAX_PARTS:
            raise ValueError('The delivery would require more than 1,000 parts.')
        whole = hashlib.sha256()
        parts, offset = [], 0
        for index in range(count):
            length = min(chunk_bytes, before.st_size - offset)
            remaining, digest = length, hashlib.sha256()
            while remaining:
                data = stream.read(min(READ_BYTES, remaining))
                if not data:
                    raise ValueError('The archive ended before its declared size.')
                remaining -= len(data)
                digest.update(data); whole.update(data)
            name = f'{ARCHIVE_NAME}.part-{index + 1:06d}' if split else ARCHIVE_NAME
            parts.append(dict(name=name, offset=offset, bytes=length, sha256=digest.hexdigest()))
            offset += length
        if stream.read(1):
            raise ValueError('The archive grew during the read.')
        _unchanged(stream, path, before)
    return dict(name=ARCHIVE_NAME, bytes=before.st_size, sha256=whole.hexdigest(),
                mode='byte-parts' if split else 'single', parts=parts)


def _record(record):
    if not isinstance(record, dict) or set(record) != {'name', 'offset', 'bytes', 'sha256'}:
        raise ValueError('Unexpected part record.')
    record = dict(record)
    name = record['name']
    if not isinstance(name, str) or (name != ARCHIVE_NAME and re.fullmatch(re.escape(ARCHIVE_NAME) + r'\.part-[0-9]{6}', name) is None):
        raise ValueError('Unexpected part name.')
    if name != ARCHIVE_NAME and not 1 <= int(name.rsplit('-', 1)[1]) <= MAX_PARTS:
        raise ValueError('Part number is outside the permitted range.')
    offset = _integer(record['offset'], 'Part offset', 0, MAX_BYTES - 1)
    length = _integer(record['bytes'], 'Part size', 1, ASSET_LIMIT - 1)
    if offset + length > MAX_BYTES:
        raise ValueError('The part exceeds the archive limit.')
    if name == ARCHIVE_NAME and offset != 0:
        raise ValueError('A single asset must start at offset zero.')
    return name, offset, length, _digest(record['sha256'])


def materialize_part(path: Path, record: dict, destination: Path) -> Path:
    """Publish exactly the approved range, atomically and without replacement."""
    name, offset, length, expected = _record(record)
    path, destination = Path(path), Path(destination)
    if destination.name in ('', '.', '..'):
        raise ValueError('Choose a new destination filename.')
    parent = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    temporary = '.pdf-delivery-part-' + secrets.token_hex(16)
    created = None
    try:
        try:
            os.stat(destination.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError('The part destination already exists.')
        free = os.fstatvfs(parent)
        if free.f_bavail * free.f_frsize < length:
            raise OSError('Insufficient free space for this part.')
        source, before = _open_source(path)
        with source:
            if offset + length > before.st_size:
                raise ValueError('The part is outside the current archive.')
            if name == ARCHIVE_NAME and length != before.st_size:
                raise ValueError('A single asset must contain the whole archive.')
            source.seek(offset)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
            temporary_info = os.fstat(descriptor)
            created = (temporary_info.st_dev, temporary_info.st_ino)
            with os.fdopen(descriptor, 'wb') as target:
                digest, remaining = hashlib.sha256(), length
                while remaining:
                    data = source.read(min(READ_BYTES, remaining))
                    if not data:
                        raise ValueError('The archive ended inside a planned part.')
                    target.write(data); digest.update(data); remaining -= len(data)
                _unchanged(source, path, before)
                if digest.hexdigest() != expected:
                    raise ValueError('The materialized part does not match the approved SHA-256.')
                target.flush(); os.fsync(target.fileno())
            os.link(temporary, destination.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            os.fsync(parent)
        return destination
    finally:
        try:
            if created is not None:
                try:
                    current = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    if (current.st_dev, current.st_ino) == created:
                        os.unlink(temporary, dir_fd=parent)
        finally:
            os.close(parent)


def _validated_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {'name', 'bytes', 'sha256', 'mode', 'parts'}:
        raise ValueError('Unexpected delivery plan.')
    plan = dict(plan)
    if plan['name'] != ARCHIVE_NAME or plan['mode'] not in ('single', 'byte-parts'):
        raise ValueError('Unexpected archive name or storage mode.')
    length = _integer(plan['bytes'], 'Archive size', 1, MAX_BYTES)
    digest = _digest(plan['sha256'])
    records = plan['parts']
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_PARTS:
        raise ValueError('The plan has an invalid number of parts.')
    records = list(records)
    parts, offset = [], 0
    for index, record in enumerate(records):
        name, start, size, sha = _record(record)
        expected = ARCHIVE_NAME if plan['mode'] == 'single' else f'{ARCHIVE_NAME}.part-{index + 1:06d}'
        if name != expected or start != offset:
            raise ValueError('Part names and offsets must form one ordered, contiguous list.')
        parts.append((name, size, sha)); offset += size
    if offset != length:
        raise ValueError('Part sizes do not sum to the archive size.')
    if plan['mode'] == 'single' and (len(parts) != 1 or parts[0][2] != digest):
        raise ValueError('The single asset must equal the approved whole archive.')
    if plan['mode'] == 'byte-parts' and len(parts) < 2:
        raise ValueError('A divided archive requires at least two parts.')
    return length, digest, parts


def reassembly_script(plan: dict) -> bytes:
    """Produce Bash 3.2 code using only standard macOS command-line utilities."""
    length, digest, parts = _validated_plan(plan)
    if plan['mode'] != 'byte-parts':
        raise ValueError('A single asset does not require reassembly.')
    # Every inserted value has a closed grammar; no plan text is shell code.
    names = ' '.join("'" + part[0] + "'" for part in parts)
    sizes = ' '.join(str(part[1]) for part in parts)
    hashes = ' '.join("'" + part[2] + "'" for part in parts)
    script = r'''#!/bin/bash
# Reassemble verified byte parts only. This script never installs or runs PDF.
set -euo pipefail
umask 077
export LC_ALL=C
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
fail() { printf '%s\n' "$1" >&2; exit 1; }
[[ $# -le 1 ]] || fail 'Usage: bash reassemble-binary.sh [existing output directory]'
script_path=${BASH_SOURCE[0]}
case "$script_path" in /*) ;; *) script_path="$PWD/$script_path" ;; esac
[[ -f "$script_path" && ! -L "$script_path" ]] || fail 'The script must be a regular file, not a symbolic link.'
source_dir=$(cd -P -- "${script_path%/*}" && pwd -P)
output_argument=${1:-"$source_dir"}
[[ -d "$output_argument" ]] || fail 'Choose an existing output directory.'
output_dir=$(cd -P -- "$output_argument" && pwd -P)
output="$output_dir/PDF-arm64.tar.gz"
[[ ! -e "$output" && ! -L "$output" ]] || fail 'The output already exists; no file was replaced.'
parts=(__PART_NAMES__)
sizes=(__PART_SIZES__)
hashes=(__PART_HASHES__)
paths=()
hash_file() { local value; value=$(shasum -a 256 < "$1"); printf '%s' "${value%% *}"; }
for index in "${!parts[@]}"; do
    part="$source_dir/${parts[$index]}"
    [[ -f "$part" && ! -L "$part" ]] || fail 'A required part is missing, special, or a symbolic link.'
    actual_size=$(wc -c < "$part")
    [[ "$actual_size" -eq "${sizes[$index]}" ]] || fail 'A part has the wrong byte count.'
    [[ "$(hash_file "$part")" == "${hashes[$index]}" ]] || fail 'A part failed SHA-256 verification.'
    paths+=("$part")
done
temporary_dir=''
temporary_identity=''
host_system=$(uname -s)
case "$host_system" in Darwin|Linux) ;; *) fail 'Unsupported system for temporary-directory verification.' ;; esac
directory_identity() {
    if [[ "$host_system" == Darwin ]]; then
        stat -f '%d:%i' "$1"
    else
        stat -c '%d:%i' -- "$1"
    fi
}
cleanup() {
    if [[ -n "$temporary_dir" && -n "$temporary_identity" && -d "$temporary_dir" && ! -L "$temporary_dir" ]]; then
        # Bind removal to the actual working directory after cd, not merely
        # to a path that could have become a link to somebody else's files.
        (
            cd -P -- "$temporary_dir" || exit 0
            [[ "$(directory_identity .)" == "$temporary_identity" ]] || exit 0
            rm -f -- ./PDF-arm64.tar.gz
        )
        if [[ -d "$temporary_dir" && ! -L "$temporary_dir" && "$(directory_identity "$temporary_dir")" == "$temporary_identity" ]]; then
            rmdir -- "$temporary_dir"
        fi
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
temporary_dir=$(mktemp -d "$output_dir/.pdf-reassemble.XXXXXXXX")
[[ -d "$temporary_dir" && ! -L "$temporary_dir" ]] || fail 'The temporary directory changed after creation.'
temporary_identity=$(directory_identity "$temporary_dir")
temporary="$temporary_dir/PDF-arm64.tar.gz"
set -o noclobber
cat "${paths[@]}" > "$temporary"
actual_size=$(wc -c < "$temporary")
[[ "$actual_size" -eq __ARCHIVE_BYTES__ ]] || fail 'The reassembled archive has the wrong byte count.'
[[ "$(hash_file "$temporary")" == '__ARCHIVE_SHA__' ]] || fail 'The reassembled archive failed SHA-256 verification.'
# Passing the existing directory, rather than the final filename, makes ln
# atomically fail if that basename is a file, symlink, or directory already.
ln -- "$temporary" "$output_dir/"
printf '%s\n' "$output"
'''
    for marker, value in (('__PART_NAMES__', names), ('__PART_SIZES__', sizes), ('__PART_HASHES__', hashes),
                          ('__ARCHIVE_BYTES__', str(length)), ('__ARCHIVE_SHA__', digest)):
        script = script.replace(marker, value)
    return script.encode('utf-8')
