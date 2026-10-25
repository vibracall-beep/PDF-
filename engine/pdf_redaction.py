"""Sanitisation of the derived redacted PDF, before no-clobber publication.

The original is never modified. Surviving annotations and fields become their
visible appearances; private semantic trees, attachments and active content are
discarded from the copy. Optional-content and XFA documents are refused because
flattening their hidden states has not been established by this implementation.
"""
from __future__ import annotations

import io
import hashlib
import math
import re

import fitz
import pymupdf
from pyhanko.pdf_utils import generic as g
from pyhanko.pdf_utils.misc import PdfError
from PIL import Image, ImageDraw


PRIVATE_KEYS = {
    '/ActualText', '/Alt', '/StructTreeRoot', '/MarkInfo', '/StructParent', '/StructParents',
    '/Metadata', '/PieceInfo', '/AF', '/SpiderInfo', '/Properties', '/Thumb',
    '/AA', '/OpenAction', '/JS', '/JavaScript', '/LastModified',
}
CATALOG_PRIVATE_KEYS = {'/Names', '/Dests', '/Outlines', '/PageLabels', '/Collection', '/DSS', '/Perms', '/Legal'}
OUTPUT_INTENT_PRIVATE_KEYS = {'/Info', '/OutputCondition', '/OutputConditionIdentifier', '/RegistryName'}
DISCARDED_TYPES = {'/Filespec', '/EmbeddedFile', '/Metadata', '/StructElem', '/StructTreeRoot'}
MULTIMEDIA_ANNOTATIONS = {'/FileAttachment', '/Sound', '/Movie', '/Screen', '/RichMedia', '/3D'}
MARKED_OPERATORS = {'BMC': 1, 'BDC': 2, 'MP': 1, 'DP': 2, 'EMC': 0}
CONTENT_OPERATORS = set('q Q cm w J j M d ri i gs m l c v y h re S s f F f* B B* b b* n W W* BT ET Tc Tw Tz TL Tf Tr Ts Td TD Tm T* Tj TJ CS cs SC SCN sc scn G g RG rg K k sh Do d0 d1 BX EX'.split()) | {"'", '"'}
WHITESPACE = b'\x00\t\n\x0c\r '
RESOURCE_MAP_KEYS = {'/Font', '/XObject', '/ExtGState', '/ColorSpace', '/Pattern', '/Shading', '/CharProcs'}


class _SyntaxHandler:
    strict = True
    def get_object(self, reference, *args, **kwargs):
        raise ValueError('Uma referência indireta foi usada como valor direto na inspeção de ocultação.')


_SYNTAX_REFERENCE = g.Reference(1, 0, _SyntaxHandler())


def _skip_space(stream):
    while True:
        position = stream.tell(); value = stream.read(1)
        if not value:
            return
        if value in WHITESPACE:
            continue
        if value == b'%':
            stream.readline(); continue
        stream.seek(position); return


def _parse_object(stream, depth=0):
    if depth > 64:
        raise ValueError('O objeto PDF excede o limite de profundidade.')
    _skip_space(stream); position = stream.tell(); prefix = stream.read(2); stream.seek(position)
    if prefix == b'<<':
        stream.read(2); result = g.DictionaryObject()
        while True:
            _skip_space(stream); position = stream.tell()
            if stream.read(2) == b'>>':
                return result
            stream.seek(position)
            key = _parse_object(stream, depth + 1)
            if not isinstance(key, g.NameObject) or key in result:
                raise ValueError('O dicionário PDF contém chave inválida ou duplicada.')
            result[key] = _parse_object(stream, depth + 1)
    if prefix[:1] == b'[':
        stream.read(1); result = g.ArrayObject()
        while True:
            _skip_space(stream); position = stream.tell()
            if stream.read(1) == b']':
                return result
            stream.seek(position); result.append(_parse_object(stream, depth + 1))
    if prefix[:1] == b'/':
        raw = bytearray(stream.read(1))
        while (value := stream.read(1)) and value not in WHITESPACE + b'()<>[]{}/%':
            raw.extend(value)
        if value:
            stream.seek(-1, io.SEEK_CUR)
        decoded = bytearray(); index = 1
        while index < len(raw):
            if raw[index] == ord('#'):
                if index + 2 >= len(raw) or re.fullmatch(rb'[0-9A-Fa-f]{2}', raw[index + 1:index + 3]) is None:
                    raise ValueError('O nome PDF contém escape inválido.')
                decoded.append(int(raw[index + 1:index + 3], 16)); index += 3
            else:
                decoded.append(raw[index]); index += 1
        # PDF names are byte sequences, not necessarily UTF-8. Latin-1 is a
        # reversible identity here; preserve the actual original token too.
        result = g.NameObject('/' + decoded.decode('latin1'))
        result._redaction_name_token = bytes(raw)
        return result
    return g.read_object(stream, container_ref=_SYNTAX_REFERENCE)


def _object(doc, xref):
    raw = doc.xref_object(xref, compressed=False)
    if not raw:
        return g.NullObject()
    try:
        return _parse_object(io.BytesIO(raw.encode('utf-8')))
    except Exception as exc:
        raise ValueError('Um objeto PDF não pôde ser inspecionado para ocultação segura. Nenhuma cópia foi publicada.') from exc


def _serialize(obj):
    # Hex strings preserve the original PDF bytes, including UTF-16, rather
    # than round-tripping literal strings through Python/UTF-8 and changing
    # glyph codes, field values or names.
    if isinstance(obj, g.TextStringObject):
        return b'<' + obj.original_bytes.hex().encode('ascii') + b'>'
    if isinstance(obj, g.ByteStringObject):
        return b'<' + bytes(obj).hex().encode('ascii') + b'>'
    if isinstance(obj, g.NameObject):
        if hasattr(obj, '_redaction_name_token'):
            return obj._redaction_name_token
        result = bytearray(b'/')
        for value in str(obj)[1:].encode('utf-8'):
            if 33 <= value <= 126 and value not in b'#()<>[]{}/%':
                result.append(value)
            else:
                result.extend(f'#{value:02X}'.encode('ascii'))
        return bytes(result)
    if isinstance(obj, g.DictionaryObject):
        return b'<<' + b' '.join(_serialize(key) + b' ' + _serialize(value) for key, value in obj.items()) + b'>>'
    if isinstance(obj, g.ArrayObject):
        return b'[' + b' '.join(_serialize(value) for value in obj) + b']'
    result = io.BytesIO(); obj.write_to_stream(result)
    return result.getvalue()


def _walk_dicts(obj, action, depth=0):
    if depth > 64:
        raise ValueError('A estrutura do PDF é profunda demais para sanear com segurança.')
    if isinstance(obj, g.DictionaryObject):
        action(obj)
        for value in list(obj.values()):
            _walk_dicts(value, action, depth + 1)
    elif isinstance(obj, g.ArrayObject):
        for value in obj:
            _walk_dicts(value, action, depth + 1)


def _resource_map_references(doc):
    result = set()
    def collect(dictionary):
        for key, value in dictionary.items():
            if str(key) in RESOURCE_MAP_KEYS and isinstance(value, g.IndirectObject):
                result.add(value.idnum)
    for xref in range(1, doc.xref_length()):
        _walk_dicts(_object(doc, xref), collect)
    return result


def _output_intent_references(doc):
    catalog = _object(doc, doc.pdf_catalog()); references = set()
    def collect(obj, depth=0):
        if depth > 64:
            raise ValueError('As referências de saída de cor excedem o limite de inspeção.')
        if isinstance(obj, g.IndirectObject):
            if obj.idnum in references:
                return
            references.add(obj.idnum); collect(_object(doc, obj.idnum), depth + 1)
        elif isinstance(obj, g.ArrayObject):
            for value in obj:
                collect(value, depth + 1)
    if '/OutputIntents' in catalog:
        collect(catalog.raw_get('/OutputIntents'))
    return references


def _walk_metadata_dicts(obj, action, protected=False, depth=0, output_intent=False):
    if depth > 64:
        raise ValueError('A estrutura do PDF é profunda demais para sanear com segurança.')
    if isinstance(obj, g.DictionaryObject):
        if not protected:
            action(obj, output_intent)
        for key, value in list(obj.items()):
            _walk_metadata_dicts(value, action, str(key) in RESOURCE_MAP_KEYS, depth + 1, str(key) == '/OutputIntents')
    elif isinstance(obj, g.ArrayObject):
        for value in obj:
            _walk_metadata_dicts(value, action, False, depth + 1, output_intent)


def _resolve(doc, value):
    seen = set()
    while isinstance(value, g.IndirectObject):
        if value.idnum in seen or len(seen) >= 64:
            raise ValueError('Há referências cíclicas em parâmetros de ocultação.')
        seen.add(value.idnum); value = _object(doc, value.idnum)
    return value


def _check_supported(doc):
    if doc.xref_length() > 500000:
        raise ValueError('A ocultação aceita até 500.000 objetos PDF por documento.')
    for page in doc:
        if any(annotation.type[0] == fitz.PDF_ANNOT_REDACT for annotation in page.annots() or []):
            raise ValueError('Há marcações de redação pendentes. Resolva-as antes de criar a cópia sanitizada.')
        traces = page.get_texttrace()
        if page.get_xobjects() and any(trace.get('type') == 3 for trace in traces):
            # The native normaliser does not preserve every inherited text
            # state at Form boundaries. Inspect the ORIGINAL renderer trace,
            # including occluded/clipped text, before any rewrite or bake.
            raise ValueError('A página combina objetos Form e texto invisível com estado herdado. Prepare uma cópia estática revisada antes de ocultar conteúdo.')
        if any(trace.get('chars') and (trace.get('size', 0) <= 0 or
                fitz.Rect(trace['bbox']).width <= 0 or fitz.Rect(trace['bbox']).height <= 0) for trace in traces):
            raise ValueError('A página contém texto com transformação ou dimensão degenerada. Prepare uma cópia estática revisada antes de ocultar conteúdo.')
    def check(dictionary):
        if _resolve(doc, dictionary.get('/Type')) in ('/OCG', '/OCMD') or any(key in dictionary for key in ('/OCProperties', '/OC', '/XFA')):
            raise ValueError('Este PDF usa camadas opcionais ou formulários XFA. A ocultação não pode garantir a remoção dos estados ocultos; prepare e revise uma cópia estática antes de continuar.')
        if _resolve(doc, dictionary.get('/Subtype')) == '/PS':
            raise ValueError('Objetos PostScript não podem ser saneados por esta ferramenta. Prepare e revise uma cópia estática.')
        if any(_resolve(doc, dictionary.get(key)) == 0 for key in ('/ca', '/CA')) or ('/SMask' in dictionary and _resolve(doc, dictionary.get('/SMask')) != '/None'):
            raise ValueError('Este PDF contém transparência invisível ou máscaras. Prepare e revise uma cópia estática antes de ocultar conteúdo.')
    maps = _resource_map_references(doc)
    def names(obj, is_map=False):
        if isinstance(obj, g.DictionaryObject):
            if is_map and any('/' in str(key)[1:] or '#' in str(key)[1:] for key in obj):
                raise ValueError('Este PDF usa nomes de recursos que o normalizador não preserva com segurança. Prepare uma cópia estática antes de ocultar conteúdo.')
            for key, value in obj.items():
                names(value, str(key) in RESOURCE_MAP_KEYS)
        elif isinstance(obj, g.ArrayObject):
            for value in obj:
                names(value)
    for xref in range(1, doc.xref_length()):
        obj = _object(doc, xref)
        _walk_dicts(obj, check); names(obj, xref in maps)


def _image_privacy(doc, verify=False):
    from pdf_image_privacy import strip_jpeg_metadata
    from print_inspection import _decode_icc_stage
    for xref in range(1, doc.xref_length()):
        obj = _object(doc, xref)
        if not isinstance(obj, g.DictionaryObject) or _resolve(doc, obj.get('/Subtype')) != '/Image':
            continue
        filters = _resolve(doc, obj.get('/Filter'))
        filters = list(filters) if isinstance(filters, g.ArrayObject) else [] if filters is None or isinstance(filters, g.NullObject) else [filters]
        filters = [str(_resolve(doc, value)) for value in filters]
        if any(value in ('/JPXDecode', '/JBIG2Decode') for value in filters):
            raise ValueError('Imagens JPEG2000/JBIG2 exigem uma cópia estática revisada; os metadados desses contêineres não são saneados por esta ferramenta.')
        if '/DCTDecode' not in filters and '/DCT' not in filters:
            continue
        if filters[-1] not in ('/DCTDecode', '/DCT') or len(filters) > 8:
            raise ValueError('A cadeia de filtros JPEG não pode ser saneada com segurança.')
        parameters = _resolve(doc, obj.get('/DecodeParms'))
        if isinstance(parameters, g.ArrayObject):
            if len(parameters) != len(filters):
                raise ValueError('Os parâmetros dos filtros JPEG são ambíguos.')
            parameters = [_resolve(doc, value) for value in parameters]
        elif parameters is None or isinstance(parameters, g.NullObject):
            parameters = [None] * len(filters)
        elif len(filters) == 1 and isinstance(parameters, g.DictionaryObject):
            parameters = [parameters]
        else:
            raise ValueError('Os parâmetros de imagem JPEG não são suportados.')
        data = doc.xref_stream_raw(xref)
        if len(data) > 128 * 1024**2:
            raise ValueError('A imagem JPEG excede o limite de inspeção.')
        for name, params in zip(filters[:-1], parameters[:-1]):
            if params is not None and not isinstance(params, g.NullObject) and (not isinstance(params, g.DictionaryObject) or
                    any(str(key) != '/Predictor' or value != 1 for key, value in params.items())):
                raise ValueError('A imagem JPEG possui parâmetros de decodificação não suportados.')
            if name not in ('/FlateDecode', '/Fl', '/ASCII85Decode', '/A85', '/ASCIIHexDecode', '/AHx', '/RunLengthDecode', '/RL'):
                raise ValueError('A imagem JPEG possui filtro anterior ao DCT não suportado.')
            data = _decode_icc_stage(data, name, 128 * 1024**2)
        cleaned = strip_jpeg_metadata(data)
        if cleaned != data or len(filters) != 1:
            if verify:
                raise ValueError('A cópia ainda contém metadados de imagem não saneados; nenhuma saída foi publicada.')
            doc.update_stream(xref, cleaned, compress=False)
            doc.xref_set_key(xref, 'Filter', '/DCTDecode')
            doc.xref_set_key(xref, 'DecodeParms', _serialize(parameters[-1]).decode('ascii') if parameters[-1] is not None else 'null')


def _icc_privacy_plan(doc):
    """Inspect declared ICC streams before rendering, without generic decoding.

    Looking at every indirect object also covers color spaces in Form groups,
    soft masks, patterns, shadings and inherited resources. Only declared ICC
    references are profiles; arbitrary streams are not guessed to be ICC.
    """
    from pdf_icc_privacy import sanitize_icc
    from print_inspection import _bounded_icc_data, ICC_DOCUMENT_DECODE_BYTES
    profiles = set()

    def profile_reference(value):
        seen = set()
        while isinstance(value, g.IndirectObject):
            xref = value.idnum
            if xref in seen or len(seen) >= 64:
                raise ValueError('O perfil ICC possui referências cíclicas.')
            seen.add(xref)
            if doc.xref_is_stream(xref):
                profiles.add(xref)
                return
            value = _object(doc, xref)
        raise ValueError('O perfil ICC declarado não é um stream indireto válido.')

    def collect(obj, depth=0):
        if depth > 64:
            raise ValueError('A estrutura de perfis ICC excede o limite de inspeção.')
        if isinstance(obj, g.ArrayObject):
            if obj and _resolve(doc, obj.raw_get(0)) == '/ICCBased':
                if len(obj) != 2:
                    raise ValueError('A declaração ICCBased está malformada.')
                profile_reference(obj.raw_get(1))
            for value in obj:
                collect(value, depth + 1)
        elif isinstance(obj, g.DictionaryObject):
            if '/DestOutputProfile' in obj:
                profile_reference(obj.raw_get('/DestOutputProfile'))
            if '/DestOutputProfileRef' in obj:
                raise ValueError('Perfis ICC externos exigem uma cópia estática revisada antes da ocultação.')
            for value in obj.values():
                collect(value, depth + 1)

    def resolved_parameters(obj, depth=0):
        if depth > 64:
            raise ValueError('Os parâmetros do perfil ICC são profundos demais.')
        obj = _resolve(doc, obj)
        if isinstance(obj, g.ArrayObject):
            return g.ArrayObject([resolved_parameters(value, depth + 1) for value in obj])
        if isinstance(obj, g.DictionaryObject):
            return g.DictionaryObject({key: resolved_parameters(value, depth + 1) for key, value in obj.items()})
        return obj

    if doc.xref_length() > 500000:
        raise ValueError('A ocultação aceita até 500.000 objetos PDF por documento.')
    for xref in range(1, doc.xref_length()):
        collect(_object(doc, xref))
    budget = [ICC_DOCUMENT_DECODE_BYTES]; updates = {}
    for xref in sorted(profiles):
        obj = _object(doc, xref)
        if not isinstance(obj, g.DictionaryObject):
            raise ValueError('O perfil ICC possui dicionário inválido.')
        parameters = {g.pdf_name(key): resolved_parameters(obj.raw_get(key))
                      for key in ('/Filter', '/DecodeParms') if key in obj}
        stream = g.StreamObject(parameters, encoded_data=doc.xref_stream_raw(xref))
        try:
            original = _bounded_icc_data(stream, budget)
            cleaned = sanitize_icc(original)
        except Exception as exc:
            raise ValueError('Um perfil ICC não pôde ser saneado sem alterar a cor. Nenhuma cópia foi publicada; prepare uma cópia estática revisada.') from exc
        expected = {b'GRAY': 1, b'RGB ': 3, b'CMYK': 4}.get(original[16:20])
        if '/N' in obj and _resolve(doc, obj.raw_get('/N')) != expected:
            raise ValueError('O número de componentes do perfil ICC não corresponde à cor declarada.')
        if cleaned != original:
            updates[xref] = cleaned
    return updates


def _page_appearance(page, excluded):
    if page.rect.width * page.rect.height > 25000000:
        raise ValueError('A página excede o limite da verificação visual de ocultação.')
    pixmap = page.get_pixmap(alpha=False, annots=True)
    canvas = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
    draw = ImageDraw.Draw(canvas)
    for bounds in excluded:
        bounds = (fitz.Rect(bounds) + (-2, -2, 2, 2)) * page.rotation_matrix
        draw.rectangle((math.floor(bounds.x0 - pixmap.x), math.floor(bounds.y0 - pixmap.y),
                        math.ceil(bounds.x1 - pixmap.x), math.ceil(bounds.y1 - pixmap.y)), fill='white')
    return (canvas.size, hashlib.sha256(canvas.tobytes()).hexdigest())


def _appearance(doc, excluded):
    return [_page_appearance(page, excluded.get(index, [])) for index, page in enumerate(doc)]


def _sanitize_objects(doc, final=False):
    catalog = doc.pdf_catalog()
    resource_maps = _resource_map_references(doc)
    output_intents = _output_intent_references(doc)
    for xref in range(1, doc.xref_length()):
        obj = _object(doc, xref)
        if not isinstance(obj, (g.DictionaryObject, g.ArrayObject)):
            continue
        if isinstance(obj, g.DictionaryObject) and (obj.get('/Type') in DISCARDED_TYPES or
                                                   (final and obj.get('/Type') == '/Annot') or
                                                   obj.get('/S') in ('/JavaScript', '/Launch', '/SubmitForm', '/ImportData', '/GoToE')):
            if doc.xref_is_stream(xref):
                doc.update_stream(xref, b'')
            doc.update_object(xref, '<<>>')
            continue
        changed = False
        def remove(dictionary, output_intent=False):
            nonlocal changed
            keys = PRIVATE_KEYS | (CATALOG_PRIVATE_KEYS if xref == catalog else set())
            if output_intent or dictionary.get('/Type') == '/OutputIntent':
                keys |= OUTPUT_INTENT_PRIVATE_KEYS
            if final:
                keys |= {'/AcroForm', '/Annots'}
            for key in list(dictionary):
                if str(key) in keys:
                    del dictionary[key]; changed = True
        _walk_metadata_dicts(obj, remove, xref in resource_maps, output_intent=xref in output_intents)
        if changed:
            doc.update_object(xref, _serialize(obj).decode('ascii'))
    # Delete the entire Info dictionary, including application-specific keys
    # that set_metadata({}) alone does not necessarily enumerate.
    doc.xref_set_key(-1, 'Info', 'null')


def _next_token(stream):
    while True:
        position = stream.tell(); byte = stream.read(1)
        if not byte:
            return None
        if byte in WHITESPACE:
            continue
        if byte == b'%':
            stream.readline()
            continue
        stream.seek(position)
        stream.token_start = position
        if byte in (b"'", b'"'):
            stream.read(1)
            return g.OperatorLiteral(byte.decode('ascii'))
        if byte.isalpha():
            word = bytearray()
            while (value := stream.read(1)) and value not in WHITESPACE + b'()<>[]{}/%':
                word.extend(value)
            if value:
                stream.seek(-1, io.SEEK_CUR)
            if word in (b'true', b'false'):
                return g.BooleanObject(word == b'true')
            if word == b'null':
                return g.NullObject()
            return g.OperatorLiteral(word.decode('ascii'))
        return g.read_object(stream, container_ref=_SYNTAX_REFERENCE, in_content_stream=g.ContentOpReading.GRAPHIC_OPS)


def _inline_image(stream):
    parameters = []
    values = {}
    for _ in range(100):
        key = _next_token(stream)
        if isinstance(key, g.OperatorLiteral) and key.literal == 'ID':
            break
        if not isinstance(key, g.NameObject):
            raise ValueError('Os parâmetros da imagem inline não puderam ser inspecionados.')
        key_bytes = bytes(stream.getbuffer()[stream.token_start:stream.tell()])
        value = _next_token(stream)
        if value is None or isinstance(value, g.OperatorLiteral):
            raise ValueError('A imagem inline contém parâmetros incompletos.')
        value_bytes = bytes(stream.getbuffer()[stream.token_start:stream.tell()])
        parameters.extend([key_bytes, value_bytes]); values[str(key)] = value
    else:
        raise ValueError('A imagem inline excede os limites de inspeção.')
    filters = values.get('/F', values.get('/Filter'))
    first = filters[0] if isinstance(filters, g.ArrayObject) and filters else filters
    if str(first) not in ('/AHx', '/ASCIIHexDecode'):
        raise ValueError('A imagem inline não pôde ser normalizada para ocultação segura.')
    separator = stream.read(1)
    if not separator or separator not in WHITESPACE:
        raise ValueError('O início da imagem inline está malformado.')
    data = bytearray()
    while True:
        chunk = stream.read(4096)
        if not chunk:
            raise ValueError('A imagem inline está truncada.')
        end = chunk.find(b'>')
        if end >= 0:
            data.extend(chunk[:end + 1]); stream.seek(end + 1 - len(chunk), io.SEEK_CUR)
            break
        data.extend(chunk)
        if len(data) > 128 * 1024**2:
            raise ValueError('A imagem inline excede o limite de inspeção.')
    if re.fullmatch(rb'[0-9A-Fa-f\x00\t\n\x0c\r ]*>', data) is None:
        raise ValueError('A imagem inline normalizada contém bytes inesperados.')
    end_token = _next_token(stream)
    if not isinstance(end_token, g.OperatorLiteral) or end_token.literal != 'EI':
        raise ValueError('O final da imagem inline está malformado.')
    from pdf_inline_privacy import sanitize_asciihex_image
    clean_data = sanitize_asciihex_image(values, bytes(data))
    return b'BI ' + b' '.join(parameters) + b' ID ' + clean_data + b' EI\n'


def sanitize_content(data):
    """Strip marked-content metadata using PDF tokens, never byte regexes."""
    if len(data) > 128 * 1024**2:
        raise ValueError('O stream de página excede o limite de inspeção de ocultação.')
    stream = io.BytesIO(data); output = bytearray(); operands = []; operand_bytes = []; depth = 0; tokens = 0
    rendering_mode = 0; state_stack = []; in_text = False; hidden_text = False; visible_text = False
    try:
        while (token := _next_token(stream)) is not None:
            tokens += 1
            if tokens > 2000000:
                raise ValueError('O stream de página excede o limite de tokens de ocultação.')
            if not isinstance(token, g.OperatorLiteral):
                operands.append(token)
                operand_bytes.append(data[stream.token_start:stream.tell()])
                if len(operands) > 100000:
                    raise ValueError('Há operandos demais no stream de página.')
                continue
            operator = token.literal
            if operator in MARKED_OPERATORS:
                if len(operands) != MARKED_OPERATORS[operator]:
                    raise ValueError('A marcação semântica da página está malformada.')
                if operator in ('BMC', 'BDC'):
                    depth += 1
                elif operator == 'EMC':
                    depth -= 1
                    if depth < 0:
                        raise ValueError('A marcação semântica da página está desbalanceada.')
            elif operator == 'BI':
                if operands:
                    raise ValueError('Há operandos inesperados antes da imagem inline.')
                output.extend(_inline_image(stream))
            else:
                if operator not in CONTENT_OPERATORS:
                    raise ValueError('Operador de página não suportado para ocultação segura: ' + operator)
                if operator == 'q':
                    state_stack.append(rendering_mode)
                elif operator == 'Q':
                    if not state_stack:
                        raise ValueError('O estado gráfico da página está desbalanceado.')
                    rendering_mode = state_stack.pop()
                elif operator == 'BT':
                    if in_text:
                        raise ValueError('Há objetos de texto aninhados.')
                    in_text = True; hidden_text = visible_text = False
                elif operator == 'ET':
                    if not in_text:
                        raise ValueError('O objeto de texto está desbalanceado.')
                    in_text = False
                elif operator == 'Tr':
                    if len(operands) != 1 or not isinstance(operands[0], g.NumberObject) or operands[0] not in range(8):
                        raise ValueError('O modo de renderização de texto é inválido.')
                    rendering_mode = int(operands[0])
                elif operator in ('Tj', 'TJ', "'", '"'):
                    if not in_text:
                        raise ValueError('Há texto fora de um objeto BT/ET.')
                    if rendering_mode == 7:
                        raise ValueError('Texto usado somente como recorte exige uma cópia estática revisada.')
                    if rendering_mode == 3:
                        if visible_text:
                            raise ValueError('O mesmo objeto mistura texto visível e invisível; normalize uma cópia estática.')
                        hidden_text = True
                        if operator == '"' and len(operands) == 3:
                            output.extend(operand_bytes[0] + b' Tw\n' + operand_bytes[1] + b' Tc\n')
                        operands = []; operand_bytes = []
                        continue
                    if hidden_text:
                        raise ValueError('O mesmo objeto mistura texto invisível e visível; normalize uma cópia estática.')
                    visible_text = True
                output.extend(b' '.join(operand_bytes))
                output.extend(b' ' + operator.encode('ascii') + b'\n')
            operands = []; operand_bytes = []
        if depth or operands or in_text or state_stack:
            raise ValueError('O stream de página contém estruturas incompletas.')
        return bytes(output)
    except (PdfError, ValueError, TypeError, IndexError, RecursionError) as exc:
        raise ValueError('Não foi possível remover a semântica oculta da página com segurança. Nenhuma cópia foi publicada.') from exc


def _content_references(doc):
    references = {xref for page in doc for xref in page.get_contents()}
    def collect(value, seen=None):
        seen = set() if seen is None else seen
        if isinstance(value, g.IndirectObject):
            if value.idnum in seen:
                return
            seen.add(value.idnum)
            if doc.xref_is_stream(value.idnum):
                references.add(value.idnum)
            else:
                collect(_object(doc, value.idnum), seen)
        elif isinstance(value, (g.DictionaryObject, g.ArrayObject)):
            for child in value.values() if isinstance(value, g.DictionaryObject) else value:
                collect(child, seen)
    for xref in range(1, doc.xref_length()):
        obj = _object(doc, xref)
        if not isinstance(obj, g.DictionaryObject):
            continue
        if obj.get('/Subtype') == '/Form' or obj.get('/PatternType') == 1:
            if doc.xref_is_stream(xref):
                references.add(xref)
        if '/CharProcs' in obj:
            collect(obj.raw_get('/CharProcs'))
    return references


def _clean_contents(doc):
    # MuPDF parses actual inline image boundaries and emits ASCIIHex data.
    # This allows our lexical pass to avoid guessing EI inside binary pixels.
    for page in doc:
        native = pymupdf._as_pdf_page(page.this, required=True)
        options = pymupdf._make_PdfFilterOptions(recurse=1, sanitize=1, ascii=1)
        pymupdf.mupdf.pdf_filter_page_contents(native.doc(), native, options)
    for xref in _content_references(doc):
        doc.update_stream(xref, sanitize_content(doc.xref_stream(xref)))


def prepare(doc):
    """Prepare actual glyph content before computing the selected rectangles."""
    icc_updates = _icc_privacy_plan(doc)
    _check_supported(doc)
    baseline = dict(encrypted=bool(doc.metadata.get('encryption')), permissions=doc.permissions)
    removed_icons = {}
    for index, page in enumerate(doc):
        removed_icons[index] = [list(annotation.rect) for annotation in page.annots() or []
                                if doc.xref_get_key(annotation.xref, 'Subtype')[1] in MULTIMEDIA_ANNOTATIONS]
    appearance = _appearance(doc, removed_icons)
    for xref, data in icc_updates.items():
        doc.update_stream(xref, data, compress=True)
        # update_stream may replace the filter; stale decoder parameters must
        # not be applied to the new ordinary Flate/raw representation.
        doc.xref_set_key(xref, 'DecodeParms', 'null')
    for page in doc:
        for annotation in list(page.annots() or []):
            subtype = doc.xref_get_key(annotation.xref, 'Subtype')[1]
            if subtype in MULTIMEDIA_ANNOTATIONS or annotation.flags & (1 | 2 | 32):
                page.delete_annot(annotation)
        for widget in list(page.widgets() or []):
            field = _object(doc, widget.xref)
            flags = _resolve(doc, field.get('/F', g.NumberObject(0)))
            if not isinstance(flags, g.NumberObject):
                raise ValueError('Um campo contém flags de visibilidade inválidos.')
            if int(flags) & (1 | 2 | 32):
                page.delete_widget(widget)
    for name in list(doc.embfile_names()):
        doc.embfile_del(name)
    _image_privacy(doc)
    _sanitize_objects(doc)
    _clean_contents(doc)
    # Bake only after removing semantic replacements and external payloads;
    # appearance streams are sanitised in the same pass as page/form content.
    doc.bake(annots=True, widgets=True)
    for page in doc:
        for link in page.get_links():
            page.delete_link(link)
    _sanitize_objects(doc, final=True)
    _clean_contents(doc)
    if _appearance(doc, removed_icons) != appearance:
        raise ValueError('O saneamento alteraria a aparência fora dos anexos removidos. Nenhuma cópia foi publicada; prepare uma cópia estática revisada.')
    baseline['appearance'] = _appearance(doc, {})
    return baseline


def record_regions(doc, audit, page, rectangles):
    audit['appearance'][page] = _page_appearance(doc[page], rectangles)


def finish(doc):
    _sanitize_objects(doc, final=True)
    _clean_contents(doc)


def verify_saved(path, password, audit):
    """Check the rewritten bytes before run() can publish the staged file."""
    from pdf_engine import open_pdf
    with open_pdf(path, password) as doc:
        if bool(doc.metadata.get('encryption')) != audit['encrypted'] or doc.permissions != audit['permissions']:
            raise ValueError('A proteção da cópia de ocultação não corresponde à origem.')
        if doc.embfile_count() or doc.get_xml_metadata():
            raise ValueError('A cópia ainda contém anexos ou metadados; nenhuma saída foi publicada.')
        if doc.xref_get_key(-1, 'Info')[0] != 'null':
            raise ValueError('A cópia ainda contém metadados de documento; nenhuma saída foi publicada.')
        catalog = _object(doc, doc.pdf_catalog())
        if CATALOG_PRIVATE_KEYS.intersection(map(str, catalog)):
            raise ValueError('A cópia ainda contém navegação ou estruturas privadas de catálogo.')
        if _icc_privacy_plan(doc):
            raise ValueError('A cópia ainda contém metadados ICC não saneados; nenhuma saída foi publicada.')
        _image_privacy(doc, verify=True)
        def check(dictionary, output_intent=False):
            if PRIVATE_KEYS.intersection(map(str, dictionary)):
                raise ValueError('A cópia ainda contém estruturas privadas ou semântica oculta.')
            if (output_intent or dictionary.get('/Type') == '/OutputIntent') and OUTPUT_INTENT_PRIVATE_KEYS.intersection(map(str, dictionary)):
                raise ValueError('A cópia ainda contém descrições privadas de saída de cor.')
            if dictionary.get('/Type') in DISCARDED_TYPES or dictionary.get('/Type') == '/Annot':
                raise ValueError('A cópia ainda contém objetos privados ou anotações interativas.')
        resource_maps = _resource_map_references(doc)
        output_intents = _output_intent_references(doc)
        for xref in range(1, doc.xref_length()):
            _walk_metadata_dicts(_object(doc, xref), check, xref in resource_maps, output_intent=xref in output_intents)
        for page in doc:
            if list(page.annots() or []) or list(page.widgets() or []) or page.get_links():
                raise ValueError('A cópia ainda contém interatividade não saneada.')
        for xref in _content_references(doc):
            data = doc.xref_stream(xref)
            if sanitize_content(data) != data:
                raise ValueError('A cópia persistida ainda contém semântica marcada não saneada.')
        for page_index, rectangles in audit['rectangles'].items():
            page = doc[page_index]
            if audit['term'] and page.search_for(audit['term']):
                raise ValueError('O texto solicitado ainda está presente na página; nenhuma cópia foi publicada.')
            if not audit['term']:
                for rectangle in rectangles:
                    if page.get_textbox(fitz.Rect(rectangle)).strip():
                        raise ValueError('A área solicitada ainda contém texto; nenhuma cópia foi publicada.')
        if _appearance(doc, audit['rectangles']) != audit['appearance']:
            raise ValueError('A cópia alterou a aparência fora das regiões removidas. Nenhuma saída foi publicada.')
