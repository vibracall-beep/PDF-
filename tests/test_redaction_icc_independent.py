"""Independent ICC review: nonstandard gamma, PDF objects and invalid inputs."""
import io
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest

import fitz
from PIL import Image, ImageCms

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run
from pdf_icc_privacy import sanitize_icc

SECRET = 'PRIVATE-68291'


def read_tags(profile):
    result = {}
    count = struct.unpack_from('>I', profile, 128)[0]
    for index in range(count):
        name, offset, size = struct.unpack_from('>4sII', profile, 132 + index * 12)
        result[name] = profile[offset:offset + size]
    return result


def rebuild(profile, changes):
    values = read_tags(profile)
    values.update(changes)
    table_size = 132 + 12 * len(values)
    table = bytearray()
    payload = bytearray()
    for name, content in values.items():
        payload += bytes(-(table_size + len(payload)) % 4)
        table += struct.pack('>4sII', name, table_size + len(payload), len(content))
        payload += content
    result = bytearray(profile[:128] + struct.pack('>I', len(values)) + table + payload)
    result += bytes(-len(result) % 4)
    result[:4] = struct.pack('>I', len(result))
    result[84:100] = bytes(16)
    return bytes(result)


def private_gamma_profile():
    original = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    description = SECRET.encode('utf-16be')
    metadata = b'mluc' + bytes(4) + struct.pack('>II4sII', 1, 12, b'ptBR', len(description), 28) + description
    changes = {b'desc': metadata, b'cprt': metadata}
    # Deliberately distinct from the default sRGB profile, and different per
    # channel. Replacing this profile with sRGB would fail the color oracle.
    for name, gamma in ((b'rTRC', 0x0180), (b'gTRC', 0x0200), (b'bTRC', 0x0280)):
        changes[name] = b'curv' + bytes(4) + struct.pack('>IH', 1, gamma)
    return rebuild(original, changes)


class IndependentICCReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='PDF independent ICC ')
        self.root = Path(self.temp.name)
        self.originals = {}

    def tearDown(self):
        for path, content in self.originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(list(self.root.glob('.pdf-output-*')), [])
        self.temp.cleanup()

    def source(self, profile, name, intent_type=True):
        target = self.root / (name + '.pdf')
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 50), SECRET)
            page.insert_text((40, 180), 'PUBLIC COLOR REVIEW')
            xref = document.get_new_xref()
            document.update_object(xref, '<< /N 3 /Alternate /DeviceRGB >>')
            document.update_stream(xref, profile)
            resources = int(document.xref_get_key(page.xref, 'Resources')[1].split()[0])
            document.xref_set_key(resources, 'ColorSpace', f'<< /Local [/ICCBased {xref} 0 R] >>')
            content = document.get_new_xref()
            document.update_object(content, '<< >>')
            document.update_stream(content, b'q /Local cs 0.2 0.5 0.7 scn 350 242 100 100 re f Q')
            document.xref_set_key(page.xref, 'Contents', '[' + ' '.join(f'{item} 0 R' for item in page.get_contents() + [content]) + ']')
            intent = document.get_new_xref()
            kind = '/Type /OutputIntent ' if intent_type else ''
            document.update_object(intent, f'<< {kind}/S /GTS_PDFA1 /DestOutputProfile {xref} 0 R /OutputCondition ({SECRET}) /OutputConditionIdentifier ({SECRET}) /RegistryName ({SECRET}) /Info ({SECRET}) >>')
            array = document.get_new_xref()
            document.update_object(array, f'[{intent} 0 R]')
            document.xref_set_key(document.pdf_catalog(), 'OutputIntents', f'{array} 0 R')
            document.save(target)
        self.originals[target] = target.read_bytes()
        return target

    def test_real_nondefault_gamma_and_raw_transform_tags_are_preserved(self):
        original = private_gamma_profile()
        cleaned = sanitize_icc(original)
        self.assertNotIn(SECRET.encode('utf-16be'), cleaned)
        for name, value in read_tags(original).items():
            if name not in (b'desc', b'cprt'):
                self.assertEqual(read_tags(cleaned)[name], value, name)
        rng = random.Random(68291)
        pixels = Image.new('RGB', (4096, 1))
        pixels.putdata([tuple(rng.randrange(256) for _ in range(3)) for _ in range(4096)])
        first = ImageCms.ImageCmsProfile(io.BytesIO(original))
        second = ImageCms.ImageCmsProfile(io.BytesIO(cleaned))
        lab = ImageCms.createProfile('LAB')
        for intent in range(4):
            before = ImageCms.applyTransform(pixels, ImageCms.buildTransform(first, lab, 'RGB', 'LAB', renderingIntent=intent)).tobytes()
            after = ImageCms.applyTransform(pixels, ImageCms.buildTransform(second, lab, 'RGB', 'LAB', renderingIntent=intent)).tobytes()
            self.assertEqual(before, after)
            standard = ImageCms.applyTransform(pixels, ImageCms.buildTransform(ImageCms.createProfile('sRGB'), lab, 'RGB', 'LAB', renderingIntent=intent)).tobytes()
            self.assertNotEqual(before, standard)

    def test_iccbased_and_output_intent_descriptions_removed_with_color_unchanged(self):
        original = private_gamma_profile()
        for with_type in (True, False):
            with self.subTest(output_intent_type=with_type):
                source = self.source(original, 'color-' + str(with_type), with_type)
                output = self.root / ('clean-' + str(with_type) + '.pdf')
                with fitz.open(source) as document:
                    before = document[0].get_pixmap(clip=fitz.Rect(345, 495, 455, 605), alpha=False).samples
                run('redact', [source], output, {'rects': [[20, 20, 340, 100]]})
                profiles = []
                with fitz.open(output) as document:
                    self.assertEqual(document[0].get_pixmap(clip=fitz.Rect(345, 495, 455, 605), alpha=False).samples, before)
                    for xref in range(1, document.xref_length()):
                        self.assertNotIn(SECRET, document.xref_object(xref))
                        if document.xref_is_stream(xref):
                            content = document.xref_stream(xref)
                            self.assertNotIn(SECRET.encode(), content)
                            self.assertNotIn(SECRET.encode('utf-16be'), content)
                            if content[36:40] == b'acsp': profiles.append(content)
                self.assertTrue(profiles)
                for profile in profiles:
                    for name in (b'rTRC', b'gTRC', b'bTRC', b'rXYZ', b'gXYZ', b'bXYZ'):
                        self.assertEqual(read_tags(profile)[name], read_tags(original)[name])

    def test_invalid_or_unsupported_profiles_fail_without_publication(self):
        original = private_gamma_profile()
        invalid_offset = bytearray(original)
        invalid_offset[136:140] = struct.pack('>I', len(original) + 4)
        invalid_padding = rebuild(original, {b'rTRC': read_tags(original)[b'rTRC'] + SECRET.encode()})
        unknown = rebuild(original, {b'priv': b'text' + bytes(4) + SECRET.encode() + b'\0'})
        curves = (b'curv' + bytes(4) + struct.pack('>I', 0)) * 3
        multistage = b'mAB ' + bytes(4) + b'\x03\x03\0\0' + struct.pack('>5I', 32, 0, 0, 0, 0) + curves + SECRET.encode()
        opaque_trailer = rebuild(original, {b'A2B0': multistage})
        # This formerly leaked: LCMS accepts the transform despite unused
        # private bytes after its last curve. Sampling alone cannot prove it.
        ImageCms.buildTransform(ImageCms.ImageCmsProfile(io.BytesIO(opaque_trailer)), ImageCms.createProfile('LAB'), 'RGB', 'LAB')
        for index, profile in enumerate((bytes(invalid_offset), invalid_padding, unknown, opaque_trailer)):
            with self.subTest(case=index):
                source = self.source(profile, 'invalid-' + str(index))
                output = self.root / ('refused-' + str(index) + '.pdf')
                with self.assertRaises(ValueError):
                    run('redact', [source], output, {'rects': [[20, 20, 340, 100]]})
                self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
