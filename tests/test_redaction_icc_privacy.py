"""Actual ICC/JPEG containers: declared privacy channels and color invariance."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import fitz
from PIL import Image, ImageCms

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run
from pdf_icc_privacy import sanitize_icc
from pdf_image_privacy import strip_jpeg_metadata

SECRET = 'PRIVATE-68291'  # 13 UTF-16 code units fit the real sRGB description.


def tags(data):
    result = {}
    for p in range(132, 132 + 12 * int.from_bytes(data[128:132], 'big'), 12):
        offset = int.from_bytes(data[p + 4:p + 8], 'big'); size = int.from_bytes(data[p + 8:p + 12], 'big')
        result[data[p:p + 4]] = data[offset:offset + size]
    return result


def with_tags(data, replacements):
    values = tags(data); values.update(replacements)
    start = 132 + len(values) * 12; table = bytearray(); body = bytearray()
    for name, value in values.items():
        body.extend(b'\0' * (-(start + len(body)) % 4))
        table.extend(name + struct.pack('>II', start + len(body), len(value))); body.extend(value)
    result = bytearray(data[:128] + struct.pack('>I', len(values)) + table + body)
    result.extend(b'\0' * (-len(result) % 4)); result[:4] = struct.pack('>I', len(result))
    result[84:100] = b'\0' * 16
    return bytes(result)


def secret_profile(data=None):
    data = data or ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    values = tags(data); description = bytearray(values[b'desc'])
    if description[:4] == b'mluc':
        length = int.from_bytes(description[20:24], 'big'); start = int.from_bytes(description[24:28], 'big')
        description[start:start + length] = (SECRET + ' ' * (length // 2 - len(SECRET))).encode('utf-16be')
    elif description[:4] == b'desc':
        count = int.from_bytes(description[8:12], 'big')
        description[12:12 + count] = (SECRET + ' ' * (count - 1 - len(SECRET))).encode() + b'\0'
    else:
        raise AssertionError('Unknown real fixture description type')
    result = bytearray(with_tags(data, {b'desc': bytes(description)}))
    result[4:8] = b'PRIV'; result[10:12] = b'PX'; result[48:56] = b'PRIVATE!'; result[80:84] = b'HIDE'
    profile = ImageCms.ImageCmsProfile(io.BytesIO(result))
    assert profile.profile.profile_description.startswith(SECRET)
    return bytes(result)


def real_profile(name):
    candidates = [Path('/usr/share/color/icc/ghostscript') / name,
                  Path('/opt/homebrew/share/ghostscript/iccprofiles') / name]
    candidates += list(Path('/opt/homebrew/share/ghostscript').glob('*/iccprofiles/' + name))
    candidates += list(Path('/usr/share/ghostscript').glob('*/iccprofiles/' + name))
    return next((path.read_bytes() for path in candidates if path.is_file()), None)


class RedactionICCPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='PDF ICC privacy ')
        self.root = Path(self.temporary.name)
        self.originals = {}

    def tearDown(self):
        for path, original in self.originals.items(): self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.pdf-output-*')))
        self.temporary.cleanup()

    def assert_private_fields_removed(self, data):
        self.assertNotIn(SECRET.encode(), data); self.assertNotIn(SECRET.encode('utf-16be'), data)
        self.assertEqual(data[4:8], b'\0' * 4); self.assertEqual(data[10:12], b'\0' * 2); self.assertEqual(data[48:56], b'\0' * 8)
        self.assertEqual(data[80:84], b'\0' * 4)
        self.assertEqual(ImageCms.ImageCmsProfile(io.BytesIO(data)).profile.profile_description, 'Sanitized color profile')

    def test_real_rgb_profile_metadata_and_header_removed_numeric_tags_preserved(self):
        original = secret_profile()
        text = SECRET.encode('utf-16be')
        # A real ICC dictionary metadata tag with a declared Author entry.
        name = 'Author'.encode('utf-16be')
        meta = b'dict' + b'\0' * 4 + struct.pack('>II', 1, 16) + struct.pack('>IIII', 32, len(name), 32 + len(name), len(text)) + name + text
        original = with_tags(original, {b'meta': meta, b'dmnd': tags(original)[b'desc']})
        cleaned = sanitize_icc(original)
        self.assert_private_fields_removed(cleaned)
        self.assertNotIn(b'meta', tags(cleaned)); self.assertNotIn(b'dmnd', tags(cleaned))
        for name, value in tags(original).items():
            if name not in (b'desc', b'cprt', b'meta', b'dmnd'):
                self.assertEqual(tags(cleaned)[name], value, name)
        self.assertEqual(sanitize_icc(cleaned), cleaned)
        hashed = bytearray(cleaned); hashed[44:48] = b'\0' * 4; hashed[64:68] = b'\0' * 4; hashed[84:100] = b'\0' * 16
        self.assertEqual(cleaned[84:100], hashlib.md5(hashed, usedforsecurity=False).digest())

    def test_real_cmyk_gray_profiles_keep_actual_four_intent_transforms(self):
        for filename, mode in (('default_cmyk.icc', 'CMYK'), ('default_gray.icc', 'L')):
            with self.subTest(mode=mode):
                raw = real_profile(filename)
                self.assertIsNotNone(raw, 'A real Ghostscript ICC profile is required, not a fabricated header.')
                original = secret_profile(raw); cleaned = sanitize_icc(original)
                self.assert_private_fields_removed(cleaned)
                self.assertEqual(original[12:24], cleaned[12:24])
                image = Image.new(mode, (16, 1))
                image.putdata([(i * 17, 255 - i * 17, (i * 41) % 256, (i * 53) % 256) for i in range(16)] if mode == 'CMYK' else [i * 17 for i in range(16)])
                target = ImageCms.createProfile('sRGB')
                for intent in range(4):
                    before = ImageCms.buildTransform(ImageCms.ImageCmsProfile(io.BytesIO(original)), target, mode, 'RGB', renderingIntent=intent)
                    after = ImageCms.buildTransform(ImageCms.ImageCmsProfile(io.BytesIO(cleaned)), target, mode, 'RGB', renderingIntent=intent)
                    self.assertEqual(ImageCms.applyTransform(image, before).tobytes(), ImageCms.applyTransform(image, after).tobytes())

    def test_unknown_icc_tags_classes_and_partial_overlap_are_refused(self):
        original = secret_profile()
        unknown = with_tags(original, {b'zzzz': b'text' + b'\0' * 4 + SECRET.encode() + b'\0'})
        wrong_class = bytearray(original); wrong_class[12:16] = b'link'
        overlapping = bytearray(original)
        first_offset = int.from_bytes(overlapping[136:140], 'big')
        overlapping[148:152] = (first_offset + 4).to_bytes(4, 'big')
        for value in (unknown, bytes(wrong_class), bytes(overlapping)):
            with self.subTest(size=len(value)):
                with self.assertRaises(ValueError): sanitize_icc(value)

    def test_real_multistage_lut_with_unused_private_trailer_is_refused(self):
        trailer = b'PRIVATE-MAB-TRAILING-63819'
        for signature, kind in ((b'A2B0', b'mAB '), (b'B2A0', b'mBA ')):
            with self.subTest(kind=kind):
                # A valid three-channel identity B-curve set followed by bytes
                # outside the transform. LCMS accepts/uses the curves and
                # ignores the trailer, so transform equality cannot approve it.
                header = kind + b'\0' * 4 + bytes((3, 3, 0, 0)) + struct.pack('>IIIII', 32, 0, 0, 0, 0)
                curve = b'curv' + b'\0' * 8
                original = with_tags(secret_profile(), {signature: header + curve * 3 + trailer})
                profile = ImageCms.ImageCmsProfile(io.BytesIO(original))
                ImageCms.buildTransform(profile, ImageCms.createProfile('LAB'), 'RGB', 'LAB')
                with self.assertRaisesRegex(ValueError, 'múltiplas etapas'):
                    sanitize_icc(original)
                source = self._pdf('multistage-' + kind.decode().strip(), original)
                target = source.with_name(source.stem + '-refused.pdf')
                with self.assertRaises(ValueError): run('redact', [source], target, {'rects': [[20, 20, 340, 100]]})
                self.assertFalse(target.exists())

    def test_jpeg_app2_profile_reassembled_sanitized_and_pixels_not_recompressed(self):
        for mode, profile in (('RGB', secret_profile()), ('CMYK', secret_profile(real_profile('default_cmyk.icc')))):
            with self.subTest(mode=mode):
                image = Image.new(mode, (32, 32), (90, 100, 120) if mode == 'RGB' else (20, 60, 100, 10))
                stream = io.BytesIO(); image.save(stream, format='JPEG', icc_profile=profile, progressive=True)
                original = stream.getvalue(); cleaned = strip_jpeg_metadata(original)
                before = Image.open(io.BytesIO(original)); after = Image.open(io.BytesIO(cleaned))
                self.assertEqual(before.mode, after.mode); self.assertEqual(before.tobytes(), after.tobytes())
                self.assert_private_fields_removed(after.info['icc_profile'])
                self.assertEqual(strip_jpeg_metadata(cleaned), cleaned)
                if mode == 'CMYK': self.assertGreater(original.count(b'ICC_PROFILE\0'), 1)

    def test_jpeg_ambiguous_icc_chunks_refused_before_metadata_is_kept(self):
        image = Image.new('RGB', (8, 8)); stream = io.BytesIO(); image.save(stream, format='JPEG', icc_profile=secret_profile())
        original = stream.getvalue(); offset = original.index(b'ICC_PROFILE\0')
        duplicate = bytearray(original); duplicate[offset + 12] = 0
        incomplete = bytearray(original); incomplete[offset + 13] = 2
        for value in (bytes(duplicate), bytes(incomplete)):
            with self.assertRaises(ValueError): strip_jpeg_metadata(value)

    def _pdf(self, name, profile, inline=False):
        stream = io.BytesIO(); Image.new('RGB', (64, 64), (90, 100, 120)).save(stream, format='JPEG', icc_profile=profile)
        source = self.root / (name + '.pdf')
        with fitz.open() as document:
            page = document.new_page(); page.insert_text((40, 50), SECRET); page.insert_text((40, 180), 'PUBLIC')
            if inline:
                content = document.get_new_xref(); document.update_object(content, '<< >>')
                document.update_stream(content, b'q 100 0 0 100 350 242 cm BI /W 64 /H 64 /CS /RGB /BPC 8 /F /DCT ID ' + stream.getvalue() + b' EI Q')
                document.xref_set_key(page.xref, 'Contents', '[' + ' '.join(f'{xref} 0 R' for xref in page.get_contents() + [content]) + ']')
            else:
                page.insert_image(fitz.Rect(350, 500, 450, 600), stream=stream.getvalue())
            document.save(source)
        self.originals[source] = source.read_bytes()
        return source

    def test_redaction_removes_icc_description_from_pdf_streams_and_inline_jpeg(self):
        for inline in (False, True):
            source = self._pdf('inline' if inline else 'xobject', secret_profile(), inline)
            target = self.root / ('clean-inline.pdf' if inline else 'clean-xobject.pdf')
            with fitz.open(source) as before:
                baseline = before[0].get_pixmap(clip=fitz.Rect(345, 495, 455, 605), alpha=False).samples
            run('redact', [source], target, {'rects': [[20, 20, 340, 100]]})
            with fitz.open(target) as after:
                self.assertIn('PUBLIC', after[0].get_text())
                self.assertEqual(after[0].get_pixmap(clip=fitz.Rect(345, 495, 455, 605), alpha=False).samples, baseline)
                chunks = []
                for xref in range(1, after.xref_length()):
                    chunks.append(after.xref_object(xref).encode())
                    if after.xref_is_stream(xref): chunks.extend((after.xref_stream(xref), after.xref_stream_raw(xref)))
                for block in after[0].get_text('dict')['blocks']:
                    if block['type'] == 1: chunks.append(block['image'])
                for chunk in chunks:
                    self.assertNotIn(SECRET.encode(), chunk); self.assertNotIn(SECRET.encode('utf-16be'), chunk)

    def test_redaction_rejects_unsupported_icc_without_overwriting_existing_documents(self):
        unknown = with_tags(secret_profile(), {b'zzzz': b'text' + b'\0' * 4 + SECRET.encode() + b'\0'})
        source = self._pdf('unknown', unknown)
        target = self.root / 'refused.pdf'
        with self.assertRaises(ValueError): run('redact', [source], target, {'rects': [[20, 20, 340, 100]]})
        self.assertFalse(target.exists())
        target.write_bytes(b'existing owner document')
        with self.assertRaises(ValueError): run('redact', [source], target, {'rects': [[20, 20, 340, 100]]})
        self.assertEqual(target.read_bytes(), b'existing owner document')


if __name__ == '__main__': unittest.main()
