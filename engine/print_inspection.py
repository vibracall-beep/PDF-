"""Bounded, independent structural inspection for print production.

pyHanko reads the original PDF objects, independently of the MuPDF geometry
reader and Ghostscript converter. The checks are deliberately enumerated: this
is not a complete ISO 15930 validator or a colorimetric proof of the press.
Resource declarations are not reported as proof that a mark uses those inks.
"""
from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
import re
import shutil
import tempfile

from PIL import ImageCms
from pyhanko.pdf_utils import generic as g
from pyhanko.pdf_utils.reader import PdfFileReader


def icc_description(data):
    """Check the ICC container and let LittleCMS parse the actual profile."""
    if not 132 <= len(data) <= 16 * 1024**2:
        raise ValueError('O perfil ICC deve ter entre 132 bytes e 16 MiB.')
    if data[36:40] != b'acsp' or int.from_bytes(data[:4], 'big') != len(data):
        raise ValueError('Assinatura ou tamanho declarado do perfil ICC inválido.')
    count = int.from_bytes(data[128:132], 'big')
    if not count or count > 4096 or 132 + 12 * count > len(data):
        raise ValueError('A tabela de tags do perfil ICC está truncada ou excede o limite.')
    names = set()
    for position in range(132, 132 + 12 * count, 12):
        name = data[position:position + 4]
        offset = int.from_bytes(data[position + 4:position + 8], 'big')
        size = int.from_bytes(data[position + 8:position + 12], 'big')
        if name in names or offset < 132 + 12 * count or offset % 4 or size < 8 or offset + size > len(data):
            raise ValueError('Uma tag do perfil ICC é duplicada, inválida ou está fora do arquivo.')
        names.add(name)
    if int.from_bytes(data[64:68], 'big') > 3:
        raise ValueError('A intenção de renderização declarada no ICC é inválida.')
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(data)).profile
        return dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                    description=profile.profile_description, color_space=profile.xcolor_space.strip(),
                    device_class=profile.device_class.strip(), connection_space=profile.connection_space.strip(),
                    version=f'{data[8]}.{data[9] >> 4}.{data[9] & 15}',
                    rendering_intent=int.from_bytes(data[64:68], 'big'), tags=count)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('LittleCMS não conseguiu interpretar o perfil ICC.') from exc


def read_cmyk_profile(path):
    from pdf_signatures import _bounded_file
    data = _bounded_file(path)
    profile = icc_description(data)
    if profile['color_space'] != 'CMYK' or profile['device_class'] != 'prtr':
        raise ValueError('Escolha um perfil ICC CMYK de saída de impressão, fornecido pela gráfica.')
    try:
        ImageCms.buildTransform(ImageCms.createProfile('LAB'), ImageCms.ImageCmsProfile(io.BytesIO(data)), 'LAB', 'CMYK')
    except (ImageCms.PyCMSError, OSError, ValueError) as exc:
        raise ValueError('O perfil ICC não contém uma transformação de saída CMYK interpretável.') from exc
    return data, profile


def _object(value):
    return value.get_object() if isinstance(value, (g.IndirectObject, g.DecryptedObjectProxy)) else value


def _raw(value, key, default=None):
    if not isinstance(value, g.DictionaryObject):
        return default
    try:
        return value.raw_get(key)
    except KeyError:
        return default


def _identity(value):
    return ('ref', value.idnum, value.generation) if isinstance(value, g.IndirectObject) else ('direct', id(value))


def _array(value):
    value = _object(value)
    return list(value) if isinstance(value, g.ArrayObject) else []


def _boolean(value):
    value = _object(value)
    return bool(value) if isinstance(value, (g.BooleanObject, bool)) else None


def _numeric(value):
    value = _object(value)
    if isinstance(value, (g.NumberObject, g.FloatObject)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def inspect_structure(path, password=''):
    """Return facts and bounded checks; no result is a PDF/X certification."""
    findings = []
    with Path(path).open('rb') as stream:
        reader = PdfFileReader(stream, strict=True)
        # MuPDF and several legacy producers write a direct /Encrypt
        # dictionary. Retain read-only diagnostics for those files, while
        # explicitly refusing to call their structure strictly validated.
        parser_mode = 'strict'
        try:
            encryption_reference = reader.trailer.raw_get('/Encrypt')
        except KeyError:
            encryption_reference = None
        if isinstance(encryption_reference, g.DictionaryObject):
            stream.seek(0)
            reader = PdfFileReader(stream, strict=False)
            parser_mode = 'compatibility-direct-encryption'
            findings.append(dict(page=None, code='direct-encryption-dictionary', detail='Diagnóstico compatível de /Encrypt direto; estrutura estrita não aprovada.'))
        encrypted = reader.encrypted
        if encrypted and reader.decrypt(password).status.name == 'FAILED':
            raise ValueError('Senha necessária ou incorreta para inspecionar a estrutura de impressão.')
        count = int(reader.root['/Pages']['/Count'])
        if not 0 < count <= 10000:
            raise ValueError('O diagnóstico de impressão aceita até 10.000 páginas por arquivo.')
        pages, output_intents = [], []
        profile_cache = {}
        visited_budget = 0

        def profile_info(value):
            identity = _identity(value)
            if identity not in profile_cache:
                profile = _object(value)
                if not isinstance(profile, g.StreamObject):
                    raise ValueError('O perfil ICC incorporado não é um stream.')
                profile_cache[identity] = icc_description(profile.data)
            return profile_cache[identity]

        intents = _object(_raw(reader.root, '/OutputIntents'))
        if intents is not None and not isinstance(intents, (g.ArrayObject, g.NullObject)):
            findings.append(dict(page=None, code='invalid-output-intents', detail='OutputIntents não é uma lista.'))
        for index, reference in enumerate(_array(intents)):
            obj = _object(reference)
            item = dict(index=index, subtype=None, condition=None, profile=None)
            if not isinstance(obj, g.DictionaryObject):
                item['error'] = 'OutputIntent não é um dicionário.'
            else:
                item['subtype'] = str(obj.get('/S', ''))
                item['condition'] = str(_object(obj.get('/OutputConditionIdentifier', '')))[:1024]
                item['info'] = str(_object(obj.get('/Info', '')))[:1024]
                try:
                    item['profile'] = profile_info(_raw(obj, '/DestOutputProfile'))
                    embedded = _object(_raw(obj, '/DestOutputProfile'))
                    channels = _numeric(embedded.get('/N'))
                    expected = {'CMYK': 4, 'RGB': 3, 'GRAY': 1}.get(item['profile']['color_space'])
                    if channels != expected or expected is None:
                        raise ValueError('O número de canais /N não corresponde ao perfil ICC.')
                except (ValueError, OSError, TypeError) as exc:
                    item['error'] = str(exc)
            output_intents.append(item)
            if 'error' in item:
                findings.append(dict(page=None, code='invalid-output-profile', detail=item))
        if not output_intents:
            findings.append(dict(page=None, code='missing-output-intent', detail='Nenhuma condição de impressão incorporada.'))

        for index in range(count):
            reference, resources = reader.find_page_for_modification(index)
            page = reference.get_object()
            entry = dict(page=index + 1, color_spaces=[], spot_inks=[], graphics_states=[],
                         transparency_groups=[], fonts=[], uninspected=[])
            seen, active = set(), set()

            def finding(code, detail):
                findings.append(dict(page=index + 1, code=code, detail=detail))

            def mapping(value, location):
                value = _object(value)
                # A null-valued dictionary entry is equivalent to absence in
                # PDF; it is not evidence of an invalid resource category.
                if value is None or isinstance(value, g.NullObject):
                    return g.DictionaryObject()
                if not isinstance(value, g.DictionaryObject):
                    entry['uninspected'].append(location + ': dicionário de recursos inválido')
                    return g.DictionaryObject()
                return value

            def colors(value, location, depth=0, ancestors=()):
                if depth > 24 or _identity(value) in ancestors:
                    entry['uninspected'].append(location + ': espaço de cor recursivo ou profundo')
                    return
                ancestors = ancestors + (_identity(value),)
                obj = _object(value)
                if isinstance(obj, g.NameObject):
                    entry['color_spaces'].append(dict(location=location, kind=str(obj)))
                    if str(obj) not in ('/DeviceCMYK', '/DeviceRGB', '/DeviceGray', '/Pattern'):
                        entry['uninspected'].append(location + ': espaço de cor não reconhecido ' + str(obj))
                    return
                if not isinstance(obj, g.ArrayObject) or not obj:
                    entry['uninspected'].append(location + ': espaço de cor inválido')
                    return
                kind = str(_object(obj[0]))
                item = dict(location=location, kind=kind)
                sizes = {'/ICCBased': (2,), '/Separation': (4,), '/DeviceN': (4, 5), '/Indexed': (4,),
                         '/Pattern': (1, 2), '/CalGray': (2,), '/CalRGB': (2,), '/Lab': (2,)}
                if kind not in sizes or len(obj) not in sizes[kind]:
                    item['error'] = 'Tipo ou quantidade de parâmetros de cor não reconhecido.'
                    entry['uninspected'].append(location + ': ' + item['error'])
                    entry['color_spaces'].append(item)
                    return
                if kind == '/ICCBased':
                    try:
                        item['profile'] = profile_info(obj[1])
                        embedded = _object(obj[1])
                        channels = _numeric(embedded.get('/N'))
                        expected = {'CMYK': 4, 'RGB': 3, 'GRAY': 1}.get(item['profile']['color_space'])
                        if expected is None or channels != expected:
                            raise ValueError('O número de canais /N não corresponde ao perfil de cor.')
                    except (ValueError, IndexError, OSError, TypeError) as exc:
                        item['error'] = str(exc)
                        finding('invalid-color-profile', item)
                elif kind in ('/Separation', '/DeviceN'):
                    raw_names = [_object(obj[1])] if kind == '/Separation' else [_object(name) for name in _array(obj[1])]
                    if not raw_names or not all(isinstance(name, g.NameObject) for name in raw_names):
                        entry['uninspected'].append(location + ': nomes das tintas inválidos')
                    names = [str(name) for name in raw_names if isinstance(name, g.NameObject)]
                    item['colorants'] = names
                    entry['spot_inks'].extend(name[1:] for name in names if name not in ('/None', '/All'))
                    if '/All' in names:
                        finding('registration-color', dict(location=location, detail='A cor /All marca todas as chapas; confira se está restrita às marcas.'))
                    if len(obj) >= 3:
                        colors(obj[2], location + '/alternate', depth + 1, ancestors)
                elif kind in ('/Indexed', '/Pattern') and len(obj) >= 2:
                    colors(obj[1], location + '/base', depth + 1, ancestors)
                elif kind in ('/CalGray', '/CalRGB', '/Lab') and not isinstance(_object(obj[1]), g.DictionaryObject):
                    entry['uninspected'].append(location + ': parâmetros de cor inválidos')
                entry['color_spaces'].append(item)

            def group(obj, location):
                value = _object(_raw(obj, '/Group'))
                if isinstance(value, g.DictionaryObject) and value.get('/S') == '/Transparency':
                    entry['transparency_groups'].append(dict(location=location, isolated=_boolean(value.get('/I')), knockout=_boolean(value.get('/K'))))
                    if '/CS' in value:
                        colors(_raw(value, '/CS'), location + '/Group/CS')

            def walk(resource_reference, location, depth=0):
                nonlocal visited_budget
                visited_budget += 1
                if depth > 32 or visited_budget > 100000:
                    raise ValueError('Os recursos de impressão excedem o limite seguro de inspeção.')
                identity = _identity(resource_reference)
                if identity in active:
                    entry['uninspected'].append(location + ': ciclo de recursos')
                    return
                if identity in seen:
                    return
                resource = _object(resource_reference)
                if resource is None or isinstance(resource, g.NullObject):
                    return
                if not isinstance(resource, g.DictionaryObject):
                    entry['uninspected'].append(location + ': recursos inválidos')
                    return
                active.add(identity); seen.add(identity)
                for name, color in mapping(resource.get('/ColorSpace', g.DictionaryObject()), location + '/ColorSpace').items():
                    colors(color, location + '/ColorSpace' + str(name))
                for name, font_reference in mapping(resource.get('/Font', g.DictionaryObject()), location + '/Font').items():
                    font = _object(font_reference)
                    if not isinstance(font, g.DictionaryObject):
                        entry['uninspected'].append(location + '/Font' + str(name))
                        continue
                    subtype = str(font.get('/Subtype', ''))
                    candidates = _array(_raw(font, '/DescendantFonts')) if subtype == '/Type0' else [font]
                    glyphs = _object(_raw(font, '/CharProcs'))
                    embedded = subtype == '/Type3' and isinstance(glyphs, g.DictionaryObject) and bool(glyphs) and all(isinstance(_object(glyph), g.StreamObject) for glyph in glyphs.values())
                    if subtype != '/Type3':
                        embedded = bool(candidates)
                        for candidate in candidates:
                            candidate = _object(candidate)
                            if not isinstance(candidate, g.DictionaryObject):
                                entry['uninspected'].append(location + '/Font' + str(name) + ': descendente inválido')
                                embedded = False
                                continue
                            descriptor = _object(_raw(candidate, '/FontDescriptor'))
                            embedded = embedded and isinstance(descriptor, g.DictionaryObject) and any(
                                isinstance(_object(_raw(descriptor, key)), g.StreamObject) for key in ('/FontFile', '/FontFile2', '/FontFile3'))
                    entry['fonts'].append(dict(location=location + '/Font' + str(name), name=str(font.get('/BaseFont', '')), subtype=subtype, embedded=bool(embedded)))
                    if subtype == '/Type3' and '/Resources' in font:
                        walk(_raw(font, '/Resources'), location + '/Font' + str(name), depth + 1)
                for name, state in mapping(resource.get('/ExtGState', g.DictionaryObject()), location + '/ExtGState').items():
                    state = _object(state)
                    if not isinstance(state, g.DictionaryObject):
                        entry['uninspected'].append(location + '/ExtGState' + str(name))
                        continue
                    stroke = _boolean(state.get('/OP')); fill = _boolean(state.get('/op'))
                    # When /op is absent, /OP also sets nonstroking overprint.
                    if fill is None and stroke is not None:
                        fill = stroke
                    item = dict(location=location + '/ExtGState' + str(name), stroke_overprint=stroke,
                                fill_overprint=fill, overprint_mode=_numeric(state.get('/OPM')),
                                stroke_alpha=_numeric(state.get('/CA')), fill_alpha=_numeric(state.get('/ca')),
                                blend_mode=str(state.get('/BM', '/Normal')),
                                soft_mask='/SMask' in state and state.get('/SMask') != '/None')
                    for key in ('/CA', '/ca'):
                        if key in state and (_numeric(state.get(key)) is None or not 0 <= _numeric(state.get(key)) <= 1):
                            entry['uninspected'].append(item['location'] + key + ': opacidade inválida')
                    for key in ('/OP', '/op'):
                        if key in state and _boolean(state.get(key)) is None:
                            entry['uninspected'].append(item['location'] + key + ': sobreimpressão inválida')
                    if '/OPM' in state and _numeric(state.get('/OPM')) not in (0, 1):
                        entry['uninspected'].append(item['location'] + '/OPM: modo inválido')
                    item['transparency'] = any(value is not None and value < 1 for value in (item['stroke_alpha'], item['fill_alpha'])) or item['soft_mask'] or item['blend_mode'] not in ('/Normal', '/Compatible')
                    entry['graphics_states'].append(item)
                for category in ('/XObject', '/Pattern', '/Shading'):
                    for name, value in mapping(resource.get(category, g.DictionaryObject()), location + category).items():
                        obj = _object(value)
                        where = location + category + str(name)
                        if not isinstance(obj, g.DictionaryObject):
                            entry['uninspected'].append(where)
                            continue
                        group(obj, where)
                        if '/ColorSpace' in obj:
                            colors(_raw(obj, '/ColorSpace'), where + '/ColorSpace')
                        if '/SMask' in obj and obj.get('/SMask') != '/None':
                            entry['transparency_groups'].append(dict(location=where + '/SMask'))
                        if '/Resources' in obj:
                            walk(_raw(obj, '/Resources'), where, depth + 1)
                active.remove(identity)

            group(page, 'page')
            walk(resources, 'page')
            for annotation_reference in _array(_raw(page, '/Annots')):
                annotation = _object(annotation_reference)
                appearances = _object(_raw(annotation, '/AP')) if isinstance(annotation, g.DictionaryObject) else None
                if isinstance(appearances, g.DictionaryObject):
                    for state, appearance in appearances.items():
                        appearance = _object(appearance)
                        appearances_for_state = [appearance] if isinstance(appearance, g.StreamObject) else list(appearance.values()) if isinstance(appearance, g.DictionaryObject) else []
                        for number, appearance in enumerate(appearances_for_state):
                            appearance = _object(appearance)
                            if isinstance(appearance, g.StreamObject):
                                group(appearance, f'annotation/{state}/{number}')
                                if '/Resources' in appearance:
                                    walk(_raw(appearance, '/Resources'), f'annotation/{state}/{number}')
            entry['spot_inks'] = sorted(set(entry['spot_inks']))
            if entry['spot_inks']:
                finding('spot-inks-declared', entry['spot_inks'])
            if any(state['stroke_overprint'] or state['fill_overprint'] for state in entry['graphics_states']):
                finding('overprint-declared', 'Há estados de sobreimpressão. Confira a prova com a gráfica.')
            if entry['transparency_groups'] or any(state['transparency'] for state in entry['graphics_states']):
                finding('transparency-declared', 'Há transparência nos recursos da página.')
            if entry['uninspected']:
                finding('uninspected-print-resources', entry['uninspected'])
            pages.append(entry)

        try:
            info = _object(reader.trailer['/Info'])
        except KeyError:
            info = g.DictionaryObject()
        if not isinstance(info, g.DictionaryObject):
            raise ValueError('O dicionário de metadados de impressão é inválido.')
        declared = str(_object(info.get('/GTS_PDFXVersion', '')))
        checks = []
        def check(code, passed, detail):
            checks.append(dict(code=code, status='passed' if passed else 'failed', detail=detail))
        check('pdfx3-declaration', declared == 'PDF/X-3:2002', declared or 'Não declarado')
        version = tuple(reader.input_version)
        catalog_version = str(reader.root.get('/Version', '')).lstrip('/')
        if catalog_version:
            if re.fullmatch(r'[1-9]\.[0-9]', catalog_version):
                version = max(version, tuple(map(int, catalog_version.split('.'))))
            else:
                version = (999, 0)
        check('pdf-version', version <= (1, 3), '.'.join(map(str, version)))
        check('unencrypted', not encrypted, 'PDF/X não permite criptografia.')
        check('title', bool(str(_object(info.get('/Title', ''))).strip()), 'Título do documento.')
        check('trapped', str(info.get('/Trapped', '')) in ('/True', '/False'), 'Estado Trapped explícito.')
        valid_intents = [item for item in output_intents if item['subtype'] == '/GTS_PDFX' and item['condition'] and item['profile'] and 'error' not in item]
        check('output-profile', len(valid_intents) == 1, 'Uma condição de impressão PDF/X com perfil ICC interpretável.')
        check('color-profile-integrity', not any(item['code'] in ('invalid-color-profile', 'invalid-output-profile', 'invalid-output-intents') for item in findings), 'Perfis ICC dos recursos e condições de saída.')
        check('embedded-fonts', all(font['embedded'] for page in pages for font in page['fonts']), 'Fontes declaradas, incluindo formulários e aparências.')
        check('no-transparency-resources', not any(page['transparency_groups'] or any(state['transparency'] for state in page['graphics_states']) for page in pages), 'Inspeção dos recursos; não expande programas de desenho.')
        check('resource-coverage', parser_mode == 'strict' and not any(page['uninspected'] for page in pages), 'Recursos dentro dos limites de inspeção e parser estrito.')
        check('no-open-action', '/OpenAction' not in reader.root and '/AA' not in reader.root, 'Ações de abertura do catálogo.')
        names = _object(reader.root.get('/Names', g.DictionaryObject()))
        check('no-attached-files-or-javascript', '/EmbeddedFiles' not in names and '/JavaScript' not in names and '/AF' not in reader.root,
              'Árvores de anexos e JavaScript do catálogo.')
        return dict(parser='pyHanko', parser_mode=parser_mode, encrypted=encrypted, pages=pages, output_intents=output_intents, findings=findings,
                    pdfx_checks=dict(profile='PDF/X-3:2002', declared=declared, checks=checks,
                                     status='checks_passed' if all(item['status'] == 'passed' for item in checks) else 'checks_failed',
                                     conformant=None, independently_certified=False,
                                     limitations=['Verificações enumeradas, não validação completa ISO 15930.',
                                                  'Recursos declarados podem não ser usados; conteúdo inline, funções e programas de fontes não são interpretados.',
                                                  'Não comprova aparência das chapas, ganho de ponto, registro ou precisão de cor na gráfica.']))


def rendered_ink_coverage(source, options, encrypted):
    """Measure rendered process-ink coverage, never confuse it with TAC max."""
    from pdf_engine import _external, integer
    if encrypted:
        raise ValueError('Para medir tintas com Ghostscript, desbloqueie uma cópia explicitamente. A senha não é enviada pela linha de comando.')
    dpi = integer(options.get('ink_dpi', 72), 'DPI da medição de tintas', 36, 150)
    executable = shutil.which('gs')
    if not executable:
        raise RuntimeError('Ghostscript não está instalado para medir a cobertura de tintas.')
    version = _external([executable, '--version'], timeout=15).stdout.strip()
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
        raise RuntimeError('Não foi possível identificar a versão do medidor de tintas.')
    profile_data = profile = None
    if options.get('icc_profile'):
        profile_data, profile = read_cmyk_profile(options['icc_profile'])
    with tempfile.TemporaryDirectory(prefix='pdf-print-ink-') as temporary:
        folder = Path(temporary)
        target = folder / 'coverage.txt'
        command = [executable, '-dBATCH', '-dNOPAUSE', '-dSAFER', '-dPDFSTOPONERROR', '-sDEVICE=inkcov',
                   '-dSimulateOverprint=true', '-r' + str(dpi), '-sOutputFile=' + str(target)]
        if profile_data is not None:
            path = folder / 'output.icc'; path.write_bytes(profile_data)
            command += ['-sOutputICCProfile=' + str(path), '--permit-file-read=' + str(path)]
        command.append(str(source))
        _external(command, timeout=300)
        if not target.is_file() or target.stat().st_size > 4 * 1024**2:
            raise RuntimeError('Ghostscript não produziu um relatório de tintas de tamanho válido.')
        rows = []
        for line in target.read_text(encoding='ascii').splitlines():
            match = re.fullmatch(r'\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+CMYK\s+OK\s*', line)
            if not match:
                if line.strip():
                    raise RuntimeError('Resposta inesperada do medidor de tintas.')
                continue
            values = [float(value) for value in match.groups()]
            if not all(math.isfinite(value) and 0 <= value <= 1 for value in values):
                raise RuntimeError('Cobertura de tinta fora do intervalo permitido.')
            rows.append(dict(page=len(rows) + 1, cyan=values[0], magenta=values[1], yellow=values[2], black=values[3]))
        return dict(engine='Ghostscript inkcov', engine_version=version, dpi=dpi, profile=profile, pages=rows,
                    color_management='Perfil ICC fornecido' if profile else 'Perfil padrão do Ghostscript',
                    metric='Fração de pixels com alguma tinta em cada canal de processo; não mede carga total máxima de tinta.',
                    limitations=['Tintas especiais são simuladas em CMYK; este relatório não exporta chapas especiais.',
                                 'Cobertura depende da resolução, perfil e simulação; não comprova cor física.'])
