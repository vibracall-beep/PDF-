"""Prove the source color/state of simple vectors before rewriting them.

MuPDF exposes display RGB, which is insufficient to preserve spot plates,
overprint or calibrated color spaces. This bounded operator/resource reader
accepts DeviceRGB/DeviceGray and default print states; text additionally preserves
validated ICC Gray/RGB profiles without converting their source components. It does not use raw
substring searches that can mistake strings for operators or miss escaped names.
"""
import io
import math

import fitz
from pyhanko.pdf_utils import generic as g
from pyhanko.pdf_utils.misc import PdfReadError


class UnprovedVectorState(ValueError): pass


def _content_token(stream,xref):
    """Read top-level operators without confusing PDF f with boolean false."""
    char=stream.read(1);stream.seek(-1,1)
    if char in (b"'",b'"'):
        stream.read(1);return g.OperatorLiteral(char.decode('ascii'))
    if char.isalpha():
        literal=g.read_until_delimiter(stream)
        if literal==b'true': return g.BooleanObject(True)
        if literal==b'false': return g.BooleanObject(False)
        if literal==b'null': return g.NullObject()
        if not literal.isascii() or literal==b'R': raise PdfReadError('Invalid content operator')
        return g.OperatorLiteral(literal.decode('ascii'))
    return g.read_object(stream,g.Reference(xref),in_content_stream=g.ContentOpReading.GRAPHIC_OPS)


def source_states(doc,page,paint,include_text=False):
    cache={};budget=0
    def unsupported(): raise UnprovedVectorState('A cor, os operadores ou o estado gráfico original não podem ser preservados por este editor.')
    def parsed(xref):
        nonlocal budget
        if xref not in cache:
            budget+=1
            if budget>10000: unsupported()
            raw=doc.xref_object(xref,compressed=False).encode('utf-8')
            if len(raw)>4*1024*1024: unsupported()
            cache[xref]=g.read_object(io.BytesIO(raw),g.Reference(xref))
        return cache[xref]
    def resolve(value):
        seen=set()
        while isinstance(value,g.IndirectObject):
            if value.idnum in seen or len(seen)>32: unsupported()
            seen.add(value.idnum);value=parsed(value.idnum)
        return value
    def raw(mapping,key,default=None):
        if not isinstance(mapping,g.DictionaryObject): unsupported()
        try: return mapping.raw_get(key)
        except KeyError: return default
    def mapping(value):
        value=resolve(value)
        if value is None or isinstance(value,g.NullObject): return g.DictionaryObject()
        if not isinstance(value,g.DictionaryObject): unsupported()
        return value
    def numbers(values,count):
        if len(values)!=count or any(not isinstance(value,(g.NumberObject,g.FloatObject)) or not math.isfinite(float(value)) for value in values): unsupported()
        return tuple(float(value) for value in values)
    current=parsed(page.xref);seen=set()
    if raw(current,'/Group') is not None: unsupported()
    resources=None
    while resources is None:
        resources=raw(current,'/Resources')
        if resources is not None: break
        parent=raw(current,'/Parent')
        if not isinstance(parent,g.IndirectObject) or parent.idnum in seen or len(seen)>64: unsupported()
        seen.add(parent.idnum);current=mapping(parent)
    resources=mapping(resources)
    colors=mapping(raw(resources,'/ColorSpace'))
    if any(raw(colors,name) is not None for name in ('/DefaultGray','/DefaultRGB','/DefaultCMYK')): unsupported()
    ext=mapping(raw(resources,'/ExtGState'));xobjects=mapping(raw(resources,'/XObject'));validated_profiles=set()
    def color_space(value):
        if not isinstance(value,g.NameObject): unsupported()
        if str(value) not in ('/DeviceRGB','/DeviceGray'):
            value=resolve(raw(colors,str(value)))
        if isinstance(value,g.NameObject) and str(value) in ('/DeviceRGB','/DeviceGray'): return str(value)
        if include_text and isinstance(value,g.ArrayObject) and len(value)==2 and str(value.raw_get(0))=='/ICCBased':
            reference=value.raw_get(1)
            if not isinstance(reference,g.IndirectObject): unsupported()
            profile=mapping(reference)
            if set(map(str,profile.keys()))-{'/N','/Alternate','/Range','/Length','/Filter','/DecodeParms'}: unsupported()
            channels=numbers([resolve(raw(profile,'/N'))],1)[0]
            if channels not in (1,3): unsupported()
            channels=int(channels);base='/DeviceGray' if channels==1 else '/DeviceRGB'
            alternate=resolve(raw(profile,'/Alternate'))
            if alternate is not None and str(alternate)!=base: unsupported()
            limits=resolve(raw(profile,'/Range'))
            if limits is not None and (not isinstance(limits,g.ArrayObject) or numbers(limits,channels*2)!=(0.0,1.0)*channels): unsupported()
            if reference.idnum not in validated_profiles:
                from print_inspection import icc_description
                if icc_description(doc.xref_stream(reference.idnum))['color_space']!=('GRAY' if channels==1 else 'RGB'): unsupported()
                validated_profiles.add(reference.idnum)
            return ('/ICCBased',channels,reference.idnum)
        unsupported()
    def graphics_state(name):
        if not isinstance(name,g.NameObject): unsupported()
        state=mapping(raw(ext,str(name)))
        if not state: unsupported()
        allowed={'/Type','/LW','/LC','/LJ','/ML','/D','/CA','/ca','/BM','/OP','/op','/OPM'}
        if set(map(str,state.keys()))-allowed: unsupported()
        for key in state.keys():
            value=resolve(raw(state,key))
            if key=='/Type' and str(value)!='/ExtGState': unsupported()
            if key in ('/CA','/ca') and numbers([value],1)!=(1.0,): unsupported()
            if key=='/BM' and str(value)!='/Normal': unsupported()
            if key in ('/OP','/op') and (not isinstance(value,g.BooleanObject) or bool(value)): unsupported()
            if key=='/OPM' and numbers([value],1)!=(0.0,): unsupported()
            if key=='/ML' and numbers([value],1)!=(10.0,): unsupported()
            if key in ('/LW','/LC','/LJ'): numbers([value],1)
            if key=='/D':
                if not isinstance(value,g.ArrayObject) or len(value)!=2 or not isinstance(resolve(value[0]),g.ArrayObject): unsupported()
                numbers(resolve(value[0]),len(resolve(value[0])));numbers([resolve(value[1])],1)
    streams=[];total=0
    for xref in page.get_contents():
        data=doc.xref_stream(xref);total+=len(data)
        if total>16*1024*1024: unsupported()
        streams.append(data)
    stream=io.BytesIO(b'\n'.join(streams));operands=[];stack=[];paths=[];path=False;operations=0
    text_paints=[];pending_text=False;in_text=False;clip_rectangle=None
    state=dict(stroke=('/DeviceGray',(0.0,)),fill=('/DeviceGray',(0.0,)),matrix=fitz.Matrix(1,1))
    def flush_text():
        nonlocal pending_text
        if pending_text: text_paints.append(state['fill']);pending_text=False
    def numeric_color(values,space):
        components=numbers(values,space[1] if isinstance(space,tuple) else (3 if space=='/DeviceRGB' else 1))
        if any(not 0<=value<=1 for value in components): unsupported()
        return space,components
    while True:
        char=stream.read(1)
        if not char: break
        if char in b'\x00\t\n\x0c\r ': continue
        if char==b'%':
            while char not in (b'',b'\r',b'\n'): char=stream.read(1)
            continue
        stream.seek(-1,1);token=_content_token(stream,page.xref)
        if not isinstance(token,g.OperatorLiteral):
            operands.append(token)
            if len(operands)>100000: unsupported()
            continue
        operations+=1
        if operations>250000: unsupported()
        op=token.literal
        if op in ('q','Q','g','G','rg','RG','cs','CS','SC','SCN','sc','scn','gs','ri','ET','Do','S','s','f','F','f*','B','B*','b','b*'):
            flush_text()
        if op=='q':
            if operands or len(stack)>=64: unsupported()
            stack.append(dict(state))
        elif op=='Q':
            if operands or not stack: unsupported()
            state=stack.pop()
        elif op=='cm': state['matrix']=fitz.Matrix(*numbers(operands,6))*state['matrix']
        elif op in ('g','G','rg','RG'):
            side='stroke' if op[0].isupper() else 'fill'
            state[side]=numeric_color(operands,'/DeviceGray' if len(op)==1 else '/DeviceRGB')
        elif op in ('cs','CS'):
            if len(operands)!=1: unsupported()
            space=color_space(operands[0]);state['stroke' if op=='CS' else 'fill']=(space,(0.0,)*(space[1] if isinstance(space,tuple) else (3 if space=='/DeviceRGB' else 1)))
        elif op in ('SC','SCN','sc','scn'):
            side='stroke' if op[0].isupper() else 'fill';state[side]=numeric_color(operands,state[side][0])
        elif op in ('k','K','BI','ID','EI','sh','BMC','BDC','EMC','BX','EX'): unsupported()
        elif op=='gs':
            if len(operands)!=1: unsupported()
            graphics_state(operands[0])
        elif op=='ri':
            if len(operands)!=1 or str(operands[0])!='/RelativeColorimetric': unsupported()
        elif op=='M':
            if numbers(operands,1)!=(10.0,): unsupported()
        elif op=='Do':
            if len(operands)!=1 or not isinstance(operands[0],g.NameObject): unsupported()
            xobject=mapping(raw(xobjects,str(operands[0])))
            if str(resolve(raw(xobject,'/Subtype')))!='/Image': unsupported()
        elif op in ('m','l','c','v','y','re'):
            values=numbers(operands,{'m':2,'l':2,'c':6,'v':4,'y':4,'re':4}[op])
            if op=='re' and not path:
                x,y,width,height=values;clip_rectangle=fitz.Rect(x,y,x+width,y+height)*state['matrix']
            else: clip_rectangle=None
            path=True
        elif op=='h':
            if operands: unsupported()
        elif op in ('S','s','f','F','f*','B','B*','b','b*'):
            if operands: unsupported()
            matrix=state['matrix']
            if any(abs(a-b)>0.00001 for a,b in zip((matrix.a,matrix.b,matrix.c,matrix.d),(1,0,0,1))): unsupported()
            if path:
                if op not in ('S','s'): paths.append(('fill-path',state['fill']))
                if op in ('S','s','B','B*','b','b*'): paths.append(('stroke-path',state['stroke']))
            path=False
        elif op=='n': path=False;clip_rectangle=None
        elif op in ('W','W*'):
            matrix=state['matrix']
            # CoreGraphics clips to the complete page. This cannot hide or
            # reveal visible content, unlike a partial/curved/transformed clip.
            if operands or clip_rectangle is None or any(abs(a-b)>0.00001 for a,b in zip((matrix.a,matrix.b,matrix.c,matrix.d),(1,0,0,1))) or not clip_rectangle.contains(page.mediabox): unsupported()
        elif op=='BT':
            if in_text or operands: unsupported()
            in_text=True
        elif op=='ET':
            if not in_text or operands: unsupported()
            in_text=False
        elif op in ('Tj','TJ',"'",'"'):
            if not in_text: unsupported()
            if op=='TJ':
                if len(operands)!=1 or not isinstance(operands[0],g.ArrayObject): unsupported()
                values=operands[0]
            else:
                if len(operands)!=(3 if op=='"' else 1): unsupported()
                values=operands[-1:]
            if any(isinstance(value,(g.TextStringObject,g.ByteStringObject)) and len(value) for value in values): pending_text=True
        elif op=='Tr':
            mode=numbers(operands,1)[0]
            if include_text and mode!=0: unsupported()
        elif op in ('w','J','j','d','Tc','Tw','Tz','TL','Tf','Ts','Td','TD','Tm','T*'):
            # Text and line parameters are decoded independently by MuPDF.
            # They cannot select spot color, transparency or an ExtGState.
            pass
        else: unsupported()
        operands=[]
    flush_text()
    if operands or stack or in_text: unsupported()
    observed=[(index,kind) for index,(kind,_) in enumerate(paint) if kind in ('fill-path','stroke-path')]
    if len(observed)!=len(paths) or any(kind!=proof[0] for (_,kind),proof in zip(observed,paths)): unsupported()
    result={index:color for (index,_),(_,color) in zip(observed,paths)}
    if include_text:
        text_indices=[index for index,(kind,_) in enumerate(paint) if kind=='fill-text']
        if len(text_indices)==len(text_paints): result.update(zip(text_indices,text_paints))
        elif len(set(text_paints))==1: result.update((index,text_paints[0]) for index in text_indices)
        elif text_indices or text_paints: unsupported()
    return result


def prove(doc,page,paint,include_text=False):
    try: return source_states(doc,page,paint,include_text=include_text)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,RuntimeError,RecursionError,OverflowError,PdfReadError): return None


def _generated_gray_stream(data,xref,gray):
    return _generated_color_stream(data,xref,(gray,))


def _generated_color_stream(data,xref,components,resource=None,expected=None):
    """Change only decoded color operators in our newly generated text PDF."""
    stream=io.BytesIO(data);operands=[];start=None;changes=[];operations=0
    while True:
        position=stream.tell();char=stream.read(1)
        if not char: break
        if char in b'\x00\t\n\x0c\r ': continue
        if char==b'%':
            while char not in (b'',b'\r',b'\n'): char=stream.read(1)
            continue
        if start is None: start=position
        stream.seek(-1,1);token=_content_token(stream,xref)
        if not isinstance(token,g.OperatorLiteral): operands.append(token);continue
        operations+=1
        if operations>250000: raise ValueError('A composição Unicode excede o limite de operadores verificáveis.')
        op=token.literal
        if op in ('g','G','rg','RG'):
            if len(operands)!=(1 if len(op)==1 else 3) or any(not isinstance(value,(g.NumberObject,g.FloatObject)) for value in operands):
                raise ValueError('A composição Unicode não forneceu uma cor verificável.')
            replacement=f'{components[0]:.8f} '+('G' if op[0].isupper() else 'g')+'\n'
            if resource:
                expected=components if expected is None else expected
                observed=tuple(float(value) for value in operands)
                wanted=expected
                if len(observed)==1 and len(expected)==3 and len(set(expected))==1: wanted=expected[:1]
                if len(observed)==3 and len(expected)==1: wanted=expected*3
                if len(observed)!=len(wanted) or any(not math.isfinite(value) or abs(value-target)>0.000001 for value,target in zip(observed,wanted)):
                    raise ValueError('A composição contém cores diferentes dos componentes ICC originais.')
                values=' '.join(f'{value:.17g}' for value in components)
                replacement=f'/{resource} '+('CS' if op[0].isupper() else 'cs')+f' {values} '+('SC' if op[0].isupper() else 'sc')+'\n'
            changes.append((start,stream.tell(),replacement.encode('ascii')))
        elif op in ('k','K','cs','CS','sc','SC','scn','SCN','gs','BI','ID','EI','sh'):
            raise ValueError('A composição Unicode exige um estado de cor que não preserva os componentes originais.')
        operands=[];start=None
    if operands: raise ValueError('A composição Unicode contém operadores incompletos.')
    for start,end,replacement in reversed(changes): data=data[:start]+replacement+data[end:]
    return data


def place_shaped_gray(page,rect,text,size,gray,alignment,line_spacing):
    """Shape Unicode as before, retaining DeviceGray rather than RGB gray.

    The temporary PDF is wholly generated by this operation. No stream from the
    original document is rewritten, and no colored glyph/image is recolored.
    """
    import pdf_engine
    with fitz.open() as generated:
        scratch=generated.new_page(width=max(72,rect.x1+2),height=max(72,rect.y1+2))
        pdf_engine._html_text(scratch,rect,text,size,(gray,gray,gray),align=alignment,line_spacing=line_spacing)
        if any(kind!='fill-text' for kind,_ in scratch.get_bboxlog()) or not scratch.get_texttrace():
            raise ValueError('A composição Unicode contém desenhos ou imagens que não podem perder sua cor original.')
        traces=scratch.get_texttrace()
        expected=round(gray*255)/255
        if any(trace['type']!=0 or trace.get('opacity',1)!=1 or len(trace['color'])!=3 or
               any(abs(component-expected)>0.0001 for component in trace['color']) for trace in traces):
            raise ValueError('A composição Unicode contém cores que não correspondem ao cinza solicitado.')
        xrefs=set(scratch.get_contents())|{item[0] for item in scratch.get_xobjects()}
        if len(xrefs)>512: raise ValueError('A composição Unicode excede o limite de recursos verificáveis.')
        for xref in xrefs:
            data=generated.xref_stream(xref)
            if len(data)>16*1024*1024: raise ValueError('A composição Unicode excede o limite de dados verificáveis.')
            generated.update_stream(xref,_generated_gray_stream(data,xref,gray))
        # Import only the verified, newly generated text into the target page.
        page.show_pdf_page(rect,generated,0,clip=rect,keep_proportion=False)


def _attach_color_profile(doc,target,profile_xref,channels):
    """Clone dictionaries through MuPDF, retaining original PDF name bytes.

    Re-serializing NameObject through Unicode can turn /F#E9 into a different
    UTF-8 name, stranding existing font invocations. Keep MuPDF's escaped raw
    object spelling, and mutate only fresh dictionaries with ASCII keys.
    """
    def dictionary(kind,value):
        seen=set()
        while kind=='xref':
            xref=int(value.split()[0])
            if xref in seen or len(seen)>64: raise ValueError('Recursos de cor cíclicos.')
            seen.add(xref);value=doc.xref_object(xref,compressed=False)
            # Indirect aliases are valid PDF objects, but not an unbounded chain.
            if value.lstrip().startswith('<<'): kind='dict'
            else:
                parsed=g.read_object(io.BytesIO((value+'\n').encode()),g.Reference(xref))
                if not isinstance(parsed,g.IndirectObject): raise ValueError('Dicionário de recursos de cor inválido.')
                kind='xref';value=f'{parsed.idnum} 0 R'
        if kind=='null': return '<<>>'
        if kind!='dict': raise ValueError('Dicionário de recursos de cor inválido.')
        return value
    owner=target;seen=set()
    while True:
        kind,value=doc.xref_get_key(owner,'Resources')
        if kind!='null': break
        parent_kind,parent=doc.xref_get_key(owner,'Parent')
        if parent_kind=='null': break
        if parent_kind!='xref': raise ValueError('Herança de recursos inválida.')
        owner=int(parent.split()[0])
        if owner in seen or len(seen)>64: raise ValueError('Recursos de página cíclicos.')
        seen.add(owner)
    resources=doc.get_new_xref();doc.update_object(resources,dictionary(kind,value))
    colors=doc.get_new_xref();doc.update_object(colors,dictionary(*doc.xref_get_key(resources,'ColorSpace')))
    prefix='PDFContentGray' if channels==1 else 'PDFContentRGB';index=0
    keys=set(doc.xref_get_keys(colors))
    while f'{prefix}{index}' in keys: index+=1
    name=f'{prefix}{index}'
    doc.xref_set_key(colors,name,f'[/ICCBased {profile_xref} 0 R]')
    doc.xref_set_key(resources,'ColorSpace',f'{colors} 0 R')
    doc.xref_set_key(target,'Resources',f'{resources} 0 R')
    return name


def preserve_generated_color_profile(page,first_xref,profile,components,expected=None):
    """Bind newly generated glyph paint to the original ICC Gray/RGB sample space.

    Original content streams and their resource dictionaries are never rewritten.
    Only content/Form objects allocated by this text operation are eligible.
    """
    doc=page.parent
    if any(image['xref']>=first_xref for image in page.get_image_info(xrefs=True)):
        raise ValueError('A composição incluiu imagens ou glifos coloridos que não podem ser recoloridos pelo perfil ICC.')
    targets=[(xref,page.xref) for xref in page.get_contents() if xref>=first_xref]
    targets.extend((item[0],item[0]) for item in page.get_xobjects() if item[0]>=first_xref)
    if not targets or len(targets)>512: raise ValueError('A composição não forneceu fluxos novos verificáveis para o perfil ICC.')
    channels=len(components);base='/DeviceGray' if channels==1 else '/DeviceRGB'
    profile_xref=doc.get_new_xref();doc.update_object(profile_xref,f'<< /N {channels} /Alternate {base} >>')
    doc.update_stream(profile_xref,profile)
    names={};converted=0
    for xref,resource_target in targets:
        if resource_target not in names: names[resource_target]=_attach_color_profile(doc,resource_target,profile_xref,channels)
        data=doc.xref_stream(xref)
        if len(data)>16*1024*1024: raise ValueError('A composição excede o limite de operadores verificáveis.')
        replaced=_generated_color_stream(data,xref,components,names[resource_target],expected)
        converted+=replaced!=data
        doc.update_stream(xref,replaced)
    if not converted: raise ValueError('A composição não forneceu operadores de cor para preservar o perfil ICC.')
