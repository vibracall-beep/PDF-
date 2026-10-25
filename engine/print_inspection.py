"""Bounded, independent structural inspection for print production.

pyHanko reads the original PDF objects, independently of the MuPDF geometry
reader and Ghostscript converter. The checks are deliberately enumerated: this
is not a complete ISO 15930 validator or a colorimetric proof of the press.
Resource declarations are not reported as proof that a mark uses those inks.
"""
from __future__ import annotations

import hashlib
import binascii
import io
import math
from pathlib import Path
import re
import shutil
import tempfile
import zlib

from PIL import ImageCms
from pyhanko.pdf_utils import generic as g
from pyhanko.pdf_utils.reader import PdfFileReader

ICC_MAX_BYTES = 16 * 1024**2
ICC_MAX_ENCODED_BYTES = 40 * 1024**2
ICC_DOCUMENT_DECODE_BYTES = 128 * 1024**2
ICC_MAX_FILTERS = 8
UNSAFE_RESOURCE_FINDINGS = frozenset(('uninspected-output-profile', 'uninspected-color-profile',
    'invalid-output-profile', 'invalid-color-profile', 'invalid-output-intents', 'uninspected-print-resources'))
_PDF_WHITESPACE = b'\x00\t\n\x0c\r '


class ICCNotInspected(ValueError):
    """An explicit inspection limit or unsupported representation was met."""


def _decode_icc_stage(data, name, cap):
    """Every decoder limits output while decoding, not after expansion."""
    if name in ('/FlateDecode', '/Fl'):
        decoder = zlib.decompressobj()
        try:
            result = decoder.decompress(data, cap + 1)
        except zlib.error as exc:
            raise ValueError('O stream Flate do ICC está corrompido.') from exc
        if len(result) > cap or decoder.unconsumed_tail:
            raise ICCNotInspected('A descompressão ICC excede o limite de saída por etapa ou por documento.')
        # Never call unbounded flush(): a complete zlib stream reaches eof
        # during decompress. Truncated and concatenated streams are not ICCs.
        if not decoder.eof or decoder.unused_data.strip(_PDF_WHITESPACE):
            raise ValueError('O stream Flate do ICC está truncado ou contém dados após o final.')
        return result
    if name in ('/ASCIIHexDecode', '/AHx'):
        end = data.find(b'>')
        if end < 0 or data[end + 1:].strip(_PDF_WHITESPACE):
            raise ValueError('O stream ASCIIHex do ICC não tem um final válido.')
        digits = data[:end].translate(None, _PDF_WHITESPACE)
        if (len(digits) + 1) // 2 > cap:
            raise ICCNotInspected('A decodificação ASCIIHex do ICC excede o limite de saída.')
        try:
            return binascii.unhexlify(digits if len(digits) % 2 == 0 else digits + b'0')
        except binascii.Error as exc:
            raise ValueError('O stream ASCIIHex do ICC contém caracteres inválidos.') from exc
    result = bytearray()

    def append(chunk):
        if len(result) + len(chunk) > cap:
            raise ICCNotInspected('A decodificação ICC excede o limite de saída por etapa ou por documento.')
        result.extend(chunk)

    if name in ('/ASCII85Decode', '/A85'):
        end = data.find(b'~>')
        if end < 0 or data[end + 2:].strip(_PDF_WHITESPACE):
            raise ValueError('O stream ASCII85 do ICC não tem um final válido.')
        position = 0
        # The optional Adobe prefix is accepted; PDF normally omits it.
        while position < end and data[position] in _PDF_WHITESPACE:
            position += 1
        if data[position:position + 2] == b'<~':
            position += 2
        group = []
        for value in memoryview(data)[position:end]:
            if value in _PDF_WHITESPACE:
                continue
            if value == ord('z') and not group:
                append(b'\x00' * 4)
                continue
            if not 33 <= value <= 117:
                raise ValueError('O stream ASCII85 do ICC contém um grupo inválido.')
            group.append(value - 33)
            if len(group) == 5:
                integer = sum(value * 85**(4 - index) for index, value in enumerate(group))
                if integer > 0xffffffff:
                    raise ValueError('Um grupo ASCII85 do ICC excede quatro bytes.')
                append(integer.to_bytes(4, 'big')); group = []
        if len(group) == 1:
            raise ValueError('O último grupo ASCII85 do ICC está truncado.')
        if group:
            length = len(group)
            group += [84] * (5 - length)
            integer = sum(value * 85**(4 - index) for index, value in enumerate(group))
            if integer > 0xffffffff:
                raise ValueError('O último grupo ASCII85 do ICC é inválido.')
            append(integer.to_bytes(4, 'big')[:length - 1])
        return bytes(result)
    if name in ('/RunLengthDecode', '/RL'):
        position = 0
        while position < len(data):
            length = data[position]; position += 1
            if length == 128:
                if data[position:].strip(_PDF_WHITESPACE):
                    raise ValueError('Há dados após o final RunLength do ICC.')
                return bytes(result)
            if length < 128:
                count = length + 1
                if position + count > len(data):
                    raise ValueError('O stream RunLength do ICC está truncado.')
                append(data[position:position + count]); position += count
            else:
                if position >= len(data):
                    raise ValueError('O stream RunLength do ICC está truncado.')
                append(bytes((data[position],)) * (257 - length)); position += 1
        raise ValueError('O stream RunLength do ICC não tem marcador de final.')
    # Only the Identity crypt filter is admitted by _bounded_icc_data.
    if name == '/Crypt':
        if len(data) > cap:
            raise ICCNotInspected('O stream ICC excede o limite de saída.')
        return data
    raise ICCNotInspected('Filtro ICC não suportado pela inspeção limitada: ' + name)


def _bounded_icc_data(profile, budget):
    """Read encoded/decrypted bytes without touching StreamObject.data.

    pyHanko already imposes a generic 256 MiB stream cap. The ICC-specific
    16 MiB cap must be applied before that generic decoder allocates output.
    Other PDF streams remain governed by their own parsers and limits.
    """
    filters = _object(_raw(profile, '/Filter'))
    if filters is None or isinstance(filters, g.NullObject):
        filters = []
    elif isinstance(filters, g.NameObject):
        filters = [filters]
    elif isinstance(filters, g.ArrayObject):
        filters = [_object(value) for value in filters]
    else:
        raise ICCNotInspected('A declaração de filtros ICC não é suportada.')
    if len(filters) > ICC_MAX_FILTERS or not all(isinstance(value, g.NameObject) for value in filters):
        raise ICCNotInspected('A cadeia de filtros ICC é inválida ou excede oito etapas.')
    parameters = _object(_raw(profile, '/DecodeParms'))
    if parameters is None or isinstance(parameters, g.NullObject):
        parameters = [None] * len(filters)
    elif isinstance(parameters, g.DictionaryObject) and len(filters) == 1:
        parameters = [parameters]
    elif isinstance(parameters, g.ArrayObject) and len(parameters) == len(filters):
        parameters = [_object(value) for value in parameters]
    else:
        raise ICCNotInspected('Os parâmetros dos filtros ICC não correspondem à cadeia.')
    names = []
    for name, params in zip(filters, parameters):
        name = str(name)
        if params is None or isinstance(params, g.NullObject):
            params = g.DictionaryObject()
        if not isinstance(params, g.DictionaryObject):
            raise ICCNotInspected('Parâmetros de filtro ICC não suportados.')
        if name in ('/FlateDecode', '/Fl'):
            predictor = _numeric(params.get('/Predictor', g.NumberObject(1)))
            if predictor != 1 or any(str(key) not in ('/Predictor', '/Colors', '/Columns', '/BitsPerComponent') for key in params):
                raise ICCNotInspected('A inspeção ICC aceita Flate somente com Predictor 1 e parâmetros conhecidos.')
            for key in ('/Colors', '/Columns', '/BitsPerComponent'):
                if key in params:
                    value = _object(params[key])
                    if not isinstance(value, g.NumberObject) or value < 1:
                        raise ICCNotInspected('Os parâmetros Flate do ICC não são suportados.')
        elif name == '/Crypt':
            if any(str(key) not in ('/Name', '/Type') for key in params) or str(params.get('/Name', '/Identity')) != '/Identity':
                raise ICCNotInspected('Filtro criptográfico ICC explícito não suportado; somente Identity é inspecionado.')
        elif name not in ('/ASCII85Decode', '/A85', '/ASCIIHexDecode', '/AHx', '/RunLengthDecode', '/RL') or params:
            raise ICCNotInspected('Filtro ou parâmetros ICC não suportados: ' + name)
        names.append(name)
    data = profile.encoded_data
    if len(data) > ICC_MAX_ENCODED_BYTES:
        raise ICCNotInspected('O stream ICC codificado excede 40 MiB.')
    if not names:
        if len(data) > min(ICC_MAX_BYTES, budget[0]):
            raise ICCNotInspected('O perfil ICC excede o limite de 16 MiB ou o orçamento do documento.')
        budget[0] -= len(data)
    for name in names:
        cap = min(ICC_MAX_BYTES, budget[0])
        if cap <= 0:
            raise ICCNotInspected('O orçamento de decodificação ICC do documento foi esgotado.')
        # Reserve before decoding so failed, distinct expansive streams also
        # consume the document budget. Successful small stages return slack.
        budget[0] -= cap
        data = _decode_icc_stage(data, name, cap)
        budget[0] += cap - len(data)
    return data


def icc_description(data):
    """Check the ICC container and let LittleCMS parse the actual profile."""
    if not 132 <= len(data) <= ICC_MAX_BYTES:
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
        icc_decode_budget = [ICC_DOCUMENT_DECODE_BYTES]
        visited_budget = 0

        def profile_info(value):
            profile = _object(value)
            if not isinstance(profile, g.StreamObject):
                raise ValueError('O perfil ICC incorporado não é um stream.')
            # ArrayObject.__getitem__ may already dereference the same ICC
            # that OutputIntents supplied as an IndirectObject. Use the stream
            # container reference so both routes share the decoding cache.
            reference = profile.container_ref
            identity = ('ref', reference.idnum, reference.generation) if isinstance(reference, g.Reference) else _identity(value)
            if identity not in profile_cache:
                try:
                    profile_cache[identity] = icc_description(_bounded_icc_data(profile, icc_decode_budget))
                except (ValueError, OSError, TypeError) as exc:
                    # Reused malformed resources must not repeatedly decode;
                    # cache text/type, never the traceback and its large bytes.
                    profile_cache[identity] = (type(exc), str(exc))
            result = profile_cache[identity]
            if isinstance(result, tuple):
                raise result[0](result[1])
            return result

        intents = _object(_raw(reader.root, '/OutputIntents'))
        if intents is not None and not isinstance(intents, (g.ArrayObject, g.NullObject)):
            findings.append(dict(page=None, code='invalid-output-intents', detail='OutputIntents não é uma lista.'))
        for index, reference in enumerate(_array(intents)):
            visited_budget += 1
            if visited_budget > 100000:
                raise ValueError('Os recursos de impressão excedem o limite seguro de inspeção.')
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
                    if isinstance(exc, ICCNotInspected):
                        item['inspection_status'] = 'not_inspected'
            output_intents.append(item)
            if 'error' in item:
                findings.append(dict(page=None, code='uninspected-output-profile' if item.get('inspection_status') == 'not_inspected' else 'invalid-output-profile', detail=item))
        if not output_intents:
            findings.append(dict(page=None, code='missing-output-intent', detail='Nenhuma condição de impressão incorporada.'))

        for index in range(count):
            reference, resources = reader.find_page_for_modification(index)
            page = reference.get_object()
            entry = dict(page=index + 1, color_spaces=[], spot_inks=[], graphics_states=[],
                         transparency_groups=[], fonts=[], uninspected=[])
            seen, active = set(), set()
            drawing_seen, drawing_active = set(), set()

            def consume(depth=0):
                nonlocal visited_budget
                visited_budget += 1
                if depth > 32 or visited_budget > 100000:
                    raise ValueError('Os recursos de impressão excedem o limite seguro de inspeção.')

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
                consume(depth)
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
                        if isinstance(exc, ICCNotInspected):
                            item['inspection_status'] = 'not_inspected'
                            entry['uninspected'].append(location + ': ' + str(exc))
                            finding('uninspected-color-profile', item)
                        else:
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
                    if kind == '/DeviceN' and len(obj) == 5:
                        attributes = mapping(obj[4], location + '/attributes')
                        for name, separation in mapping(_raw(attributes, '/Colorants'), location + '/Colorants').items():
                            colors(separation, location + '/Colorants' + str(name), depth + 1, ancestors)
                        process = mapping(_raw(attributes, '/Process'), location + '/Process')
                        if '/ColorSpace' in process:
                            colors(_raw(process, '/ColorSpace'), location + '/Process/ColorSpace', depth + 1, ancestors)
                        if any(str(key) not in ('/Subtype', '/Colorants', '/Process', '/MixingHints') for key in attributes):
                            entry['uninspected'].append(location + ': atributos DeviceN desconhecidos')
                elif kind in ('/Indexed', '/Pattern') and len(obj) >= 2:
                    colors(obj[1], location + '/base', depth + 1, ancestors)
                elif kind in ('/CalGray', '/CalRGB', '/Lab') and not isinstance(_object(obj[1]), g.DictionaryObject):
                    entry['uninspected'].append(location + ': parâmetros de cor inválidos')
                entry['color_spaces'].append(item)

            def group(obj, location):
                value = _object(_raw(obj, '/Group'))
                if value is None or isinstance(value, g.NullObject):
                    return
                if not isinstance(value, g.DictionaryObject) or value.get('/S') != '/Transparency':
                    entry['uninspected'].append(location + ': grupo de transparência inválido ou desconhecido')
                    return
                entry['transparency_groups'].append(dict(location=location, isolated=_boolean(value.get('/I')), knockout=_boolean(value.get('/K'))))
                if '/CS' in value:
                    colors(_raw(value, '/CS'), location + '/Group/CS')

            def inspect_state(reference, location, depth):
                consume(depth)
                state = _object(reference)
                if not isinstance(state, g.DictionaryObject):
                    entry['uninspected'].append(location + ': estado gráfico inválido')
                    return
                stroke = _boolean(state.get('/OP')); fill = _boolean(state.get('/op'))
                if fill is None and stroke is not None:
                    fill = stroke
                item = dict(location=location, stroke_overprint=stroke, fill_overprint=fill,
                            overprint_mode=_numeric(state.get('/OPM')), stroke_alpha=_numeric(state.get('/CA')),
                            fill_alpha=_numeric(state.get('/ca')), blend_mode=str(state.get('/BM', '/Normal')),
                            soft_mask='/SMask' in state and state.get('/SMask') != '/None')
                for key in ('/CA', '/ca'):
                    if key in state and (_numeric(state.get(key)) is None or not 0 <= _numeric(state.get(key)) <= 1):
                        entry['uninspected'].append(location + key + ': opacidade inválida')
                for key in ('/OP', '/op'):
                    if key in state and _boolean(state.get(key)) is None:
                        entry['uninspected'].append(location + key + ': sobreimpressão inválida')
                if '/OPM' in state and _numeric(state.get('/OPM')) not in (0, 1):
                    entry['uninspected'].append(location + '/OPM: modo inválido')
                item['transparency'] = any(value is not None and value < 1 for value in (item['stroke_alpha'], item['fill_alpha'])) or item['soft_mask'] or item['blend_mode'] not in ('/Normal', '/Compatible')
                entry['graphics_states'].append(item)
                mask = _object(_raw(state, '/SMask'))
                if mask is not None and not isinstance(mask, g.NullObject) and mask != '/None':
                    if not isinstance(mask, g.DictionaryObject) or mask.get('/S') not in ('/Alpha', '/Luminosity') or '/G' not in mask:
                        entry['uninspected'].append(location + '/SMask: máscara gráfica inválida')
                    else:
                        drawing(_raw(mask, '/G'), location + '/SMask/G', depth + 1, 'form')

            def drawing(reference, location, depth=0, expected=None):
                consume(depth)
                obj = _object(reference)
                identity = _identity(reference)
                container = getattr(obj, 'container_ref', None)
                # A direct dictionary's container_ref names its enclosing
                # object, not its own identity. Only streams must be indirect.
                if isinstance(obj, g.StreamObject) and isinstance(container, g.Reference):
                    identity = ('ref', container.idnum, container.generation)
                if identity in drawing_active:
                    entry['uninspected'].append(location + ': ciclo de objetos de desenho')
                    return
                if identity in drawing_seen:
                    return
                if not isinstance(obj, g.DictionaryObject):
                    entry['uninspected'].append(location + ': objeto de desenho inválido')
                    return
                subtype = str(obj.get('/Subtype', ''))
                if expected in ('form', 'image') and (not isinstance(obj, g.StreamObject) or subtype != {'form': '/Form', 'image': '/Image'}[expected]):
                    entry['uninspected'].append(location + ': tipo de imagem/formulário inválido')
                    return
                if expected == 'xobject' and (not isinstance(obj, g.StreamObject) or subtype not in ('/Form', '/Image')):
                    entry['uninspected'].append(location + ': XObject não suportado')
                    return
                if expected == 'pattern' and _numeric(obj.get('/PatternType')) not in (1, 2):
                    entry['uninspected'].append(location + ': padrão de desenho não suportado')
                    return
                drawing_active.add(identity); drawing_seen.add(identity)
                group(obj, location)
                if '/ColorSpace' in obj:
                    colors(_raw(obj, '/ColorSpace'), location + '/ColorSpace')
                elif expected == 'shading':
                    entry['uninspected'].append(location + ': sombreado sem espaço de cor')
                if '/Resources' in obj:
                    walk(_raw(obj, '/Resources'), location, depth + 1)
                if '/Shading' in obj:
                    drawing(_raw(obj, '/Shading'), location + '/Shading', depth + 1, 'shading')
                if '/ExtGState' in obj:
                    inspect_state(_raw(obj, '/ExtGState'), location + '/ExtGState', depth + 1)
                for key in ('/SMask', '/Mask'):
                    mask = _object(_raw(obj, key))
                    if mask is None or isinstance(mask, g.NullObject) or mask == '/None':
                        continue
                    if key == '/Mask' and isinstance(mask, g.ArrayObject):
                        if len(mask) not in (2, 4, 6) or any(_numeric(value) is None for value in mask):
                            entry['uninspected'].append(location + key + ': máscara por cores inválida')
                        continue
                    entry['transparency_groups'].append(dict(location=location + key))
                    drawing(_raw(obj, key), location + key, depth + 1, 'image')
                alternates = _object(_raw(obj, '/Alternates'))
                if alternates is not None and not isinstance(alternates, g.NullObject):
                    if not isinstance(alternates, g.ArrayObject):
                        entry['uninspected'].append(location + '/Alternates: imagens alternativas inválidas')
                    else:
                        for number, alternative in enumerate(alternates):
                            consume(depth + 1)
                            alternative = _object(alternative)
                            if not isinstance(alternative, g.DictionaryObject) or '/Image' not in alternative:
                                entry['uninspected'].append(location + '/Alternates: imagem alternativa ausente')
                            else:
                                drawing(_raw(alternative, '/Image'), location + f'/Alternates/{number}', depth + 1, 'image')
                drawing_active.remove(identity)

            def walk(resource_reference, location, depth=0):
                consume(depth)
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
                    consume(depth + 1)
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
                            consume(depth + 1)
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
                    inspect_state(state, location + '/ExtGState' + str(name), depth + 1)
                for category, expected in (('/XObject', 'xobject'), ('/Pattern', 'pattern'), ('/Shading', 'shading')):
                    for name, value in mapping(resource.get(category, g.DictionaryObject()), location + category).items():
                        drawing(value, location + category + str(name), depth + 1, expected)
                active.remove(identity)

            group(page, 'page')
            walk(resources, 'page')
            acroform = _object(_raw(reader.root, '/AcroForm'))
            if acroform is not None and not isinstance(acroform, g.NullObject):
                if not isinstance(acroform, g.DictionaryObject):
                    entry['uninspected'].append('AcroForm: dicionário inválido')
                elif '/DR' in acroform:
                    walk(_raw(acroform, '/DR'), 'AcroForm/DR')
            annotations = _object(_raw(page, '/Annots'))
            if annotations is not None and not isinstance(annotations, (g.ArrayObject, g.NullObject)):
                entry['uninspected'].append('Annots: lista inválida')
            for annotation_reference in _array(annotations):
                consume()
                annotation = _object(annotation_reference)
                if not isinstance(annotation, g.DictionaryObject):
                    entry['uninspected'].append('Annots: anotação inválida')
                    continue
                appearances = _object(_raw(annotation, '/AP'))
                if appearances is None or isinstance(appearances, g.NullObject):
                    continue
                if not isinstance(appearances, g.DictionaryObject):
                    entry['uninspected'].append('AP: dicionário de aparências inválido')
                    continue
                for state, appearance in appearances.items():
                    appearance = _object(appearance)
                    if isinstance(appearance, g.StreamObject):
                        drawing(appearance, f'annotation/{state}', expected='form')
                    elif isinstance(appearance, g.DictionaryObject):
                        for name, stream in appearance.items():
                            drawing(stream, f'annotation/{state}/{name}', expected='form')
                    else:
                        entry['uninspected'].append(f'annotation/{state}: aparência inválida')
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
        check('color-profile-integrity', not any(item['code'] in ('invalid-color-profile', 'invalid-output-profile', 'invalid-output-intents', 'uninspected-color-profile', 'uninspected-output-profile') for item in findings), 'Perfis ICC dos recursos e condições de saída.')
        check('embedded-fonts', all(font['embedded'] for page in pages for font in page['fonts']), 'Fontes declaradas, incluindo formulários e aparências.')
        check('no-transparency-resources', not any(page['transparency_groups'] or any(state['transparency'] for state in page['graphics_states']) for page in pages), 'Inspeção dos recursos; não expande programas de desenho.')
        check('resource-coverage', parser_mode == 'strict' and not any(page['uninspected'] for page in pages) and not any(item['code'] == 'uninspected-output-profile' for item in findings), 'Recursos dentro dos limites de inspeção e parser estrito.')
        check('no-open-action', '/OpenAction' not in reader.root and '/AA' not in reader.root, 'Ações de abertura do catálogo.')
        names = _object(reader.root.get('/Names', g.DictionaryObject()))
        check('no-attached-files-or-javascript', '/EmbeddedFiles' not in names and '/JavaScript' not in names and '/AF' not in reader.root,
              'Árvores de anexos e JavaScript do catálogo.')
        return dict(parser='pyHanko', parser_mode=parser_mode, encrypted=encrypted, pages=pages, output_intents=output_intents, findings=findings,
                    icc_limits=dict(decoded_bytes_per_stage=ICC_MAX_BYTES, encoded_bytes=ICC_MAX_ENCODED_BYTES,
                                    filter_stages=ICC_MAX_FILTERS, document_decoded_bytes=ICC_DOCUMENT_DECODE_BYTES,
                                    document_budget_used=ICC_DOCUMENT_DECODE_BYTES - icc_decode_budget[0]),
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
