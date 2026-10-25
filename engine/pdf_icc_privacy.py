"""Remove declared ICC descriptions while retaining supported color transforms.

This is not a detector for steganography in numerical color data. Unknown
profile classes, tags and tag types are refused rather than silently retained.
"""
from __future__ import annotations

import hashlib
import io
import itertools
import struct

from PIL import Image, ImageCms

LIMIT = 16 * 1024**2
DESCRIPTIVE = {b'desc', b'cprt', b'dmnd', b'dmdd', b'vued', b'meta', b'pseq', b'psid', b'targ', b'tech'}
NUMERIC = {
    b'wtpt': {b'XYZ '}, b'bkpt': {b'XYZ '}, b'lumi': {b'XYZ '},
    b'rXYZ': {b'XYZ '}, b'gXYZ': {b'XYZ '}, b'bXYZ': {b'XYZ '},
    b'rTRC': {b'curv', b'para'}, b'gTRC': {b'curv', b'para'},
    b'bTRC': {b'curv', b'para'}, b'kTRC': {b'curv', b'para'},
    b'chad': {b'sf32'}, b'chrm': {b'chrm'}, b'meas': {b'meas'},
    b'view': {b'view'}, b'clrt': {b'clrt'}, b'clot': {b'clrt'}, b'clro': {b'clro'},
    b'gamt': {b'mft1', b'mft2'}, b'pre0': {b'mft1', b'mft2'},
    b'pre1': {b'mft1', b'mft2'}, b'pre2': {b'mft1', b'mft2'},
    **{('A2B' + str(i)).encode(): {b'mft1', b'mft2'} for i in range(3)},
    **{('B2A' + str(i)).encode(): {b'mft1', b'mft2'} for i in range(3)},
}


def _uint(data):
    return int.from_bytes(data, 'big')


def _description(value, version):
    if version >= 4:
        encoded = value.encode('utf-16be')
        return b'mluc' + b'\0' * 4 + struct.pack('>II', 1, 12) + b'enUS' + struct.pack('>II', len(encoded), 28) + encoded
    encoded = value.encode('ascii') + b'\0'
    return b'desc' + b'\0' * 4 + struct.pack('>I', len(encoded)) + encoded + b'\0' * (4 + 4 + 2 + 1 + 67)


def _bounded_length(data, required):
    if not required <= len(data) <= required + 3 or any(data[required:]):
        raise ValueError('O perfil ICC contém tamanho ou padding de tag não suportado.')
    return data[:required]


def _numeric_tag(signature, data):
    kind = data[:4]
    if kind in (b'mAB ', b'mBA ', b'mpet'):
        # LCMS tolerates unused bytes after multi-stage blocks. Equal rendered
        # samples do not prove that those bytes contain no descriptive data.
        # Refuse until offsets, lengths and every gap are structurally covered.
        raise ValueError('Este perfil ICC usa LUT de múltiplas etapas ainda não saneável; prepare uma cópia estática revisada.')
    if kind not in NUMERIC.get(signature, set()) or len(data) < 8 or any(data[4:8]):
        raise ValueError('O perfil ICC contém tag ou tipo não suportado para saneamento de metadados.')
    if kind == b'XYZ ':
        return _bounded_length(data, 20)
    if kind == b'sf32':
        return _bounded_length(data, 44)
    if kind == b'curv':
        if len(data) < 12:
            raise ValueError('A curva ICC está truncada.')
        return _bounded_length(data, 12 + 2 * _uint(data[8:12]))
    if kind == b'para':
        if len(data) < 12 or any(data[10:12]) or _uint(data[8:10]) not in range(5):
            raise ValueError('A curva paramétrica ICC não é suportada.')
        return _bounded_length(data, 12 + 4 * (1, 3, 4, 5, 7)[_uint(data[8:10])])
    if kind == b'chrm':
        if len(data) < 12 or not 1 <= _uint(data[8:10]) <= 16:
            raise ValueError('A cromaticidade ICC é inválida.')
        return _bounded_length(data, 12 + 8 * _uint(data[8:10]))
    if kind in (b'meas', b'view'):
        return _bounded_length(data, 36)
    if kind == b'clro':
        if len(data) < 12 or not 1 <= _uint(data[8:12]) <= 16:
            raise ValueError('A ordem dos colorantes ICC não é suportada.')
        return _bounded_length(data, 12 + _uint(data[8:12]))
    if kind == b'clrt':
        if len(data) < 12 or not 1 <= _uint(data[8:12]) <= 16:
            raise ValueError('A tabela de colorantes ICC não é suportada.')
        count = _uint(data[8:12]); result = bytearray(_bounded_length(data, 12 + 38 * count))
        for index in range(count):
            start = 12 + 38 * index
            label = ('Channel ' + str(index + 1)).encode('ascii')
            result[start:start + 32] = label + b'\0' * (32 - len(label))
        return bytes(result)
    if kind in (b'mft1', b'mft2'):
        minimum = 48 if kind == b'mft1' else 52
        if len(data) < minimum or not 1 <= data[8] <= 16 or not 1 <= data[9] <= 16 or not 2 <= data[10] <= 255 or data[11] != 0:
            raise ValueError('A LUT ICC não é suportada.')
        inputs, outputs, grid = data[8], data[9], data[10]
        if kind == b'mft1':
            required = 48 + 256 * inputs + grid ** inputs * outputs + 256 * outputs
        else:
            input_entries, output_entries = _uint(data[48:50]), _uint(data[50:52])
            if input_entries < 2 or output_entries < 2:
                raise ValueError('A LUT ICC possui tabelas incompletas.')
            required = 52 + 2 * (input_entries * inputs + grid ** inputs * outputs + output_entries * outputs)
        return _bounded_length(data, required)
    raise ValueError('O perfil ICC contém tipo de tag não suportado.')


def _sample_image(mode):
    values = (0, 64, 128, 192, 255)
    channels = {'RGB': 3, 'CMYK': 4, 'L': 1}[mode]
    samples = list(itertools.product(values, repeat=channels))
    image = Image.new(mode, (len(samples), 1))
    image.putdata([item[0] for item in samples] if channels == 1 else samples)
    return image


def _prove_transforms(original, cleaned, mode):
    """Bounded numerical proof samples supplement unchanged color-tag bytes."""
    first = ImageCms.ImageCmsProfile(io.BytesIO(original)); second = ImageCms.ImageCmsProfile(io.BytesIO(cleaned))
    lab = ImageCms.createProfile('LAB')
    samples = _sample_image(mode)
    reverse_samples = Image.new('LAB', (5, 1))
    reverse_samples.putdata([(0, 128, 128), (64, 112, 144), (128, 128, 128), (192, 144, 112), (255, 128, 128)])
    for intent in range(4):
        try:
            source = ImageCms.buildTransform(first, lab, mode, 'LAB', renderingIntent=intent)
            target = ImageCms.buildTransform(second, lab, mode, 'LAB', renderingIntent=intent)
        except (ImageCms.PyCMSError, ValueError, OSError) as exc:
            raise ValueError('O perfil ICC não permite verificar sua transformação de cor com segurança.') from exc
        if ImageCms.applyTransform(samples, source).tobytes() != ImageCms.applyTransform(samples, target).tobytes():
            raise ValueError('O saneamento ICC alteraria as amostras de transformação de cor.')
        try:
            source_reverse = ImageCms.buildTransform(lab, first, 'LAB', mode, renderingIntent=intent)
        except (ImageCms.PyCMSError, ValueError, OSError):
            # Input-only profiles may lack an inverse. Do not invent one, and
            # do not accept a rewritten profile that changes that capability.
            try:
                ImageCms.buildTransform(lab, second, 'LAB', mode, renderingIntent=intent)
            except (ImageCms.PyCMSError, ValueError, OSError):
                continue
            raise ValueError('O saneamento alterou a capacidade inversa do perfil ICC.')
        try:
            target_reverse = ImageCms.buildTransform(lab, second, 'LAB', mode, renderingIntent=intent)
        except (ImageCms.PyCMSError, ValueError, OSError) as exc:
            raise ValueError('O saneamento perdeu a transformação inversa do perfil ICC.') from exc
        if ImageCms.applyTransform(reverse_samples, source_reverse).tobytes() != ImageCms.applyTransform(reverse_samples, target_reverse).tobytes():
            raise ValueError('O saneamento ICC alteraria as amostras da transformação inversa.')


def sanitize_icc(data):
    if not isinstance(data, bytes):
        data = bytes(data)
    if not 132 <= len(data) <= LIMIT or _uint(data[:4]) != len(data) or data[36:40] != b'acsp':
        raise ValueError('O perfil ICC é inválido ou excede o limite de 16 MiB.')
    version = data[8]
    modes = {b'RGB ': 'RGB', b'CMYK': 'CMYK', b'GRAY': 'L'}
    if version not in (2, 4) or data[12:16] not in (b'mntr', b'prtr', b'scnr') or data[16:20] not in modes or data[20:24] not in (b'XYZ ', b'Lab '):
        raise ValueError('Esta classe, versão ou espaço de cor ICC exige uma cópia estática revisada.')
    if _uint(data[64:68]) > 3:
        raise ValueError('A intenção de renderização ICC é inválida.')
    count = _uint(data[128:132]); table_end = 132 + count * 12
    if not 1 <= count <= 4096 or table_end > len(data):
        raise ValueError('A tabela de tags ICC é inválida.')
    tags = {}; ranges = []
    for position in range(132, table_end, 12):
        signature = data[position:position + 4]; offset = _uint(data[position + 4:position + 8]); length = _uint(data[position + 8:position + 12])
        if signature in tags or offset < table_end or offset % 4 or length < 8 or offset + length > len(data):
            raise ValueError('A tag ICC está duplicada, truncada ou fora do perfil.')
        if any(max(offset, start) < min(offset + length, end) and (offset, offset + length) != (start, end) for start, end in ranges):
            raise ValueError('Há tags ICC parcialmente sobrepostas.')
        ranges.append((offset, offset + length)); tags[signature] = data[offset:offset + length]
    if b'desc' not in tags or b'cprt' not in tags:
        raise ValueError('O perfil ICC não contém as tags descritivas obrigatórias.')
    cleaned_tags = {}
    for signature, value in tags.items():
        if signature == b'desc':
            cleaned_tags[signature] = _description('Sanitized color profile', version)
        elif signature == b'cprt':
            cleaned_tags[signature] = _description('', 4) if version == 4 else b'text' + b'\0' * 5
        elif signature in DESCRIPTIVE:
            continue
        else:
            cleaned_tags[signature] = _numeric_tag(signature, value)
    header = bytearray(data[:128])
    header[4:8] = b'\0' * 4  # Preferred CMM identifier.
    header[10:12] = b'\0' * 2  # Reserved portion of the profile-version field.
    header[24:36] = struct.pack('>6H', 2000, 1, 1, 0, 0, 0)
    header[40:44] = b'\0' * 4  # Platform identifier.
    header[48:56] = b'\0' * 8  # Manufacturer and model.
    # Vendor/reserved bits are descriptive; retain standardized color/media flags.
    header[44:48] = (_uint(data[44:48]) & 3).to_bytes(4, 'big')
    header[56:64] = (_uint(data[56:64]) & 15).to_bytes(8, 'big')
    header[80:128] = b'\0' * 48  # Creator, old profile ID and reserved bytes.
    table = bytearray(); payload = bytearray(); offsets = {}
    start = 132 + len(cleaned_tags) * 12
    for signature, value in cleaned_tags.items():
        if value in offsets:
            offset = offsets[value]
        else:
            payload.extend(b'\0' * (-(start + len(payload)) % 4))
            offset = start + len(payload); offsets[value] = offset; payload.extend(value)
        table.extend(signature + struct.pack('>II', offset, len(value)))
    result = bytearray(header + struct.pack('>I', len(cleaned_tags)) + table + payload)
    result.extend(b'\0' * (-len(result) % 4)); result[:4] = struct.pack('>I', len(result))
    if version == 4:
        hashed = bytearray(result); hashed[44:48] = b'\0' * 4; hashed[64:68] = b'\0' * 4
        result[84:100] = hashlib.md5(hashed, usedforsecurity=False).digest()
    cleaned = bytes(result)
    try:
        _prove_transforms(data, cleaned, modes[data[16:20]])
    except (ImageCms.PyCMSError, ValueError, TypeError, OSError) as exc:
        raise ValueError('Não foi possível preservar a transformação do perfil ICC ao remover seus metadados.') from exc
    return cleaned
