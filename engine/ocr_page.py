"""Recognize a local PNG with real Tesseract words and normalized geometry.

This is a recognition transport, not a PDF renderer or a Vision implementation.
The caller owns atomic publication. No recognized text is emitted to logs.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from PIL import Image, UnidentifiedImageError

from scan_analysis import _read_words

INPUT_LIMIT = 128 * 1024 * 1024
OUTPUT_LIMIT = 16 * 1024 * 1024
PIXEL_LIMIT = 40_000_000
WORD_LIMIT = 50_000
TEXT_LIMIT = 8 * 1024 * 1024
LANGUAGES = {'en': 'eng', 'pt': 'por+eng'}


def _read_regular(path, limit):
    """Refuse links, pipes and changing/oversized input before decoding bytes."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_CLOEXEC', 0))
    except OSError:
        raise ValueError('Selecione um arquivo local regular e legível, sem link simbólico.') from None
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError('O arquivo precisa ser regular, não vazio e respeitar o limite de tamanho do OCR.')
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if len(data) != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('O arquivo mudou durante a leitura. Selecione uma cópia estável.')
    return data


def _private_write(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)


def _image(data):
    try:
        with Image.open(io.BytesIO(data)) as candidate:
            if candidate.format != 'PNG' or getattr(candidate, 'n_frames', 1) != 1:
                raise ValueError('O reconhecimento de página aceita um único PNG estático.')
            width, height = candidate.size
            if not 0 < width <= 30_000 or not 0 < height <= 30_000 or width * height > PIXEL_LIMIT:
                raise ValueError('A imagem excede 40 milhões de pixels ou as dimensões permitidas para OCR.')
            candidate.verify()
        with Image.open(io.BytesIO(data)) as candidate:
            candidate.load()
            # Vision's canonical page is already opaque; explicit alpha handling
            # also makes direct CLI inputs reproducible against a white page.
            if 'A' in candidate.getbands() or 'transparency' in candidate.info:
                foreground = candidate.convert('RGBA')
                background = Image.new('RGBA', candidate.size, (255,255,255,255))
                background.alpha_composite(foreground)
                return background.convert('RGB')
            return candidate.convert('RGB')
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ValueError('O PNG está inválido, incompleto ou excede os limites de leitura.') from None


def _observations(tsv, width, height):
    words = _read_words(tsv, width, height)
    if len(words) > WORD_LIMIT:
        raise RuntimeError('O OCR excedeu o limite de 50.000 observações por página.')
    observations = []
    total = 0
    for word in words:
        x0,y0,x1,y1 = word['rect']
        # The shared scan parser tolerates tiny border offsets; this transport
        # is stricter because the native renderer consumes normalized bounds.
        if not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height:
            raise RuntimeError('O OCR retornou coordenadas fora da imagem.')
        length = len(word['text'].encode('utf-8'))
        total += length
        if not 0 < length <= 65_536 or total > TEXT_LIMIT:
            raise RuntimeError('O texto reconhecido excedeu os limites de uma página.')
        observations.append(dict(string=word['text'], confidence=word['confidence'],
            boundingBox=dict(origin=dict(x=x0/width, y=(height-y1)/height),
                             size=dict(width=(x1-x0)/width, height=(y1-y0)/height))))
    return observations


def recognize(input_path, output_path, options, external):
    language = options.get('language', 'en')
    if not isinstance(language, str) or language not in LANGUAGES:
        raise ValueError('Selecione o idioma en (inglês) ou pt (português e inglês).')
    image = _image(_read_regular(input_path, INPUT_LIMIT))
    executable = shutil.which('tesseract')
    if not executable:
        raise RuntimeError('Tesseract não está instalado. Execute o instalador completo do PDF.')
    try:
        installed = external([executable, '--list-langs'], timeout=10)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Não foi possível consultar os idiomas do Tesseract instalado.') from None
    available = set(installed.stdout.splitlines())
    missing = set(LANGUAGES[language].split('+')) - available
    if missing:
        # Tesseract can exit zero after dropping an unavailable requested
        # language. Refuse that silent downgrade before recognizing the page.
        raise RuntimeError('O Tesseract não possui todos os idiomas solicitados: '+', '.join(sorted(missing))+'. Execute o instalador completo do PDF.')
    width,height = image.size
    # Same private transaction as the JSON output; cleanup includes interruption.
    with tempfile.TemporaryDirectory(prefix='.ocr-page-', dir=Path(output_path).parent) as temporary:
        root = Path(temporary)
        image.info.clear()
        encoded = io.BytesIO(); image.save(encoded, format='PNG')
        image.close()
        source = root/'input.png'; target = root/'recognized'
        _private_write(source, encoded.getvalue())
        try:
            external([executable, source, target, '-l', LANGUAGES[language], '--psm', '3', 'tsv'], timeout=60)
        except subprocess.TimeoutExpired:
            raise RuntimeError('O Tesseract excedeu 60 segundos; nenhum resultado foi publicado.') from None
        except (RuntimeError, OSError):
            # Converter stderr can contain source paths or recognized content.
            # Keep those bytes out of CLI/application logs and structured errors.
            raise RuntimeError('O Tesseract não conseguiu reconhecer a página. Confira a instalação e os idiomas eng/por selecionados.') from None
        try:
            tsv = _read_regular(target.with_suffix('.tsv'), OUTPUT_LIMIT).decode('utf-8', errors='strict')
        except (ValueError, UnicodeError):
            raise RuntimeError('O Tesseract não produziu uma resposta TSV válida dentro do limite de 16 MiB.') from None
        observations = _observations(tsv, width, height)
    response = dict(version=1, language=language, width=width, height=height,
                    backend='tesseract', observations=observations)
    data = json.dumps(response, ensure_ascii=False, separators=(',',':')).encode('utf-8')
    if len(data) > OUTPUT_LIMIT:
        raise RuntimeError('O resultado de reconhecimento excede 16 MiB.')
    _private_write(output_path, data)
    return response
