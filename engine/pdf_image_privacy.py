"""Remove standard JPEG descriptive metadata without recompressing pixels.

Supported ICC color transforms are retained after their declared descriptions
are removed. This is not a steganography detector; unsupported image containers
or ICC structures are refused by the redaction operation.
"""
from __future__ import annotations


def strip_jpeg_metadata(data):
    if not data.startswith(b'\xff\xd8') or len(data) > 128 * 1024**2:
        raise ValueError('O contêiner JPEG é inválido ou excede o limite de 128 MiB.')
    output = bytearray(data[:2]); position = 2; scans = 0
    icc_chunks = {}; icc_count = None; icc_position = None
    while position < len(data):
        start = position
        if data[position] != 0xff:
            raise ValueError('O contêiner JPEG contém um marcador inválido.')
        while position < len(data) and data[position] == 0xff:
            position += 1
        if position >= len(data):
            break
        marker = data[position]; position += 1
        if marker == 0xd9:
            if not scans:
                raise ValueError('O JPEG não contém dados de imagem.')
            output.extend(b'\xff\xd9')
            # Bytes after EOI are not image data and may contain attachments.
            if icc_position is not None:
                clean_markers = _clean_icc_markers(icc_chunks, icc_count)
                output[icc_position:icc_position] = clean_markers
            if len(output) > 128 * 1024**2:
                raise ValueError('O JPEG saneado excede o limite de inspeção.')
            return bytes(output)
        if marker in (0x00, 0xd8) or 0xd0 <= marker <= 0xd7:
            raise ValueError('O contêiner JPEG contém marcador fora de contexto.')
        if marker == 0x01:
            output.extend(data[start:position]); continue
        if position + 2 > len(data):
            break
        length = int.from_bytes(data[position:position + 2], 'big')
        if length < 2 or position + length > len(data):
            raise ValueError('Um segmento JPEG está truncado.')
        payload = data[position + 2:position + length]
        end = position + length
        if marker == 0xe0:
            if payload.startswith(b'JFIF\x00') and len(payload) >= 14:
                # Keep density/color interpretation, discard its RGB thumbnail.
                header = payload[:12] + b'\x00\x00'
                output.extend(b'\xff\xe0' + (len(header) + 2).to_bytes(2, 'big') + header)
            elif payload.startswith(b'JFXX\x00'):
                pass
            else:
                raise ValueError('O JPEG contém extensão APP0 não suportada para sanitização segura.')
        elif marker == 0xe2:
            if payload.startswith(b'ICC_PROFILE\x00'):
                if len(payload) < 14:
                    raise ValueError('O segmento ICC do JPEG está truncado.')
                sequence, count = payload[12], payload[13]
                if not 1 <= sequence <= count or (icc_count is not None and count != icc_count) or sequence in icc_chunks:
                    raise ValueError('Os segmentos ICC do JPEG são duplicados ou ambíguos.')
                icc_count = count
                if icc_position is None:
                    icc_position = len(output)
                icc_chunks[sequence] = payload[14:]
            # MPF and other APP2 payloads may carry extra photos/private data.
        elif marker == 0xee:
            if not payload.startswith(b'Adobe') or len(payload) < 12:
                raise ValueError('O JPEG contém extensão APP14 não suportada para sanitização segura.')
            header = payload[:12]
            output.extend(b'\xff\xee' + (len(header) + 2).to_bytes(2, 'big') + header)
        elif 0xe0 <= marker <= 0xef or marker == 0xfe:
            # APP1 (EXIF/XMP), APP13 (IPTC/Photoshop), COM and other
            # application markers do not belong to the compressed scan.
            pass
        else:
            output.extend(data[start:end])
        position = end
        if marker == 0xda:
            scans += 1
            entropy_start = position
            while position < len(data):
                if data[position] != 0xff:
                    position += 1; continue
                candidate = position
                while position < len(data) and data[position] == 0xff:
                    position += 1
                if position >= len(data):
                    break
                code = data[position]
                if code == 0x00 or 0xd0 <= code <= 0xd7:
                    position += 1; continue
                output.extend(data[entropy_start:candidate])
                position = candidate
                break
    raise ValueError('O JPEG está truncado ou não possui marcador de final.')


def _clean_icc_markers(chunks, count):
    from pdf_icc_privacy import sanitize_icc
    if count is None or set(chunks) != set(range(1, count + 1)):
        raise ValueError('O perfil ICC segmentado do JPEG está incompleto.')
    original = b''.join(chunks[index] for index in range(1, count + 1))
    cleaned = sanitize_icc(original)
    maximum = 65_519  # 65535-byte marker length minus 2-byte length and 14-byte ICC header.
    count = (len(cleaned) + maximum - 1) // maximum
    if not 1 <= count <= 255:
        raise ValueError('O perfil ICC não cabe na segmentação JPEG suportada.')
    result = bytearray()
    for index in range(count):
        payload = b'ICC_PROFILE\x00' + bytes((index + 1, count)) + cleaned[index * maximum:(index + 1) * maximum]
        result.extend(b'\xff\xe2' + (len(payload) + 2).to_bytes(2, 'big') + payload)
    return bytes(result)
