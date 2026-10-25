"""Source-bound edits of isolated rectangle and axis-aligned line primitives.

Complex paths remain outside this editor. Inspection proves a primitive is
isolated from every other paint operation and interactive object before it can
be removed. Removal checks the complete drawing multiset, not just its count.
"""
from collections import Counter
from bisect import bisect_left,bisect_right
import math
import re
import fitz


def _content():
    import pdf_content
    return pdf_content


def _plain(value):
    if isinstance(value,(fitz.Rect,fitz.Point,fitz.Quad,fitz.Matrix)): return [_plain(part) for part in value]
    if isinstance(value,float): return round(value,5)
    if isinstance(value,(list,tuple)): return [_plain(part) for part in value]
    if isinstance(value,dict): return {key:_plain(part) for key,part in value.items() if key not in ('seqno','level')}
    return value


def signature(drawing): return _content()._digest(_plain(drawing))


def _shape(drawing):
    items=drawing.get('items',[])
    if drawing.get('type') not in ('s','f','fs') or len(items)!=1: return None
    item=items[0]
    if item[0]=='re' and len(item)==3 and item[2] in (-1,1): return 'rectangle'
    if item[0]=='l' and len(item)==3 and drawing['type']=='s':
        a,b=item[1:]
        if (abs(a.x-b.x)<=0.00001) != (abs(a.y-b.y)<=0.00001): return 'line'
    return None


def _hex(color):
    if color is None: return None
    if len(color)!=3: return None
    return '#'+''.join(f'{round(max(0,min(1,value))*255):02x}' for value in color)


def inspect(page,index,source_hash,drawings,paint,interactive,clipped,unusual_group,pending):
    content=_content();bounds=content._bounds(page);records=[]
    from pdf_vector_state import prove
    color_proof=prove(page.parent,page,paint)
    indexed=sorted(enumerate(paint),key=lambda item:item[1][1][1]);tops=[item[1][1][1] for item in indexed]
    tallest=max((area[3]-area[1] for _,area in paint),default=0);comparisons=0
    for position,drawing in enumerate(drawings):
        kind=_shape(drawing)
        if kind is None: continue
        stroke=drawing.get('color') is not None
        width=drawing.get('width',0) if stroke else 0
        if not isinstance(width,(int,float)) or not math.isfinite(width) or width<0: continue
        rect=fitz.Rect(drawing['rect'])+(-width/2,-width/2,width/2,width/2)
        if rect.is_empty or rect.is_infinite: continue
        limitations=[]
        if color_proof is None: limitations.append('vector-graphics-state-unproven')
        if stroke and not 0<width<=100: limitations.append('unsupported-vector-stroke')
        cap=drawing.get('lineCap',(0,0,0))
        if stroke and (len(cap)!=3 or len(set(cap))!=1 or cap[0] not in (0,1,2) or drawing.get('lineJoin') not in (0,1,2)):
            limitations.append('unsupported-vector-stroke')
        if stroke and not re.fullmatch(r'\[\s*(?:\d+(?:\.\d+)?\s*)*\]\s*[+-]?\d+(?:\.\d+)?',drawing.get('dashes','')):
            limitations.append('unsupported-vector-stroke')
        if (stroke and drawing.get('stroke_opacity')!=1) or (drawing.get('fill') is not None and drawing.get('fill_opacity')!=1):
            limitations.append('nonstandard-vector-opacity')
        if drawing.get('layer'): limitations.append('optional-content-vector')
        if clipped: limitations.append('clipped-page-content')
        if unusual_group: limitations.append('nonstandard-transparency-group')
        if pending: limitations.append('pending-redaction')
        if not bounds.contains(rect): limitations.append('vector-outside-visible-page')
        if any(content._overlap(rect,area) for area in interactive): limitations.append('interactive-overlap')
        first=drawing.get('seqno',-1);own={first,first+1} if drawing['type']=='fs' else {first}
        expected=['fill-path','stroke-path'] if drawing['type']=='fs' else ['fill-path'] if drawing['type']=='f' else ['stroke-path']
        if first<0 or first+len(expected)>len(paint) or [paint[order][0] for order in sorted(own)]!=expected:
            limitations.append('unmapped-vector-paint-order')
        else:
            for order,(_,area) in indexed[bisect_left(tops,rect.y0-tallest):bisect_right(tops,rect.y1)]:
                comparisons+=1
                if comparisons>1_000_000:
                    limitations.append('vector-inspection-complexity');break
                if order not in own and content._overlap(rect,area):
                    limitations.append('vector-object-overlap');break
        entry=dict(kind='vector',vector_shape=kind,page=index+1,rect=content._numbers(rect),
            color=_hex(drawing.get('color')),fill_color=_hex(drawing.get('fill')),stroke_width=width,
            editable=not limitations,limitations=sorted(set(limitations)),supported_actions=['move','replace','delete'])
        source_stroke=source_fill=None
        if color_proof is not None:
            for order in own:
                if order not in color_proof: limitations.append('vector-graphics-state-unproven');break
                if paint[order][0]=='stroke-path': source_stroke=color_proof[order][1]
                elif paint[order][0]=='fill-path': source_fill=color_proof[order][1]
        entry['limitations']=sorted(set(limitations));entry['editable']=not limitations
        entry['id']=content._digest([source_hash,'vector',index,position,entry,_plain(drawing)])
        records.append((entry,dict(drawing=drawing,signature=signature(drawing),paint_indices=own,source_stroke=source_stroke,source_fill=source_fill)))
    return records


def plan(doc,entry,internal,edit):
    content=_content();engine=content._engine();page=doc[entry['page']-1]
    drawing=internal['drawing'];rect=content._rect(edit.get('rect',entry['rect']),page)
    color=internal['source_stroke'];fill=internal['source_fill'];width=drawing.get('width',1) or 1
    for name in ('stroke_color','fill_color'):
        if name in edit and edit[name] is not None and not isinstance(edit[name],str): raise ValueError('A cor vetorial deve ser hexadecimal ou null.')
    if 'stroke_color' in edit and (edit['stroke_color'] is None or edit['stroke_color'].casefold()!=(entry.get('color') or '').casefold()):
        color=None if edit['stroke_color'] is None else engine.color(edit['stroke_color'])
    if 'fill_color' in edit and (edit['fill_color'] is None or edit['fill_color'].casefold()!=(entry.get('fill_color') or '').casefold()):
        fill=None if edit['fill_color'] is None else engine.color(edit['fill_color'])
    if 'stroke_width' in edit: width=engine.number(edit['stroke_width'],'Espessura do traço',0.1,100)
    if entry['vector_shape']=='line' and (color is None or fill is not None): raise ValueError('Uma linha exige cor do traço e não aceita preenchimento.')
    if color is None and fill is None: raise ValueError('Escolha traço ou preenchimento; use excluir para remover o vetor.')
    inset=width/2 if color is not None else 0
    if rect.width<2*inset-0.00001 or rect.height<2*inset-0.00001:
        raise ValueError('A espessura excede a área disponível para o vetor.')
    inner=rect+(inset,inset,-inset,-inset)
    if entry['vector_shape']=='rectangle' and (inner.width<=0 or inner.height<=0): raise ValueError('O retângulo precisa de área interna positiva.')
    result=dict(rect=rect,shape=entry['vector_shape'],inner=inner,color=color,fill=fill,width=width,
        line_cap=drawing.get('lineCap',(0,0,0))[0] if drawing.get('color') is not None else 0,
        line_join=drawing.get('lineJoin',0) or 0,dashes=drawing.get('dashes','[] 0') or '[] 0')
    if entry['vector_shape']=='line':
        a,b=drawing['items'][0][1:]
        if abs(a.y-b.y)<=0.00001:
            result['points']=(fitz.Point(inner.x0,(inner.y0+inner.y1)/2),fitz.Point(inner.x1,(inner.y0+inner.y1)/2))
            if a.x>b.x: result['points']=tuple(reversed(result['points']))
        else:
            result['points']=(fitz.Point((inner.x0+inner.x1)/2,inner.y0),fitz.Point((inner.x0+inner.x1)/2,inner.y1))
            if a.y>b.y: result['points']=tuple(reversed(result['points']))
        if result['points'][0]==result['points'][1]: raise ValueError('A linha precisa ter comprimento positivo.')
    with fitz.open() as proof:
        scratch=proof.new_page(width=max(72,rect.x1+1),height=max(72,rect.y1+1));place(scratch,result)
        if len(scratch.get_drawings())!=1 or any(not (rect+(-0.05,-0.05,0.05,0.05)).contains(fitz.Rect(area)) for _,area in scratch.get_bboxlog()):
            raise ValueError('A prova geométrica do vetor excede a área de destino.')
    return result


def place(page,plan):
    common=dict(color=plan['color'],width=plan['width'],lineCap=plan['line_cap'],lineJoin=plan['line_join'],dashes=plan['dashes'])
    if plan['shape']=='rectangle': page.draw_rect(plan['inner'],fill=plan['fill'],**common)
    else: page.draw_line(*plan['points'],**common)


def erase(page,entry,internal):
    before=Counter(signature(drawing) for drawing in page.get_drawings())
    if before[internal['signature']]!=1: raise ValueError('O desenho original mudou ou deixou de ser um objeto isolado. Inspecione novamente.')
    page.add_redact_annot(fitz.Rect(entry['rect'])+(-0.01,-0.01,0.01,0.01),fill=False)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,text=fitz.PDF_REDACT_TEXT_NONE)
    expected=before.copy();expected[internal['signature']]-=1
    if Counter(signature(drawing) for drawing in page.get_drawings())!=+expected:
        raise ValueError('A remoção não preservou todos os demais desenhos. Nenhuma cópia foi criada.')
