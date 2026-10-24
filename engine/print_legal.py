"""Print preflight and legal production tools; all outputs are new files.

Coordinates use unrotated PDF page points. Preflight is a diagnostic, never an
independent PDF/X certification. PDF/X conversion requires an explicit ICC file.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

import fitz


def _json(output, value):
    Path(output).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def preflight(source, output, options):
    from pdf_engine import open_pdf, number
    minimum = number(options.get('minimum_dpi', 200), 'Resolução mínima', 36, 2400)
    findings, pages = [], []
    with open_pdf(source, options.get('password', '')) as document:
        for index, page in enumerate(document):
            fonts, images = [], []
            for font in page.get_fonts(full=True):
                xref, extension, kind, name, resource, *_ = font
                embedded = False
                if xref:
                    try:
                        embedded = bool(document.extract_font(xref)[3])
                    except (ValueError, RuntimeError):
                        pass
                fonts.append(dict(name=name, type=kind, embedded=embedded, resource=resource))
                if not embedded:
                    findings.append(dict(page=index + 1, code='font-not-embedded', detail=name))
            for image in page.get_image_info(xrefs=True):
                # Matrix columns describe the on-page lengths of image axes,
                # even if the image is rotated or skewed.
                a, b, c, d, _, _ = image['transform']
                width, height = math.hypot(a, b), math.hypot(c, d)
                dpi_x = image['width'] * 72 / width if width > 0 else None
                dpi_y = image['height'] * 72 / height if height > 0 else None
                item = dict(xref=image['xref'], rect=list(image['bbox']), pixels=[image['width'], image['height']],
                            dpi_x=dpi_x, dpi_y=dpi_y, color_space=image['cs-name'])
                images.append(item)
                if dpi_x is None or dpi_y is None or min(dpi_x, dpi_y) < minimum:
                    findings.append(dict(page=index + 1, code='low-image-resolution', detail=item))
            if list(page.trimbox) == list(page.mediabox):
                findings.append(dict(page=index + 1, code='no-distinct-trim', detail='A área final coincide com a folha.'))
            pages.append(dict(page=index + 1, media=list(page.mediabox), crop=list(page.cropbox),
                              trim=list(page.trimbox), bleed=list(page.bleedbox), fonts=fonts, images=images))
        intent = document.xref_get_key(document.pdf_catalog(), 'OutputIntents')
        _json(output, dict(schema_version=1, source_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                           page_count=len(document), minimum_dpi=minimum, pages=pages, findings=findings,
                           output_intents_present=intent[0] != 'null', independently_certified=False,
                           scope='Fontes, resolução efetiva e caixas. Não certifica PDF/X, separações, sobreimpressão ou fidelidade de cor.'))


def prepare_print(source, output, options):
    from pdf_engine import open_pdf, number, parse_pages, save
    inset = number(options.get('trim_inset', 18), 'Margem de corte', 0, 144)
    bleed = number(options.get('bleed', 8.5), 'Sangria', 0, 72)
    marks = options.get('crop_marks', True)
    if not isinstance(marks, bool) or bleed > inset:
        raise ValueError('A sangria deve caber na margem de corte; crop_marks deve ser booleano.')
    with open_pdf(source, options.get('password', '')) as document:
        for index in parse_pages(options.get('pages'), len(document)):
            page = document[index]
            if page.rotation or page.mediabox.x0 != 0 or page.mediabox.y0 != 0:
                raise ValueError('Prepare uma cópia sem rotação e com origem da folha em zero antes de definir marcas de corte.')
            trim = page.mediabox + (inset, inset, -inset, -inset)
            if trim.is_empty or min(trim.width, trim.height) < 20:
                raise ValueError('A margem de corte elimina a área útil da página.')
            page.set_trimbox(trim)
            page.set_bleedbox(trim + (-bleed, -bleed, bleed, bleed))
            if marks:
                length = min(9, max(0, inset - bleed - 2))
                if length <= 0:
                    raise ValueError('Não há espaço entre a sangria e a borda para marcas de corte.')
                for x in (trim.x0, trim.x1):
                    for y in (trim.y0, trim.y1):
                        direction_x = -1 if x == trim.x0 else 1
                        direction_y = -1 if y == trim.y0 else 1
                        gap = bleed + 2
                        page.draw_line((x + direction_x * gap, y), (x + direction_x * (gap + length), y), color=(0, 0, 0), width=.25)
                        page.draw_line((x, y + direction_y * gap), (x, y + direction_y * (gap + length)), color=(0, 0, 0), width=.25)
        save(document, output)


def pdfx(source, output, options):
    from pdf_engine import open_pdf, _external
    profile = Path(options.get('icc_profile', ''))
    if not profile.is_file() or profile.is_symlink() or not 128 <= profile.stat().st_size <= 16 * 1024**2:
        raise ValueError('Escolha um perfil ICC CMYK regular, de até 16 MiB, fornecido pela gráfica.')
    data = profile.read_bytes()
    if data[36:40] != b'acsp' or data[16:20] != b'CMYK' or int.from_bytes(data[:4], 'big') != len(data):
        raise ValueError('O perfil precisa ser um ICC CMYK válido, com tamanho declarado correto.')
    condition = options.get('output_condition', 'User supplied CMYK printing condition')
    if not isinstance(condition, str) or not re.fullmatch(r'[A-Za-z0-9 ._/-]{1,120}', condition):
        raise ValueError('Descreva a condição de impressão usando até 120 caracteres ASCII simples.')
    with open_pdf(source, options.get('password', '')) as document:
        if document.metadata.get('encryption'):
            raise ValueError('PDF/X não permite criptografia. Desbloqueie uma cópia explicitamente.')
    executable = shutil.which('gs')
    if not executable:
        raise RuntimeError('Ghostscript não está instalado.')
    with tempfile.TemporaryDirectory(prefix='pdf-print-') as temporary:
        folder = Path(temporary)
        icc = folder / 'output.icc'; icc.write_bytes(data)
        # Hex strings avoid interpreting paths or labels as PostScript code.
        path_hex = str(icc).encode('utf-8').hex()
        label_hex = condition.encode('ascii').hex()
        definition = folder / 'output-intent.ps'
        definition.write_text(f'''%!
[ /GTS_PDFXVersion (PDF/X-3:2002) /Title (PDF print copy) /Trapped /False /DOCINFO pdfmark
[/_objdef {{icc_pdf}} /type /stream /OBJ pdfmark
[{{icc_pdf}} << /N 4 >> /PUT pdfmark
[{{icc_pdf}} <{path_hex}> (r) file /PUT pdfmark
[/_objdef {{OutputIntent_PDFX}} /type /dict /OBJ pdfmark
[{{OutputIntent_PDFX}} << /Type /OutputIntent /S /GTS_PDFX
/OutputConditionIdentifier <{label_hex}> /Info <{label_hex}>
/RegistryName (http://www.color.org) /DestOutputProfile {{icc_pdf}} >> /PUT pdfmark
[{{Catalog}} << /OutputIntents [{{OutputIntent_PDFX}}] >> /PUT pdfmark
''', encoding='ascii')
        _external([executable, '-dBATCH', '-dNOPAUSE', '-dSAFER', '-dPDFX=3', '-dPDFXCompatibilityPolicy=2',
                   '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.3', '-dEmbedAllFonts=true',
                   '-sColorConversionStrategy=CMYK', '-sProcessColorModel=DeviceCMYK',
                   '-sOutputICCProfile=' + str(icc), '--permit-file-read=' + str(icc),
                   '-sOutputFile=' + str(output), str(definition), str(source)], timeout=300)
        with fitz.open(output) as result:
            intent = result.xref_get_key(result.pdf_catalog(), 'OutputIntents')
            metadata = result.xref_get_key(-1, 'Info')
            info = result.xref_object(int(metadata[1].split()[0])) if metadata[0] == 'xref' else ''
            if intent[0] == 'null' or 'GTS_PDFXVersion' not in info or len(result) == 0:
                raise RuntimeError('O conversor não produziu a identificação PDF/X e o perfil de saída esperados.')


def bates(source, output, options):
    from pdf_engine import open_pdf, parse_pages, integer, number, _html_text, color, save, _checked_text
    prefix = _checked_text(options.get('prefix', 'DOC-'))
    suffix = _checked_text(options.get('suffix', ''))
    if len(prefix) + len(suffix) > 100:
        raise ValueError('Prefixo e sufixo devem totalizar até 100 caracteres.')
    start = integer(options.get('start', 1), 'Início', 0, 10**12)
    digits = integer(options.get('digits', 6), 'Dígitos', 1, 16)
    size = number(options.get('font_size', 10), 'Fonte', 4, 36)
    with open_pdf(source, options.get('password', '')) as document:
        for offset, index in enumerate(parse_pages(options.get('pages'), len(document))):
            page = document[index]
            bounds = page.rect * page.derotation_matrix
            rect = fitz.Rect(bounds.x0 + 18, bounds.y1 - 36, bounds.x1 - 18, bounds.y1 - 12)
            _html_text(page, rect, prefix + str(start + offset).zfill(digits) + suffix, size,
                       color(options.get('color')), align=2)
        save(document, output)


def stamp(source, output, options):
    from pdf_engine import open_pdf, parse_pages, rectangle, _html_text, color, number, save, _checked_text
    text = _checked_text(options.get('text', 'REVISADO'))
    if not text.strip() or len(text) > 200:
        raise ValueError('O carimbo deve conter entre 1 e 200 caracteres.')
    with open_pdf(source, options.get('password', '')) as document:
        for index in parse_pages(options.get('pages'), len(document)):
            page = document[index]
            rect = rectangle(options, page)
            ink = color(options.get('color'), (0.6, 0.1, 0.1))
            size = number(options.get('font_size', 14), 'Fonte', 4, 72)
            page.draw_rect(rect, color=ink, width=1.2)
            _html_text(page, rect + (4, 4, -4, -4), text, size, ink, align=1)
        save(document, output)


def measure(source, output, options):
    from pdf_engine import open_pdf, integer, number
    points = options.get('points')
    if not isinstance(points, list) or not 2 <= len(points) <= 1000:
        raise ValueError('Informe de 2 a 1.000 pontos para medir distância, perímetro ou área.')
    with open_pdf(source, options.get('password', '')) as document:
        index = integer(options.get('page', 1), 'Página', 1, len(document)) - 1
        bounds = document[index].rect * document[index].derotation_matrix
        checked = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError('Cada ponto precisa de duas coordenadas.')
            x = number(point[0], 'Coordenada X', bounds.x0, bounds.x1)
            y = number(point[1], 'Coordenada Y', bounds.y0, bounds.y1)
            checked.append((x, y))
        scale = number(options.get('scale', 1), 'Denominador da escala', .000001, 10**9)
        unit = options.get('unit', 'm')
        if unit not in ('mm', 'cm', 'm'):
            raise ValueError('Escolha mm, cm ou m.')
        factor = 25.4 / 72 * scale / {'mm': 1, 'cm': 10, 'm': 1000}[unit]
        distance = sum(math.dist(a, b) for a, b in zip(checked, checked[1:])) * factor
        closed = options.get('closed', False)
        if not isinstance(closed, bool) or (closed and len(checked) < 3):
            raise ValueError('Uma área fechada precisa de três ou mais pontos.')
        if any(a == b for a, b in zip(checked, checked[1:])) or (closed and checked[0] == checked[-1]):
            raise ValueError('Remova pontos consecutivos repetidos; o fechamento do polígono é automático.')
        area = None
        if closed:
            def turn(a, b, c):
                return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            def within(a, b, p):
                return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
            edges = list(zip(checked, checked[1:] + checked[:1]))
            for i, (a, b) in enumerate(edges):
                for j in range(i + 1, len(edges)):
                    if j == i + 1 or (i == 0 and j == len(edges) - 1):
                        continue
                    c, d = edges[j]
                    t1, t2, t3, t4 = turn(a, b, c), turn(a, b, d), turn(c, d, a), turn(c, d, b)
                    if ((t1 > 0) != (t2 > 0) and (t3 > 0) != (t4 > 0)) or any(
                        t == 0 and within(x, y, p) for t, x, y, p in ((t1, a, b, c), (t2, a, b, d), (t3, c, d, a), (t4, c, d, b))):
                        raise ValueError('O polígono cruza a si mesmo. Corrija a ordem dos pontos antes de calcular a área.')
            distance += math.dist(checked[-1], checked[0]) * factor
            area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(checked, checked[1:] + checked[:1]))) / 2 * factor**2
            if area == 0:
                raise ValueError('Os pontos não delimitam uma área positiva.')
        _json(output, dict(schema_version=1, source_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                           page=index + 1, scale=scale, unit=unit, points=checked, closed=closed, distance=distance, area=area,
                           scope='Escala informada pelo usuário; confirme uma medida conhecida. Não substitui levantamento técnico.'))


def dossier(inputs, output, options):
    from pdf_engine import open_pdf, _encrypted_output, save, _html_text
    credentials = options.get('input_passwords', [options.get('password', '')] * len(inputs))
    if not isinstance(credentials, list) or len(credentials) != len(inputs) or not all(isinstance(item, str) for item in credentials):
        raise ValueError('Informe uma senha por documento.')
    titles = options.get('titles', [Path(item).stem for item in inputs])
    if not isinstance(titles, list) or len(titles) != len(inputs) or not all(isinstance(item, str) and 0 < len(item) <= 100 for item in titles):
        raise ValueError('Informe um título de até 100 caracteres por documento.')
    if len(inputs) > 500:
        raise ValueError('Um conjunto aceita até 500 documentos.')
    documents = []
    try:
        for path, password in zip(inputs, credentials):
            documents.append(open_pdf(path, password))
        protected = [(doc, password) for doc, password in zip(documents, credentials) if doc.metadata.get('encryption')]
        protection = {}
        if protected:
            passwords = {password for _, password in protected}
            output_password = options.get('output_password') or (next(iter(passwords)) if len(passwords) == 1 else None)
            if not output_password or not isinstance(output_password, str):
                raise ValueError('Escolha uma senha de saída ao reunir documentos com senhas diferentes.')
            protection = _encrypted_output(protected[0][0], output_password)
            permissions = protected[0][0].permissions
            for document, _ in protected[1:]:
                permissions &= document.permissions
            protection['permissions'] = permissions
        with fitz.open() as result:
            index_pages = math.ceil(len(documents) / 20)
            for _ in range(index_pages):
                result.new_page(width=595, height=842)
            cursor = index_pages
            toc = []
            for index, (document, title) in enumerate(zip(documents, titles)):
                if not len(document):
                    raise ValueError('Um dos documentos está vazio.')
                result.insert_pdf(document, links=True, annots=True, widgets=True)
                page = result[index // 20]
                if index % 20 == 0:
                    _html_text(page, fitz.Rect(36, 30, 559, 75), 'Índice de documentos', 20, (0, 0, 0))
                row = fitz.Rect(36, 90 + (index % 20) * 34, 559, 120 + (index % 20) * 34)
                _html_text(page, row, f'{index + 1}. {title} — página {cursor + 1}', 10, (0, 0, 0))
                page.insert_link({'kind': fitz.LINK_GOTO, 'from': row, 'page': cursor, 'to': fitz.Point(0, 0)})
                toc.append([1, title, cursor + 1])
                cursor += len(document)
            result.set_toc(toc)
            save(result, output, **protection)
    finally:
        for document in documents:
            document.close()
