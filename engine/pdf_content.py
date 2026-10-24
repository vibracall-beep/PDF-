"""Inspected, source-bound content edits and human-reviewed local OCR.

This module edits an intentionally bounded subset of PDF content. It never
claims arbitrary content-stream roundtripping or inferred font equivalence.
The engine's transaction layer owns publication of the resulting new file.
"""
from __future__ import annotations

from collections import Counter
from bisect import bisect_left, bisect_right
import hashlib
import io
import json
import os
import re
import subprocess
import statistics
import unicodedata

import fitz

SOURCE_LIMIT = 256 * 1024 * 1024
JSON_LIMIT = 32 * 1024 * 1024
OBJECT_LIMIT = 100_000
TEXT_LIMIT = 8 * 1024 * 1024
BASE_FONTS = {'Helvetica':'helv','Helvetica-Bold':'hebo','Helvetica-Oblique':'heit',
    'Helvetica-BoldOblique':'hebi','Times-Roman':'tiro','Times-Bold':'tibo',
    'Times-Italic':'tiit','Times-BoldItalic':'tibi','Courier':'cour',
    'Courier-Bold':'cobo','Courier-Oblique':'coit','Courier-BoldOblique':'cobi'}


def _engine():
    import pdf_engine
    return pdf_engine


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _source(path, options):
    from ocr_page import _read_regular
    data = _read_regular(path, SOURCE_LIMIT)
    digest = hashlib.sha256(data).hexdigest()
    doc = fitz.open(stream=data, filetype='pdf')
    if doc.needs_pass and not doc.authenticate(options.get('password', '')):
        doc.close(); raise ValueError('Senha necessária ou incorreta.')
    if not len(doc):
        doc.close(); raise ValueError('O PDF não contém páginas.')
    return doc, digest


def _json(path, value):
    from ocr_page import _private_write
    data = _canonical(value)
    if len(data) > JSON_LIMIT: raise ValueError('A inspeção excede 32 MiB. Selecione menos páginas.')
    _private_write(path, data)


def _save(doc, output):
    """Write only a new staging file, preserving the input encryption."""
    class Sink:
        def __init__(self, stream): self.stream = stream
        def write(self, data): return self.stream.write(data)
        def seek(self, *args): return self.stream.seek(*args)
        def tell(self): return self.stream.tell()
        def flush(self): return self.stream.flush()
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            doc.save(Sink(stream), garbage=4, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            stream.flush(); os.fsync(stream.fileno())
    except BaseException:
        try:
            current = os.lstat(output)
            if (current.st_dev,current.st_ino) == (identity.st_dev,identity.st_ino): os.unlink(output)
        except FileNotFoundError: pass
        raise


def _bounds(page): return page.rect * page.derotation_matrix


def _rect(values, page):
    return _engine().rectangle({'rect': values}, page)


def _numbers(rect): return [round(float(value), 5) for value in rect]


def _overlap(a, b):
    rect = fitz.Rect(a) & fitz.Rect(b)
    return not rect.is_empty and rect.width * rect.height > 0.01


def _font_name(value): return re.sub(r'^[A-Z]{6}\+', '', value or '')


def _font_spec(doc, page, name, fonts=None):
    normalized = _font_name(name)
    candidates = {};standard=False
    for font in fonts if fonts is not None else page.get_fonts(full=True):
        if _font_name(font[3]) != normalized or not font[0]: continue
        try:
            _, extension, _, data = doc.extract_font(font[0])
            if data and extension in ('ttf','otf','cff'):
                fitz.Font(fontbuffer=data)
                candidates[hashlib.sha256(data).hexdigest()] = data
            elif not data and font[2]=='Type1' and normalized in BASE_FONTS: standard=True
        except (ValueError, RuntimeError): continue
    if len(candidates) == 1 and not standard: return {'name':'originalfont', 'buffer':next(iter(candidates.values()))}
    if not candidates and standard: return {'name':BASE_FONTS[normalized],'buffer':None}
    return None


def _content_paint(doc, index):
    """Exclude annotation appearances from content-stream clipping evidence.

    Keep the isolated page only in memory. Annotation/widget rectangles on the
    original page are checked separately and remain protected from editing.
    """
    page=doc[index]
    if next(page.annots() or iter(()),None) is None and next(page.widgets() or iter(()),None) is None:
        return page.get_texttrace(),page.get_bboxlog(),page.get_drawings(extended=True),page.get_text('rawdict',clip=fitz.INFINITE_RECT())
    with fitz.open() as content:
        content.insert_pdf(doc,from_page=index,to_page=index,links=False,annots=False,widgets=False)
        isolated=content[0]
        return isolated.get_texttrace(),isolated.get_bboxlog(),isolated.get_drawings(extended=True),isolated.get_text('rawdict',clip=fitz.INFINITE_RECT())


def _paragraph_records(records, source_hash, page, image_areas, vector_areas, interactive):
    """Group only homogeneous consecutive lines from one source text block."""
    by_block={}
    for entry,internal in records:
        by_block.setdefault(internal['block'],{}).setdefault(internal['line'],[]).append((entry,internal))
    ordered_records=sorted(records,key=lambda record:record[0]['rect'][1])
    tops=[entry['rect'][1] for entry,_ in ordered_records]
    tallest=max((entry['rect'][3]-entry['rect'][1] for entry,_ in records),default=0)
    result=[];comparisons=0
    def collides(area, members):
        nonlocal comparisons
        start=bisect_left(tops,area.y0-tallest);end=bisect_right(tops,area.y1)
        others=[entry['rect'] for entry,_ in ordered_records[start:end] if entry['id'] not in members]
        others.extend([*image_areas,*vector_areas,*interactive])
        for other in others:
            comparisons+=1
            if comparisons>1_000_000: raise ValueError('A página contém objetos demais para validar parágrafos com segurança.')
            if _overlap(area,other): return True
        return False
    def alignment(lines):
        for name,position in (('left',lambda line:line['rect'].x0),('right',lambda line:line['rect'].x1),('center',lambda line:(line['rect'].x0+line['rect'].x1)/2)):
            values=[position(line) for line in lines]
            if max(values)-min(values)<=max(1.5,lines[0]['size']*0.15): return name
        return None
    def emit(lines):
        if len(lines)<2: return
        members=[record for line in lines for record in line['records']];first=members[0][0]
        area=fitz.Rect(lines[0]['rect'])
        for line in lines[1:]: area|=line['rect']
        ids=[entry['id'] for entry,_ in members];member_ids=set(ids)
        limitations=sorted({reason for _,internal in members for reason in internal['base_limitations']})
        if collides(area,member_ids): limitations.append('paragraph-object-overlap')
        spacing=statistics.median((b['baseline']-a['baseline'])/first['font_size'] for a,b in zip(lines,lines[1:]))
        entry=dict(kind='paragraph',page=first['page'],rect=_numbers(area),text='\n'.join(line['text'] for line in lines),
            font=first['font'],font_size=first['font_size'],color=first['color'],font_status=first['font_status'],
            substitution_font=first['substitution_font'],member_ids=ids,line_spacing=round(spacing,5),alignment=alignment(lines),
            editable=not limitations,limitations=sorted(set(limitations)))
        entry['id']=_digest([source_hash,'paragraph',page,entry])
        result.append((entry,dict(font=members[0][1]['font'],member_ids=ids)))
    for blocks in by_block.values():
        group=[]
        for number,records_on_line in sorted(blocks.items()):
            ordered=sorted(records_on_line,key=lambda record:record[0]['rect'][0])
            styles={(entry['font'],round(entry['font_size'],5),entry['color'],internal['flags']) for entry,internal in ordered}
            baselines=[internal['origin'][1] for _,internal in ordered]
            if len(styles)!=1 or max(baselines)-min(baselines)>0.25 or any(_overlap(a[0]['rect'],b[0]['rect']) for a,b in zip(ordered,ordered[1:])):
                emit(group);group=[];continue
            rect=fitz.Rect(ordered[0][0]['rect'])
            for entry,_ in ordered[1:]: rect|=fitz.Rect(entry['rect'])
            line=dict(records=ordered,style=next(iter(styles)),size=ordered[0][0]['font_size'],rect=rect,
                baseline=statistics.mean(baselines),text=''.join(entry['text'] for entry,_ in ordered),number=number)
            if group:
                gap=(line['baseline']-group[-1]['baseline'])/line['size']
                same=number==group[-1]['number']+1 and line['style']==group[-1]['style'] and 1<=gap<=3 and alignment([*group,line]) is not None and len(group)<200
                if same and len(group)>1:
                    prior=(group[-1]['baseline']-group[-2]['baseline'])/line['size']
                    same=abs(prior-gap)<=0.15
                if not same: emit(group);group=[]
            group.append(line)
        emit(group)
    return result


def _inspect(doc, source_hash, pages):
    image_uses = Counter(info['xref'] for page in doc for info in page.get_image_info(xrefs=True) if info['xref'])
    objects=[]; private={}; page_reports=[];font_cache={}
    for index in pages:
        page=doc[index]; bounds=_bounds(page)
        page_reports.append(dict(page=index+1,width=bounds.width,height=bounds.height,rotation=page.rotation,
            cropbox=_numbers(page.cropbox)))
        traces,paint,drawings,raw=_content_paint(doc,index)
        def restricts_page(drawing):
            if drawing['type']!='clip': return False
            items=drawing.get('items',[])
            return not (len(items)==1 and items[0][0]=='re' and fitz.Rect(items[0][1]).contains(bounds))
        clipped=any(restricts_page(drawing) for drawing in drawings)
        unusual_group=any(drawing['type']=='group' and (drawing.get('opacity',1)!=1 or drawing.get('blendmode','Normal')!='Normal') for drawing in drawings)
        origins={}
        for trace in traces:
            for code,_,origin,_ in trace['chars']:
                if 0<=code<=0x10ffff:
                    origins.setdefault((round(origin[0],3),round(origin[1],3),chr(code)),set()).add(trace['seqno'])
        interactive=[tuple(a.rect) for a in page.annots() or []]+[tuple(w.rect) for w in page.widgets() or []]
        interactive.extend(tuple(link['from']) for link in page.get_links())
        pending=any(a.type[0]==fitz.PDF_ANNOT_REDACT for a in page.annots() or [])
        text_records=[];fonts=page.get_fonts(full=True)
        for block_number,block in enumerate(raw['blocks']):
            if block['type']!=0: continue
            for line_number,line in enumerate(block['lines']):
                for span in line['spans']:
                    text=''.join(char['c'] for char in span['chars'])
                    if not text.strip(): continue
                    rect=fitz.Rect(span['bbox']); limitations=[]
                    if tuple(line.get('dir',(1,0)))!=(1,0): limitations.append('rotated-or-skewed-text')
                    if not bounds.contains(rect): limitations.append('text-outside-visible-page')
                    if any(_overlap(rect, area) for area in interactive): limitations.append('interactive-overlap')
                    if pending: limitations.append('pending-redaction')
                    if clipped: limitations.append('clipped-page-content')
                    if unusual_group: limitations.append('nonstandard-transparency-group')
                    sequences=set()
                    for char in span['chars']:
                        sequences.update(origins.get((round(char['origin'][0],3),round(char['origin'][1],3),char['c']),set()))
                    if not sequences: limitations.append('unmapped-text-paint-order')
                    elif any(offset>min(sequences) and kind not in ('fill-text','stroke-text','ignore-text') and _overlap(rect,area)
                             for offset,(kind,area) in enumerate(paint)):
                        limitations.append('later-object-overlap')
                    if span.get('alpha',255)!=255 or any((t['type']!=0 or t.get('opacity',1)!=1) and _overlap(rect,t['bbox']) for t in traces):
                        limitations.append('nonstandard-or-invisible-text-rendering')
                    key=(_font_name(span['font']),tuple(font[0] for font in fonts if _font_name(font[3])==_font_name(span['font'])))
                    if key not in font_cache: font_cache[key]=_font_spec(doc,page,span['font'],fonts)
                    spec=font_cache[key]
                    entry=dict(kind='text',page=index+1,rect=_numbers(rect),text=text,font=span['font'],
                        font_size=span['size'],color=f"#{span['color']:06x}",
                        font_status='original' if spec else 'substitution-required',substitution_font='MuPDF Unicode fallback (sans-serif)',limitations=limitations)
                    text_records.append((entry,dict(font=spec,chars=[tuple(c['bbox']) for c in span['chars']],
                        block=block_number,line=line_number,origin=span['origin'],flags=span['flags'],base_limitations=list(limitations))))
                    if len(text_records)>10000: raise ValueError('A página excede 10.000 trechos de texto. Use uma página ou região menos complexa.')
        active=[];overlapping=set();comparisons=0
        for position in sorted(range(len(text_records)),key=lambda offset:text_records[offset][0]['rect'][1]):
            rect=text_records[position][0]['rect'];active=[offset for offset in active if text_records[offset][0]['rect'][3]>rect[1]]
            for offset in active:
                comparisons+=1
                if comparisons>1_000_000: raise ValueError('A página contém sobreposições demais para inspecionar com segurança.')
                if _overlap(rect,text_records[offset][0]['rect']): overlapping.update((offset,position))
            active.append(position)
        for position,(entry,internal) in enumerate(text_records):
            if position in overlapping:
                entry['limitations'].append('overlapping-text-runs')
            entry['editable']=not entry['limitations']
            entry['id']=_digest([source_hash,'text',index,position,entry])
            objects.append(entry);private[entry['id']]=internal
        image_info=page.get_image_info(xrefs=True)
        for position,info in enumerate(image_info):
            limitations=[]; rect=fitz.Rect(info['bbox']); xref=info['xref']; matrix=fitz.Matrix(info['transform'])
            if not xref: limitations.append('inline-image')
            elif image_uses[xref]!=1: limitations.append('shared-image-object')
            if abs(matrix.b)>0.0001 or abs(matrix.c)>0.0001 or matrix.a<=0 or matrix.d<=0: limitations.append('rotated-skewed-or-reflected-image')
            if not bounds.contains(rect): limitations.append('image-outside-visible-page')
            if xref and any(doc.xref_get_key(xref,key)[0]!='null' for key in ('SMask','Mask')): limitations.append('image-mask')
            if any(_overlap(rect,area) for area in interactive): limitations.append('interactive-overlap')
            if pending: limitations.append('pending-redaction')
            entry=dict(kind='image',page=index+1,rect=_numbers(rect),width=info['width'],height=info['height'],
                editable=not limitations,limitations=limitations,supported_actions=['replace','delete'] if clipped or unusual_group else ['replace','move','delete'])
            entry['id']=_digest([source_hash,'image',index,position,xref,entry])
            objects.append(entry);private[entry['id']]=dict(xref=xref,clipped=clipped or unusual_group)
        vectors=[drawing['rect']+(-0.5,-0.5,0.5,0.5) for drawing in page.get_drawings()]
        for entry,internal in _paragraph_records(text_records,source_hash,index,[info['bbox'] for info in image_info],vectors,interactive):
            objects.append(entry);private[entry['id']]=internal
        if len(objects)>OBJECT_LIMIT: raise ValueError('O PDF excede 100.000 objetos inspecionáveis. Selecione menos páginas.')
    return dict(version=1,source_sha256=source_hash,page_count=len(doc),pages=page_reports,objects=objects,
        limitations=['Only isolated horizontal text runs, homogeneous consecutive paragraph groups and uniquely placed axis-aligned images are editable.',
                     'Font substitution requires explicit consent; arbitrary content-stream reconstruction is not claimed.']),private


def inspect_pdf(source, output, options):
    doc,digest=_source(source,options)
    try:
        pages=_engine().parse_pages(options.get('pages'),len(doc))
        report,_=_inspect(doc,digest,pages);_json(output,report)
    finally: doc.close()


def _text_plan(doc, entry, internal, edit):
    engine=_engine();page=doc[entry['page']-1]
    text=engine._checked_text(edit.get('text',entry['text']))
    if not text.strip() or len(text.encode('utf-8'))>65536: raise ValueError('Informe texto não vazio de até 64 KiB; use excluir para remover.')
    rect=_rect(edit.get('rect',entry['rect']),page)
    size=engine.number(edit.get('font_size',entry['font_size']),'Fonte',4,300)
    alignment=edit.get('alignment',entry.get('alignment','left'))
    if alignment not in ('left','center','right','justify'): raise ValueError('Alinhamento desconhecido.')
    spec=internal['font'];substitution=False
    if edit.get('font_file'):
        from ocr_page import _read_regular
        buffer=_read_regular(edit['font_file'],32*1024*1024)
        spec={'name':'customfont','buffer':buffer};substitution=True
    if spec:
        measure=fitz.Font(fontbuffer=spec['buffer']) if spec['buffer'] else fitz.Font(fontname=spec['name'])
        if any(not measure.has_glyph(ord(char)) for char in text if not char.isspace()):
            if edit.get('font_file'): raise ValueError('A fonte escolhida não contém todos os caracteres. Selecione uma fonte compatível.')
            spec=None
        elif not spec['buffer'] and any(ord(char)>255 for char in text): spec=None
        if any(unicodedata.bidirectional(char) in ('R','AL','AN') or unicodedata.category(char).startswith('M') or char in '\u200c\u200d' for char in text):
            if edit.get('font_file'): raise ValueError('Este texto exige composição Unicode. Remova a fonte explícita e autorize a composição automática.')
            spec=None
    if spec is None:
        if edit.get('allow_font_substitution') is not True:
            raise ValueError('A fonte original não suporta este texto. Autorize a substituição ou escolha um arquivo de fonte compatível.')
        substitution=True
    if substitution and edit.get('allow_font_substitution') is not True:
        raise ValueError('A troca de fonte exige allow_font_substitution:true.')
    return dict(text=text,rect=rect,size=size,align=('left','center','right','justify').index(alignment),
        ink=engine.color(edit.get('color',entry['color'])),font=spec,substitution=substitution,
        paragraph=entry['kind']=='paragraph',line_spacing=engine.number(edit.get('line_spacing',entry.get('line_spacing',1.5)),'Espaçamento',1,3))


def _place_text(page, plan, tag):
    rect=plan['rect'];spec=plan['font'];text=plan['text'];size=plan['size']
    if spec is None:
        _engine()._html_text(page,rect,text,size,plan['ink'],align=plan['align'],line_spacing=plan['line_spacing']);return
    name=spec['name'] if spec['buffer'] is None else tag
    if spec['buffer']: page.insert_font(fontname=name,fontbuffer=spec['buffer'])
    font=fitz.Font(fontbuffer=spec['buffer']) if spec['buffer'] else fitz.Font(fontname=name)
    if plan['paragraph']:
        # Isolate the font resource from an existing page font-info cache: some
        # producers use different ascender metadata for the same Base-14 name.
        # The actual font program used for measuring and writing must agree.
        name=tag;buffer=spec['buffer'] or font.buffer
        page.insert_font(fontname=name,fontbuffer=buffer)
        # insert_textbox reserves extra descender space and multiplies a supplied
        # line height by the ascender. Verify actual glyph geometry independently
        # before using its wrapping engine, rather than clipping surplus text.
        internal_rect=rect+(0,0,0,max(size*3,-font.descender*size))
        arguments=dict(fontname=name,fontsize=size,color=plan['ink'],align=plan['align'],lineheight=plan['line_spacing']/max(font.ascender,0.01))
        with fitz.open() as trial:
            proof=trial.new_page(width=max(72,internal_rect.x1+1),height=max(72,internal_rect.y1+1))
            proof.insert_font(fontname=name,fontbuffer=buffer)
            remaining=proof.insert_textbox(internal_rect,text,**arguments)
            glyphs=[fitz.Rect(char['bbox']) for block in proof.get_text('rawdict',clip=fitz.INFINITE_RECT())['blocks'] if block['type']==0 for line in block['lines'] for span in line['spans'] for char in span['chars'] if not char['c'].isspace()]
            if remaining<0 or not glyphs or any(not (rect+(-0.05,-0.05,0.05,0.05)).contains(area) for area in glyphs):
                raise ValueError('O parágrafo não cabe no retângulo com este espaçamento. Nenhuma cópia foi criada.')
        if page.insert_textbox(internal_rect,text,**arguments)<0: raise ValueError('O parágrafo excede a área disponível.')
    elif '\n' not in text and '\r' not in text and plan['align']!=3:
        width=font.text_length(text,fontsize=size)
        if width>rect.width+0.01 or (font.ascender-font.descender)*size>rect.height+0.05:
            raise ValueError('O texto não cabe no retângulo. Ajuste tamanho, área ou conteúdo; nenhuma cópia foi criada.')
        x=rect.x0+(rect.width-width)*({0:0,1:0.5,2:1}[plan['align']])
        page.insert_text((x,rect.y0+font.ascender*size),text,fontname=name,fontsize=size,color=plan['ink'])
    else:
        remaining=page.insert_textbox(rect,text,fontname=name,fontsize=size,color=plan['ink'],align=plan['align'])
        if remaining<0: raise ValueError('O texto não cabe no retângulo. Nenhuma cópia foi criada.')


def apply_edits(source, output, options):
    doc,digest=_source(source,options)
    try:
        if options.get('source_sha256')!=digest: raise ValueError('O PDF mudou desde a inspeção. Inspecione novamente.')
        edits=options.get('edits')
        if not isinstance(edits,list) or not 1<=len(edits)<=1000: raise ValueError('Informe de 1 a 1.000 alterações.')
        report,private=_inspect(doc,digest,list(range(len(doc))));objects={o['id']:o for o in report['objects']}
        planned=[];seen=set();claimed=set()
        for edit in edits:
            if not isinstance(edit,dict) or not isinstance(edit.get('id'),str) or edit['id'] not in objects: raise ValueError('Objeto desconhecido ou inspeção desatualizada.')
            identity=edit['id'];entry=objects[identity];action=edit.get('action')
            if identity in seen: raise ValueError('Um objeto não pode receber duas alterações na mesma transação.')
            seen.add(identity)
            members=set(entry.get('member_ids',[identity]))
            if members & claimed: raise ValueError('Um parágrafo e seus trechos não podem ser alterados juntos na mesma transação.')
            claimed.update(members)
            if not entry['editable']: raise ValueError('Este objeto não pode ser editado com preservação comprovada: '+', '.join(entry['limitations']))
            if action not in ('replace','move','delete'): raise ValueError('Ação de conteúdo desconhecida.')
            plan=None
            if entry['kind'] in ('text','paragraph') and action!='delete':
                plan=_text_plan(doc,entry,private[identity],edit)
                for other in report['objects']:
                    kinds=('text','image') if entry['kind']=='paragraph' else ('text',)
                    if other['kind'] in kinds and other['page']==entry['page'] and other['id'] not in members and _overlap(plan['rect'],other['rect']):
                        raise ValueError('A área de destino sobrepõe outro objeto original. Escolha uma área livre.')
                if entry['kind']=='paragraph':
                    page=doc[entry['page']-1]
                    occupied=[drawing['rect']+(-0.5,-0.5,0.5,0.5) for drawing in page.get_drawings()]
                    occupied.extend(a.rect for a in page.annots() or [])
                    occupied.extend(w.rect for w in page.widgets() or [])
                    occupied.extend(link['from'] for link in page.get_links())
                    if any(_overlap(plan['rect'],area) for area in occupied):
                        raise ValueError('A área do parágrafo sobrepõe gráficos, anotações ou campos. Escolha uma área livre.')
                with fitz.open() as preview:
                    bounds=_bounds(doc[entry['page']-1]);scratch=preview.new_page(width=bounds.width,height=bounds.height)
                    _place_text(scratch,plan,'preflightfont')
            elif entry['kind']=='image' and action!='delete':
                page=doc[entry['page']-1];rect=_rect(edit.get('rect',entry['rect']),page)
                if action=='replace':
                    if any(abs(a-b)>0.001 for a,b in zip(rect,entry['rect'])):
                        raise ValueError('Substitua a imagem na área original ou use mover separadamente; isso preserva a ordem das camadas.')
                    from ocr_page import _read_regular
                    if not isinstance(edit.get('image_path'),str): raise ValueError('Selecione a imagem de substituição.')
                    data=_read_regular(edit['image_path'],64*1024*1024)
                    from PIL import Image
                    with Image.open(io.BytesIO(data)) as image:
                        if image.width*image.height>40_000_000: raise ValueError('A imagem excede 40 milhões de pixels.')
                        if getattr(image,'n_frames',1)!=1: raise ValueError('Selecione uma imagem estática de um único quadro.')
                        image.verify()
                    with fitz.open(stream=data) as image:
                        if len(image)!=1 or image.is_pdf: raise ValueError('Selecione uma imagem estática.')
                else:
                    if private[identity]['clipped']:
                        raise ValueError('Mover esta imagem poderia remover um recorte ou composição original. Apenas substituir na mesma área ou excluir é suportado.')
                    occupied=[o['rect'] for o in report['objects'] if o['kind']!='paragraph' and o['page']==entry['page'] and o['id']!=identity]
                    occupied.extend(drawing['rect'] for drawing in page.get_drawings())
                    if any(_overlap(rect,other) for other in occupied):
                        raise ValueError('Mover a imagem sobre outro objeto poderia alterar a ordem das camadas. Escolha uma área livre.')
                    data=doc.extract_image(private[identity]['xref'])['image']
                plan=dict(rect=rect,data=data)
            if plan and any(old_plan and old_entry['page']==entry['page'] and
                (entry['kind']=='paragraph' or old_entry['kind']=='paragraph') and _overlap(plan['rect'],old_plan['rect'])
                for old_entry,_,old_plan in planned):
                raise ValueError('As áreas de destino de duas alterações se sobrepõem. Nenhuma cópia foi criada.')
            planned.append((entry,action,plan))
        _engine()._separate_page_aliases(doc)
        for entry,action,plan in planned:
            page=doc[entry['page']-1]
            if entry['kind'] in ('text','paragraph'):
                _engine()._reject_pending_redactions(page)
                page.add_redact_annot(fitz.Rect(entry['rect']),fill=False)
                page.apply_redactions(images=0,graphics=0,text=0)
                if plan: _place_text(page,plan,'editedfont'+entry['id'][:12])
            else:
                xref=private[entry['id']]['xref']
                if action=='replace': page.replace_image(xref,stream=plan['data'])
                else:
                    page.delete_image(xref)
                    if plan: page.insert_image(plan['rect'],stream=plan['data'],keep_proportion=False)
        _save(doc,output)
    finally: doc.close()


def _ocr_settings(options):
    engine=_engine()
    if not isinstance(options,dict): raise ValueError('As configurações OCR devem ser um objeto JSON.')
    language=options.get('language','eng')
    if not isinstance(language,str) or not re.fullmatch(r'[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*',language): raise ValueError('Idioma OCR inválido.')
    settings=dict(language=language,ocr_dpi=engine.integer(options.get('ocr_dpi',200),'DPI',120,400),
        ocr_psm=engine.integer(options.get('ocr_psm',6),'Segmentação OCR',3,13),
        min_confidence=engine.number(options.get('min_confidence',35),'Confiança',0,100))
    if 'ocr_deskew' in options:
        if not isinstance(options['ocr_deskew'],bool): raise ValueError('ocr_deskew deve ser true ou false.')
        settings['ocr_deskew']=options['ocr_deskew']
    return settings


def _ocr_report(doc,digest,pages,settings):
    from scan_analysis import analyze
    def external(command,**kwargs):
        try: return _engine()._external(command,**kwargs)
        except (RuntimeError,OSError,subprocess.TimeoutExpired):
            raise RuntimeError('Não foi possível concluir o OCR local. Confira o Tesseract e os idiomas; nenhum resultado foi publicado.') from None
    response=external(['tesseract','--list-langs'],timeout=10)
    available=set(response.stdout.splitlines())
    if not set(settings['language'].split('+')).issubset(available): raise ValueError('Instale todos os idiomas OCR selecionados antes de reconhecer.')
    words=[];page_reports=[];text_size=0
    for index in pages:
        page=doc[index];bounds=_bounds(page)
        if page.get_text().strip(): raise ValueError('A revisão OCR aceita páginas digitalizadas sem texto selecionável, evitando camadas duplicadas.')
        analysis=analyze(page,index+1,settings,external)
        page_reports.append(dict(page=index+1,width=bounds.width,height=bounds.height,rotation=page.rotation))
        if settings.get('ocr_deskew'): page_reports[-1]['preprocessing']=analysis['preprocessing']
        for position,word in enumerate(analysis['words']):
            _rect(word['rect'],page)
            record=dict(page=index+1,rect=_numbers(word['rect']),text=word['text'],confidence=word['confidence'])
            if settings.get('ocr_deskew'): record['quad']=word['quad']
            record['id']=_digest([digest,settings,index,position,record]);words.append(record)
            text_size+=len(word['text'].encode('utf-8'))
        if len(words)>50000 or text_size>TEXT_LIMIT:
            raise ValueError('A revisão OCR excede 50.000 palavras ou 8 MiB de texto. Selecione menos páginas.')
    report=dict(version=1,source_sha256=digest,page_count=len(doc),backend='tesseract',language=settings['language'],settings=settings,
        pages=page_reports,words=words,review_required=True)
    report['review_sha256']=_digest(report)
    return report


def review_ocr(source,output,options):
    doc,digest=_source(source,options)
    try:
        report=_ocr_report(doc,digest,_engine().parse_pages(options.get('pages'),len(doc)),_ocr_settings(options))
        _json(output,report)
    finally: doc.close()


def _place_ocr_word(page,rect,text,font,font_name):
    """Reuse one standard font for Latin OCR instead of grafting one font/word."""
    if all(ord(char)<=255 and (char.isspace() or font.has_glyph(ord(char))) for char in text):
        width=font.text_length(text,fontsize=1)
        size=min(72,rect.height/(font.ascender-font.descender),rect.width/max(width,0.001))*0.995
        if size<1: raise ValueError('A correção OCR não cabe na área original. Reduza a palavra antes de aplicar.')
        page.insert_text((rect.x0,rect.y0+font.ascender*size),text,fontname=font_name,fontsize=size,render_mode=3)
    else:
        size=max(4,min(72,rect.height/1.5))
        _engine()._html_text(page,rect,text,size,(0,0,0),minimum=min(4,size),opacity=0)


def apply_ocr(source,output,options):
    doc,digest=_source(source,options)
    try:
        review=options.get('review')
        if 'review_path' in options:
            if 'review' in options: raise ValueError('Informe review ou review_path, não ambos.')
            from ocr_page import _read_regular
            try: review=json.loads(_read_regular(options['review_path'],JSON_LIMIT))
            except (UnicodeDecodeError,json.JSONDecodeError): raise ValueError('O arquivo de revisão não contém JSON válido.') from None
        if not isinstance(review,dict) or type(review.get('version')) is not int or review['version']!=1 or options.get('source_sha256')!=digest or review.get('source_sha256')!=digest:
            raise ValueError('A revisão OCR não corresponde aos bytes deste PDF.')
        if not isinstance(review.get('pages'),list) or not review['pages']: raise ValueError('A revisão não informa páginas válidas.')
        pages=[_engine().integer(p.get('page'),'Página',1,len(doc))-1 for p in review['pages'] if isinstance(p,dict)]
        if len(pages)!=len(review['pages']) or len(set(pages))!=len(pages): raise ValueError('Páginas OCR inválidas ou duplicadas.')
        settings=_ocr_settings(review.get('settings',{}));current=_ocr_report(doc,digest,pages,settings)
        # Re-recognition binds geometry and IDs to actual source pixels; a
        # caller cannot forge a review hash to inject arbitrary hidden regions.
        if _canonical(review)!=_canonical(current): raise ValueError('O OCR ou sua geometria mudou. Faça uma nova revisão antes de aplicar.')
        corrections=options.get('corrections',[])
        if not isinstance(corrections,list) or len(corrections)>50000: raise ValueError('Correções OCR inválidas.')
        words={w['id']:w for w in current['words']};changed={}
        for edit in corrections:
            if not isinstance(edit,dict) or set(edit)-{'id','text'} or not isinstance(edit.get('id'),str) or edit['id'] not in words or edit['id'] in changed:
                raise ValueError('Uma correção contém identidade, geometria ou propriedade não autorizada.')
            text=_engine()._checked_text(edit.get('text'))
            if not text.strip() or len(text.encode('utf-8'))>4096: raise ValueError('A palavra corrigida deve conter de 1 a 4.096 bytes de texto.')
            if any(char in text for char in '\n\r\t'): raise ValueError('Uma correção de palavra não pode conter quebras de linha ou tabulações.')
            changed[edit['id']]=text
        if not words: raise ValueError('Nenhuma palavra foi reconhecida para criar uma camada OCR.')
        font=fitz.Font('helv')
        shaped=sum(any(ord(char)>255 or (not char.isspace() and not font.has_glyph(ord(char))) for char in changed.get(word['id'],word['text'])) for word in current['words'])
        if shaped>2000: raise ValueError('A revisão excede 2.000 trechos que exigem fontes Unicode compostas. Revise menos páginas por vez para limitar a memória.')
        _engine()._separate_page_aliases(doc)
        font_names={}
        for word in current['words']:
            page=doc[word['page']-1];rect=fitz.Rect(word['rect']);text=changed.get(word['id'],word['text'])
            if word['page'] not in font_names:
                existing={entry[4] for entry in page.get_fonts(full=True)};suffix=0
                while f'OCRReviewFont{suffix}' in existing: suffix+=1
                name=f'OCRReviewFont{suffix}';page.insert_font(fontname=name,fontbuffer=font.buffer);font_names[word['page']]=name
            # Invisible text keeps original pixels, with shaped Unicode fallback
            # only when needed. Reusing Latin resources bounds ordinary OCR RAM.
            _place_ocr_word(page,rect,text,font,font_names[word['page']])
        _save(doc,output)
    finally: doc.close()
