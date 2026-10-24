"""Real Java regression and bounded structural tests for Mach-O containers."""
import base64
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest

from macho_format import is_macho


ARM64 = 0x0100000c
X86_64 = 0x01000007


def thin(cpu=ARM64, subtype=0, endian='<', bits=64):
    magic = 0xfeedfacf if bits == 64 else 0xfeedface
    data = struct.pack(endian + '7I', magic, cpu, subtype, 1, 0, 0, 0)
    return data + (b'\0' * 4 if bits == 64 else b'')


def universal(endian='>', bits=32):
    entry_size = 20 if bits == 32 else 32
    magic = 0xcafebabe if bits == 32 else 0xcafebabf
    payloads = [thin(ARM64), thin(X86_64, subtype=3)]
    data = bytearray(256 + len(payloads[-1]))
    data[:8] = struct.pack(endian + 'II', magic, 2)
    for index, (cpu, subtype, offset, payload) in enumerate([
            (ARM64, 0, 128, payloads[0]), (X86_64, 3, 256, payloads[1])]):
        entry = (struct.pack(endian + '5I', cpu, subtype, offset, len(payload), 4)
                 if bits == 32 else struct.pack(endian + 'IIQQII', cpu, subtype, offset, len(payload), 4, 0))
        data[8 + index * entry_size:8 + (index + 1) * entry_size] = entry
        data[offset:offset + len(payload)] = payload
    return data


class MachOFormatTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-macho-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'candidate'

    def identify(self, data):
        self.path.write_bytes(data)
        return is_macho(self.path)

    def test_thin_headers_cover_both_widths_and_byte_orders(self):
        for endian in ('>', '<'):
            for bits in (32, 64):
                with self.subTest(endian=endian, bits=bits):
                    self.assertTrue(self.identify(thin(cpu=12 if bits == 32 else ARM64, endian=endian, bits=bits)))

    def test_universal_headers_cover_fat32_fat64_and_both_byte_orders(self):
        for endian in ('>', '<'):
            for bits in (32, 64):
                with self.subTest(endian=endian, bits=bits):
                    self.assertTrue(self.identify(universal(endian, bits)))

    def test_real_java_class_with_same_magic_is_not_a_universal_binary(self):
        # Unchanged class from the official veraPDF cli-1.30.3.jar:
        # org/verapdf/gf/model/impl/pd/colors/GFPDDeviceRGB.class.
        # JAR SHA256 4c8acbaeb16405456c8d6d76deac8cf40d94618cb4e33aedf44e51ee1b68be91.
        # The 1,100-byte class even fits the bogus 52-entry FAT32 table implied
        # by its Java major version, so checking table length alone is unsafe.
        data = base64.b64decode(
            'yv66vgAAADQALgcAAgEAMW9yZy92ZXJhcGRmL2dmL21vZGVsL2ltcGwvcGQvY29sb3JzL0dGUEREZXZpY2VSR0IIAAQBAAtQRERldmljZVJHQgoABgAHBwAIDAAJAAoBADJvcmcvdmVyYXBkZi9nZi9tb2RlbC9pbXBsL3BkL2NvbG9ycy9HRlBEQ29sb3JTcGFjZQEABjxpbml0PgEAOShMb3JnL3ZlcmFwZGYvcGQvY29sb3JzL1BEQ29sb3JTcGFjZTtMamF2YS9sYW5nL1N0cmluZzspVgkAAQAMDAANAA4BAAhJTlNUQU5DRQEAJ0xvcmcvdmVyYXBkZi9tb2RlbC9wZGxheWVyL1BERGV2aWNlUkdCOwkAAQAQDAARAA4BABJJTkhFUklURURfSU5TVEFOQ0UJABMAFAcAFQwADQAWAQAhb3JnL3ZlcmFwZGYvcGQvY29sb3JzL1BERGV2aWNlUkdCAQAjTG9yZy92ZXJhcGRmL3BkL2NvbG9ycy9QRERldmljZVJHQjsKAAEAGAwACQAZAQAmKExvcmcvdmVyYXBkZi9wZC9jb2xvcnMvUEREZXZpY2VSR0I7KVYJABMAGwwAEQAWBwAdAQAlb3JnL3ZlcmFwZGYvbW9kZWwvcGRsYXllci9QRERldmljZVJHQgEAD0RFVklDRV9SR0JfVFlQRQEAEkxqYXZhL2xhbmcvU3RyaW5nOwEADUNvbnN0YW50VmFsdWUBAARDb2RlAQAPTGluZU51bWJlclRhYmxlAQASTG9jYWxWYXJpYWJsZVRhYmxlAQAEdGhpcwEAM0xvcmcvdmVyYXBkZi9nZi9tb2RlbC9pbXBsL3BkL2NvbG9ycy9HRlBERGV2aWNlUkdCOwEADnNpbXBsZVBET2JqZWN0AQALZ2V0SW5zdGFuY2UBACkoKUxvcmcvdmVyYXBkZi9tb2RlbC9wZGxheWVyL1BERGV2aWNlUkdCOwEAFGdldEluaGVyaXRlZEluc3RhbmNlAQAIPGNsaW5pdD4BAAMoKVYBAApTb3VyY2VGaWxlAQASR0ZQRERldmljZVJHQi5qYXZhACEAAQAGAAEAHAADABoADQAOAAAAGgARAA4AAAAZAB4AHwABACAAAAACAAMABAACAAkAGQABACEAAABAAAMAAgAAAAgqKxIDtwAFsQAAAAIAIgAAAAoAAgAAACYABwAnACMAAAAWAAIAAAAIACQAJQAAAAAACAAmABYAAQAJACcAKAABACEAAAAcAAEAAAAAAASyAAuwAAAAAQAiAAAABgABAAAAKgAJACkAKAABACEAAAAcAAEAAAAAAASyAA+wAAAAAQAiAAAABgABAAAALgAIACoAKwABACEAAAA3AAMAAAAAABu7AAFZsgAStwAXswALuwABWbIAGrcAF7MAD7EAAAABACIAAAAKAAIAAAAdAA0AHwABACwAAAACAC0=')
        self.assertEqual(hashlib.sha256(data).hexdigest(), 'd602e737ae881721fccabce0789b27c868725375f2bec4f960e9f50fd6e856f3')
        self.assertEqual(data[:4], b'\xca\xfe\xba\xbe')
        self.assertFalse(self.identify(data))

    def test_truncated_and_oversized_headers_are_rejected(self):
        cases = [b'', b'\xca\xfe\xba\xbe', thin()[:31],
                 struct.pack('>II', 0xcafebabe, 0), struct.pack('>II', 0xcafebabe, 0xffffffff),
                 universal()[:30], universal()[:270]]
        for data in cases:
            with self.subTest(size=len(data)):
                self.assertFalse(self.identify(data))

    def test_invalid_offsets_sizes_alignment_and_slice_headers_are_rejected(self):
        # Mutate FAT32 entries, keeping the rest of the file intact.
        for location, value in [(16, 0), (16, 129), (16, 0xffffffff),
                                (20, 0), (20, 0xffffffff), (24, 32),
                                (8, X86_64), (12, 8), (36, 128)]:
            data = universal(); struct.pack_into('>I', data, location, value)
            with self.subTest(location=location, value=value):
                self.assertFalse(self.identify(data))
        data = universal(); data[128:132] = b'\xca\xfe\xba\xbe'
        self.assertFalse(self.identify(data))
        data = universal(bits=64); struct.pack_into('>I', data, 36, 1)
        self.assertFalse(self.identify(data))

    def test_overlapping_slices_and_duplicate_architectures_are_rejected(self):
        data = universal(); struct.pack_into('>I', data, 20, 160)
        self.assertFalse(self.identify(data))
        data = universal(); data[28:36] = data[8:16]; data[256:288] = thin()
        self.assertFalse(self.identify(data))

    def test_load_command_area_must_fit_its_own_slice(self):
        for commands, size in [(1, 0), (0, 8), (2, 8), (1, 0xffffffff)]:
            data = bytearray(thin()); struct.pack_into('<II', data, 16, commands, size)
            with self.subTest(commands=commands, size=size):
                self.assertFalse(self.identify(data))
        # A bounded real-shaped load command remains a Mach-O candidate for
        # the mandatory otool/lipo validation in the packaging stage.
        data = bytearray(thin()) + struct.pack('<II', 0x1b, 24) + bytes(16)
        struct.pack_into('<II', data, 16, 1, 24)
        self.assertTrue(self.identify(data))

    def test_regular_files_only_and_sparse_slice_offsets_are_bounded(self):
        self.path.write_bytes(thin())
        link = self.root / 'link'; link.symlink_to(self.path)
        self.assertFalse(is_macho(link))
        fifo = self.root / 'fifo'; os.mkfifo(fifo)
        self.assertFalse(is_macho(fifo))
        self.assertFalse(is_macho(self.root))
        self.assertFalse(is_macho(self.root / 'missing'))
        # A sparse container proves that file size does not determine memory
        # consumption: only its tiny table and thin header are read.
        offset = 8 * 1024 * 1024
        with self.path.open('wb') as stream:
            stream.write(struct.pack('>II', 0xcafebabf, 1))
            stream.write(struct.pack('>IIQQII', ARM64, 0, offset, 32, 12, 0))
            stream.seek(offset); stream.write(thin())
        self.assertTrue(is_macho(self.path))


if __name__ == '__main__':
    unittest.main()
