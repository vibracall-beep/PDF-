#!/usr/bin/env python3
"""Require all native preview artifacts; validate PNG structure and existing AX rules.

These checks establish artifact completeness, not visual correctness, VoiceOver
interaction, contrast, or semantic accessibility of an arbitrary PDF.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import struct
import sys
import zlib

from check_accessibility_report import check as check_accessibility

PREVIEW_STATES = (
    '', 'leitor', 'abas', 'lado-a-lado', 'anotacoes', 'recuperacao',
    'personalizar', 'ferramentas', 'navegacao', 'opcoes-leitura', 'arquivos',
    'escuro', 'lista', 'configuracao-ferramenta', 'fluxo-lote',
    'assinatura-digital', 'verificar-assinaturas', 'validar-pdfa', 'auditar-pdfua',
    'atalhos', 'perfis', 'menus', 'paleta', 'editor-conteudo', 'revisao-ocr', 'biblioteca',
    'corrigir-acessibilidade', 'solicitar-assinaturas', 'automacao',
    'producao-print-preflight', 'producao-bates', 'producao-measure', 'producao-pdfx',
)
REQUIRED_AX = {
    'PDF-preview.accessibility.json': {'pdf.catalog.search', 'pdf.customize.toolbar'},
    'PDF-preview.leitor.accessibility.json': {'pdf.reader.document', 'pdf.reader.search', 'pdf.reader.page'},
    'PDF-preview.lado-a-lado.accessibility.json': {'pdf.reader.document', 'pdf.reader.reference'},
    'PDF-preview.anotacoes.accessibility.json': {'pdf.reader.document', 'pdf.reader.inspector'},
    'PDF-preview.biblioteca.accessibility.json': {'pdf.library'},
    'PDF-preview.menus.accessibility.json': {'pdf.menus.quick-title', 'pdf.menus.quick-add'},
    'PDF-preview.corrigir-acessibilidade.accessibility.json': {
        'pdf.accessibility.tag.title', 'pdf.accessibility.tag.alt', 'pdf.accessibility.tag.actual-text',
        'pdf.accessibility.tag.language', 'pdf.accessibility.tag.scope',
    },
}
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_RASTER_BYTES = 128 * 1024 * 1024
DECODE_BLOCK_BYTES = 64 * 1024


class PNGRaster:
    """Validate deflate and scanline framing with bounded incremental decoding."""
    def __init__(self, header):
        width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', header)
        depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
        if color not in depths or depth not in depths[color] or compression or filtering or interlace not in (0, 1):
            raise ValueError('invalid PNG color, depth, compression, filter or interlace method')
        if width <= 100 or height <= 100:
            raise ValueError('preview dimensions must exceed 100 pixels')
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
        passes = [(0, 0, 1, 1)] if not interlace else [
            (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
            (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
        ]
        rows = []
        for x, y, dx, dy in passes:
            columns = max(0, (width - x + dx - 1) // dx)
            count = max(0, (height - y + dy - 1) // dy)
            if columns and count:
                rows.append((count, (columns * channels * depth + 7) // 8))
        self.expected = sum(count * (length + 1) for count, length in rows)
        if self.expected > MAX_RASTER_BYTES:
            raise ValueError('decoded PNG raster exceeds the 128 MB limit')
        self.dimensions = (width, height)
        self.color, self.depth = color, depth
        self.rows = (length for count, length in rows for _ in range(count))
        self.remaining = self.decoded = 0
        self.decoder = zlib.decompressobj()

    def _scanlines(self, data):
        self.decoded += len(data)
        if self.decoded > self.expected:
            raise ValueError('PNG contains more raster bytes than its dimensions allow')
        offset = 0
        while offset < len(data):
            if not self.remaining:
                length = next(self.rows, None)
                if length is None or data[offset] > 4:
                    raise ValueError('invalid PNG scanline filter or extra raster data')
                self.remaining = length
                offset += 1
            consumed = min(self.remaining, len(data) - offset)
            self.remaining -= consumed
            offset += consumed

    def feed(self, data):
        try:
            while data:
                if self.decoder.eof:
                    raise ValueError('PNG contains data after the deflate stream')
                self._scanlines(self.decoder.decompress(data, DECODE_BLOCK_BYTES))
                if self.decoder.unused_data:
                    raise ValueError('PNG contains trailing or concatenated deflate data')
                data = self.decoder.unconsumed_tail
        except zlib.error as error:
            raise ValueError('PNG image data cannot be decompressed') from error

    def finish(self):
        if not self.decoder.eof or self.decoded != self.expected or self.remaining:
            raise ValueError('PNG has a truncated deflate stream or incomplete raster')


@contextmanager
def regular_file(path):
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARTIFACT_BYTES:
            raise ValueError(f'{path.name}: expected a regular artifact of at most 64 MB')
        yield stream


def check_png(path):
    with regular_file(path) as stream:
        if stream.read(8) != PNG_SIGNATURE:
            raise ValueError(f'{path.name}: missing PNG signature')
        raster = None
        image_bytes = 0
        palette = False
        after_image_data = False
        consumed_bytes = 8
        while True:
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError(f'{path.name}: truncated PNG or missing IEND')
            length, kind = struct.unpack('>I4s', header)
            consumed_bytes += length + 12
            if consumed_bytes > MAX_ARTIFACT_BYTES:
                raise ValueError(f'{path.name}: invalid PNG chunk length')
            if any(not (65 <= byte <= 90 or 97 <= byte <= 122) for byte in kind) or kind[2] & 32:
                raise ValueError(f'{path.name}: invalid PNG chunk type')
            payload = stream.read(length)
            checksum = stream.read(4)
            if len(payload) != length or len(checksum) != 4:
                raise ValueError(f'{path.name}: truncated PNG chunk')
            expected = struct.unpack('>I', checksum)[0]
            if zlib.crc32(payload, zlib.crc32(kind)) & 0xffffffff != expected:
                raise ValueError(f'{path.name}: PNG chunk checksum mismatch')
            if raster is None:
                if kind != b'IHDR' or length != 13:
                    raise ValueError(f'{path.name}: missing PNG IHDR')
                raster = PNGRaster(payload)
            elif kind == b'IHDR':
                raise ValueError(f'{path.name}: duplicate PNG IHDR')
            elif kind == b'PLTE':
                if palette or image_bytes or raster.color in (0, 4) or not length or length % 3 or length > 768:
                    raise ValueError(f'{path.name}: invalid PNG palette')
                if raster.color == 3 and length // 3 > 2 ** raster.depth:
                    raise ValueError(f'{path.name}: PNG palette exceeds indexed bit depth')
                palette = True
            elif not kind[0] & 32 and kind not in (b'IDAT', b'IEND'):
                raise ValueError(f'{path.name}: unsupported critical PNG chunk')
            if kind == b'IDAT':
                if after_image_data or (raster.color == 3 and not palette):
                    raise ValueError(f'{path.name}: PNG image chunks are out of order or lack a palette')
                image_bytes += length
                raster.feed(payload)
            elif image_bytes:
                after_image_data = True
            if kind == b'IEND':
                if length or not image_bytes or stream.read(1):
                    raise ValueError(f'{path.name}: incomplete PNG image or invalid IEND')
                raster.finish()
                return raster.dimensions


def check_directory(directory):
    directory = Path(directory)
    failures = []
    for state in PREVIEW_STATES:
        name = 'PDF-preview' + ('.' + state if state else '') + '.png'
        try:
            width, height = check_png(directory / name)
            print(f'{name}: PNG {width} × {height}')
        except (OSError, ValueError) as error:
            failures.append(f'{name}: {error}')
    reports = sorted(directory.glob('PDF-preview*accessibility.json'))
    missing = set(REQUIRED_AX) - {path.name for path in reports}
    for name in sorted(missing):
        failures.append(f'{name}: required accessibility report missing')
    for path in reports:
        try:
            with regular_file(path) as stream:
                report = json.load(stream)
            identifiers = {node.get('identifier') for node in report.get('nodes', [])}
            missing_ids = REQUIRED_AX.get(path.name, set()) - identifiers
            if missing_ids:
                failures.append(f'{path.name}: required node identifiers missing: {", ".join(sorted(missing_ids))}')
            # Keep the established checker unchanged: unnamed owned controls,
            # missing identifiers and traversal limits remain hard failures.
            if not check_accessibility(path, report=report):
                failures.append(f'{path.name}: accessibility checker failed')
        except (OSError, ValueError, TypeError, AttributeError) as error:
            failures.append(f'{path.name}: {error}')
    for failure in failures:
        print(f'Preview artifact failure: {failure}', file=sys.stderr)
    if failures:
        return False
    print(f'Native preview artifacts complete: {len(PREVIEW_STATES)} PNGs and {len(REQUIRED_AX)} required accessibility reports.')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    raise SystemExit(0 if check_directory(args.directory) else 1)
