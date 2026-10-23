"""Portable artifact-validator regressions; fixtures do not represent native UI tests."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

import check_preview_artifacts as preview


def chunk(kind, payload):
    checksum=zlib.crc32(payload,zlib.crc32(kind)) & 0xffffffff
    return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',checksum)


def png(width=101, height=102, *, pixels=None, compressed=None, depth=8, color=2, interlace=0):
    # Real, small RGB raster; no imaging dependency is needed before native build.
    if compressed is None:
        if pixels is None: pixels=(b'\0'+b'\xff\xff\xff'*width)*height
        compressed=zlib.compress(pixels)
    return (preview.PNG_SIGNATURE + chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,depth,color,0,0,interlace))
            + chunk(b'IDAT',compressed) + chunk(b'IEND',b''))


class PreviewArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='pdf preview artifacts ')
        self.root=Path(self.temporary.name)
        for state in preview.PREVIEW_STATES:
            name='PDF-preview'+('.'+state if state else '')+'.png'
            (self.root/name).write_bytes(png())
        for name, identifiers in preview.REQUIRED_AX.items():
            self.write_report(name,identifiers)

    def tearDown(self): self.temporary.cleanup()

    def write_report(self,name,identifiers,findings=None):
        report={'version':1,'scope':'current-process-own-window','findings':findings or [],
                'traversalLimited':False,'missingRequiredIdentifiers':[],
                'nodes':[{'index':index,'role':'AXButton','identifier':value,'name':'Synthetic test label'}
                         for index,value in enumerate(sorted(identifiers))]}
        (self.root/name).write_text(json.dumps(report))

    def check(self):
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            return preview.check_directory(self.root)

    def test_all_19_images_and_4_ax_reports_are_required(self):
        self.assertEqual(len(preview.PREVIEW_STATES),19)
        self.assertEqual(len(preview.REQUIRED_AX),4)
        self.assertTrue(self.check())
        for state in preview.PREVIEW_STATES:
            path=self.root/('PDF-preview'+('.'+state if state else '')+'.png')
            data=path.read_bytes();path.unlink()
            self.assertFalse(self.check(),state or 'home')
            path.write_bytes(data)
        for name in preview.REQUIRED_AX:
            path=self.root/name;data=path.read_bytes();path.unlink()
            self.assertFalse(self.check(),name)
            path.write_bytes(data)

    def test_non_png_small_truncated_and_bad_checksum_images_fail(self):
        path=self.root/'PDF-preview.anotacoes.png'
        corrupted=bytearray(png());corrupted[20]^=1
        for data in (b'not a PNG',png(100,102),png(101,100),png()[:24],png()[:-12],bytes(corrupted)):
            with self.subTest(length=len(data)):
                path.write_bytes(data);self.assertFalse(self.check())

    def test_missing_identifier_fails_even_without_emitted_finding(self):
        name='PDF-preview.leitor.accessibility.json'
        self.write_report(name,{'pdf.reader.document','pdf.reader.search'})
        self.assertFalse(self.check())

    def test_undecodable_and_wrong_sized_rasters_fail_with_valid_chunk_checksums(self):
        path=self.root/'PDF-preview.png'
        pixels=(b'\0'+b'\xff\xff\xff'*101)*102
        damaged=(b'not-deflate',zlib.compress(pixels)[:-1],zlib.compress(pixels[:-1]),
                 zlib.compress(pixels+b'\0'),zlib.compress(pixels)+zlib.compress(b'extra'),
                 zlib.compress(b'\5'+pixels[1:]))
        for data in damaged:
            with self.subTest(compressed_length=len(data)):
                path.write_bytes(png(compressed=data));self.assertFalse(self.check())

    def test_raster_limits_and_illegal_pixel_formats_fail_before_allocation(self):
        path=self.root/'PDF-preview.png'
        for width,height,depth,color in [(2**31,2**31,16,6),(101,102,3,2),(101,102,8,7)]:
            with self.subTest(width=width,height=height,depth=depth,color=color):
                path.write_bytes(png(width,height,depth=depth,color=color,compressed=b'not decoded'))
                self.assertFalse(self.check())

    def test_real_sized_rgba_and_adam7_rasters_pass_incremental_decoding(self):
        path=self.root/'PDF-preview.png'
        width,height=2100,1440
        pixels=(b'\0'+b'\x12\x34\x56\xff'*width)*height
        path.write_bytes(png(width,height,color=6,pixels=pixels))
        self.assertTrue(self.check())
        width,height=101,102
        passes=[(0,0,8,8),(4,0,8,8),(0,4,4,8),(2,0,4,4),(0,2,2,4),(1,0,2,2),(0,1,1,2)]
        pixels=b''.join((b'\0'+b'\x7f'*len(range(x,width,dx)))*len(range(y,height,dy)) for x,y,dx,dy in passes)
        path.write_bytes(png(width,height,color=0,pixels=pixels,interlace=1))
        self.assertTrue(self.check())

    def test_ax_failure_flags_are_enforced_without_findings(self):
        path=self.root/'PDF-preview.leitor.accessibility.json'
        original=json.loads(path.read_text())
        for field,value in [('traversalLimited',True),('missingRequiredIdentifiers',['pdf.reader.page'])]:
            with self.subTest(field=field):
                report=dict(original);report[field]=value;path.write_text(json.dumps(report))
                self.assertFalse(self.check())

    def test_owned_unnamed_control_is_rejected_without_a_finding(self):
        path=self.root/'PDF-preview.leitor.accessibility.json'
        report=json.loads(path.read_text());report['nodes'][0]['name']='  '
        path.write_text(json.dumps(report));self.assertFalse(self.check())

    def test_existing_accessibility_checker_failures_are_not_weakened(self):
        name='PDF-preview.anotacoes.accessibility.json'
        for code in ('unnamed-app-control','missing-required-identifier','traversal-limit'):
            self.write_report(name,preview.REQUIRED_AX[name],[{'code':code,'detail':'Synthetic failure'}])
            self.assertFalse(self.check(),code)

    def test_symlink_image_is_not_accepted_as_a_capture(self):
        path=self.root/'PDF-preview.png';path.unlink()
        path.symlink_to(self.root/'PDF-preview.leitor.png')
        self.assertFalse(self.check())

    def test_extra_accessibility_reports_are_checked_too(self):
        self.write_report('PDF-preview.extra.accessibility.json',{'pdf.extra'},
                          [{'code':'unnamed-app-control','detail':'Synthetic failure'}])
        self.assertFalse(self.check())

if __name__=='__main__': unittest.main()
