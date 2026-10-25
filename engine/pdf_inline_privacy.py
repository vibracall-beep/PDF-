"""Sanitize encoded inline-image containers without recompressing pixels."""
from __future__ import annotations

from pyhanko.pdf_utils import generic as g

from pdf_image_privacy import strip_jpeg_metadata


def sanitize_asciihex_image(values, encoded):
    """Inspect the filter chain emitted by MuPDF's ASCII inline normalizer.

    PDF page streams may wrap JPEG/JPX bytes in ASCIIHex. Removing metadata
    only from image XObjects would leave the same payload in these streams.
    Other image filters encode samples, not descriptive JPEG containers.
    """
    filters = values.get('/F', values.get('/Filter'))
    filters = list(filters) if isinstance(filters, g.ArrayObject) else [filters]
    if not 1 <= len(filters) <= 8 or any(not isinstance(item, g.NameObject) for item in filters):
        raise ValueError('A cadeia de filtros da imagem inline não pôde ser inspecionada.')
    names = [str(item) for item in filters]
    if names[0] not in ('/AHx', '/ASCIIHexDecode'):
        raise ValueError('A imagem inline não foi normalizada em ASCIIHex.')
    if any(item in ('/JPX', '/JPXDecode', '/JBIG2', '/JBIG2Decode') for item in names):
        raise ValueError('Imagens inline JPEG2000/JBIG2 exigem uma cópia estática revisada; os metadados desses contêineres não são saneados.')
    if not any(item in ('/DCT', '/DCTDecode') for item in names):
        return encoded
    if len(names) != 2 or names[1] not in ('/DCT', '/DCTDecode'):
        raise ValueError('A cadeia de filtros JPEG inline não pode ser saneada com segurança.')
    # Decode only the outer ASCIIHex layer. The JPEG entropy stream, color
    # profile, Adobe color transform and PDF decoding parameters stay intact.
    hexadecimal = b''.join(encoded[:-1].split())
    if len(hexadecimal) % 2:
        hexadecimal += b'0'
    try:
        data = bytes.fromhex(hexadecimal.decode('ascii'))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Os dados ASCIIHex da imagem inline são inválidos.') from exc
    cleaned = strip_jpeg_metadata(data)
    return encoded if cleaned == data else cleaned.hex().encode('ascii') + b'>'
