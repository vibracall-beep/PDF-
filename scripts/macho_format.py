"""Bounded structural Mach-O identification, without launching Apple tools.

FAT_MAGIC and Java's class-file magic are both CAFEBABE. A four-byte test
cannot distinguish them. This classifier checks the universal container and
its thin Mach-O headers; architecture and load-command validation still belong
to the existing lipo/otool/codesign checks performed by the packager.
"""
from __future__ import annotations

import os
import stat
import struct


_THIN = {
    b'\xfe\xed\xfa\xce': ('>', 28),
    b'\xce\xfa\xed\xfe': ('<', 28),
    b'\xfe\xed\xfa\xcf': ('>', 32),
    b'\xcf\xfa\xed\xfe': ('<', 32),
}
_FAT = {
    b'\xca\xfe\xba\xbe': ('>', 20),
    b'\xbe\xba\xfe\xca': ('<', 20),
    b'\xca\xfe\xba\xbf': ('>', 32),
    b'\xbf\xba\xfe\xca': ('<', 32),
}
# More than the supported CPU/subtype combinations, with a 128 KiB table cap.
_MAX_ARCHITECTURES = 4096


def _thin_header(descriptor, offset, size):
    if size < 28:
        return None
    data = os.pread(descriptor, min(size, 32), offset)
    format_ = _THIN.get(data[:4])
    if format_ is None:
        return None
    endian, header_size = format_
    if len(data) < header_size:
        return None
    _, cpu, subtype, filetype, commands, command_bytes, _ = struct.unpack(endian + '7I', data[:28])
    # Load commands have at least cmd/cmdsize (8 bytes); their declared area
    # must fit inside this slice. Do not allocate or read the executable body.
    if (not cpu or not filetype or command_bytes > size - header_size
            or commands > command_bytes // 8 or bool(commands) != bool(command_bytes)):
        return None
    return cpu, subtype


def _identify(descriptor, size):
    header = os.pread(descriptor, 8, 0)
    if header[:4] in _THIN:
        return _thin_header(descriptor, 0, size) is not None
    format_ = _FAT.get(header[:4])
    if format_ is None or len(header) != 8:
        return False
    endian, entry_size = format_
    count = struct.unpack(endian + 'I', header[4:])[0]
    table_end = 8 + count * entry_size
    if not 0 < count <= _MAX_ARCHITECTURES or table_end > size:
        return False
    table = os.pread(descriptor, count * entry_size, 8)
    if len(table) != count * entry_size:
        return False
    slices = []
    architectures = set()
    for index in range(count):
        entry = table[index * entry_size:(index + 1) * entry_size]
        if entry_size == 20:
            cpu, subtype, offset, length, alignment = struct.unpack(endian + '5I', entry)
            max_alignment = 31
        else:
            cpu, subtype, offset, length, alignment, reserved = struct.unpack(endian + 'IIQQII', entry)
            if reserved:
                return False
            max_alignment = 63
        if (alignment > max_alignment or offset < table_end or length < 28
                or offset > size or length > size - offset
                or offset % (1 << alignment)):
            return False
        architecture = cpu, subtype
        if architecture in architectures or _thin_header(descriptor, offset, length) != architecture:
            return False
        architectures.add(architecture)
        slices.append((offset, offset + length))
    slices.sort()
    return all(previous[1] <= current[0] for previous, current in zip(slices, slices[1:]))


def is_macho(path) -> bool:
    """Identify a regular thin/universal Mach-O, rejecting links and special files.

    This is a classifier, not an architecture or signature approval. Its
    positive result must still go through the packager's mandatory checks.
    Reads are bounded by the FAT table and at most 32 bytes per slice.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 28:
            return False
        result = _identify(descriptor, before.st_size)
        after = os.fstat(descriptor)
        unchanged = (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        return result and unchanged
    except (OSError, OverflowError, struct.error):
        return False
    finally:
        os.close(descriptor)
