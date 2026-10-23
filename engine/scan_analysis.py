"""Local raster structure analysis: Tesseract words plus measured ruling geometry.

Scores describe observed OCR confidence / border evidence, not calibrated accuracy.
The analysis is deliberately reviewable and does not create fields automatically.
"""
from __future__ import annotations
import csv
import io
import math
from pathlib import Path
import re
import tempfile

import fitz
from PIL import Image, ImageDraw, ImageOps


def _number(value, name, low, high, integer=False):
    if isinstance(value, bool): raise ValueError(f'{name}: número inválido.')
    try: value = float(value)
    except (ValueError, TypeError): raise ValueError(f'{name}: número inválido.') from None
    if not math.isfinite(value) or not low <= value <= high or (integer and not value.is_integer()):
        raise ValueError(f'{name}: valor fora do intervalo permitido.')
    return int(value) if integer else value


def source_mode(page, options):
    mode = options.get('source', 'auto')
    if mode not in ('auto', 'vector', 'ocr'): raise ValueError('source deve ser auto, vector ou ocr.')
    if mode != 'auto': return mode
    text = page.get_text().strip()
    # Do not OCR illustrations inside an otherwise searchable page.
    if text: return 'vector'
    return 'ocr' if page.get_images() else 'vector'


def _segments(image, scale, vertical=False):
    """Collect black runs using byte regex, coalescing the thickness of each rule."""
    if vertical: image = image.transpose(Image.Transpose.TRANSPOSE)
    width, height = image.size
    data = image.tobytes()
    minimum = max(10, round(7 * scale))
    pattern = re.compile(b'\x00{' + str(minimum).encode() + b',}')
    segments = []
    active = []
    tolerance = max(2, round(scale))
    for row in range(height):
        candidates = []
        for match in pattern.finditer(data, row * width, (row + 1) * width):
            start, end = match.start() - row * width, match.end() - row * width
            previous = next((line for line in active if row-line['last'] <= tolerance and abs(line['start']-start) <= tolerance and abs(line['end']-end) <= tolerance), None)
            if previous is None:
                previous = dict(start=start, end=end, first=row, last=row)
                segments.append(previous)
                if len(segments) > 50000: raise ValueError('A imagem contém regras demais para analisar com segurança. Recorte a região desejada.')
            else:
                previous['start'] = min(previous['start'], start)
                previous['end'] = max(previous['end'], end)
                previous['last'] = row
            candidates.append(previous)
        selected={id(line) for line in candidates}
        active = candidates + [line for line in active if id(line) not in selected and row-line['last'] < tolerance]
    # Characters can contain short straight runs; rectangles require all four edges.
    return [dict(start=line['start'], end=line['end'], at=(line['first']+line['last']+1)/2,
                 thickness=line['last']-line['first']+1) for line in segments
            if line['last']-line['first']+1 <= max(12, 6*scale)]


def _components(horizontal, vertical, tolerance):
    neighbours = {('h', i): [] for i in range(len(horizontal))}
    neighbours.update({('v', i): [] for i in range(len(vertical))})
    for h, line in enumerate(horizontal):
        for v, other in enumerate(vertical):
            if line['start']-tolerance <= other['at'] <= line['end']+tolerance and other['start']-tolerance <= line['at'] <= other['end']+tolerance:
                neighbours['h', h].append(('v', v)); neighbours['v', v].append(('h', h))
    seen = set()
    for node, edges in neighbours.items():
        if node in seen or not edges: continue
        stack = [node]; nodes = []
        while stack:
            current = stack.pop()
            if current in seen: continue
            seen.add(current); nodes.append(current); stack.extend(neighbours[current])
        hs = sorted([horizontal[index] for axis,index in nodes if axis=='h'], key=lambda line:line['at'])
        vs = sorted([vertical[index] for axis,index in nodes if axis=='v'], key=lambda line:line['at'])
        if len(hs)>=2 and len(vs)>=2: yield hs,vs


def _read_words(tsv, width, height):
    required = {'level','left','top','width','height','conf','text'}
    reader = csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE)
    if not required.issubset(reader.fieldnames or []): raise RuntimeError('Tesseract não produziu uma tabela TSV válida.')
    words = []
    for row in reader:
        try:
            if row['level']!='5' or not row['text'].strip(): continue
            confidence = float(row['conf'])
            left,top,w,h = [float(row[key]) for key in ('left','top','width','height')]
            if not all(math.isfinite(value) for value in (confidence,left,top,w,h)) or not 0<=confidence<=100 or w<=0 or h<=0:
                raise ValueError()
            rect = fitz.Rect(left,top,left+w,top+h)
            if not fitz.Rect(-2,-2,width+2,height+2).contains(rect): raise ValueError()
        except (ValueError,TypeError,KeyError,AttributeError): raise RuntimeError('Tesseract retornou coordenadas ou confiança inválidas.') from None
        words.append(dict(text=row['text'],rect=list(rect),confidence=confidence/100))
    return words


def _lines(words):
    groups = []
    for word in sorted(words,key=lambda word:(word['rect'][1],word['rect'][0])):
        box=fitz.Rect(word['rect']); middle=(box.y0+box.y1)/2
        line=next((line for line in groups if abs(line['middle']-middle)<=max(line['height'],box.height)*0.45),None)
        if line is None:
            line=dict(middle=middle,height=box.height,words=[]); groups.append(line)
        line['words'].append(word)
    return [' '.join(word['text'] for word in sorted(line['words'],key=lambda word:word['rect'][0])) for line in sorted(groups,key=lambda line:line['middle'])]


def _inside(words, rect):
    return [word for word in words if rect.contains(fitz.Point((word['rect'][0]+word['rect'][2])/2,(word['rect'][1]+word['rect'][3])/2))]


def analyze(page, page_number, options, external):
    dpi = _number(options.get('ocr_dpi',200),'DPI do OCR',120,400,integer=True)
    minimum_confidence = _number(options.get('min_confidence',35),'Confiança mínima',0,100)/100
    language = options.get('language','eng')
    if not isinstance(language,str) or not re.fullmatch(r'[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*',language):
        raise ValueError('Idioma OCR inválido; use eng, por ou por+eng.')
    psm = _number(options.get('ocr_psm',6),'Modo de segmentação OCR',3,13,integer=True)
    scale=dpi/72
    bounds=page.rect*page.derotation_matrix
    if math.ceil(bounds.width*scale)*math.ceil(bounds.height*scale)>40_000_000:
        raise ValueError('A página excede 40 milhões de pixels no DPI escolhido. Reduza o DPI ou recorte a página.')
    rotation=page.rotation
    try:
        page.set_rotation(0)
        pix=page.get_pixmap(dpi=dpi,colorspace=fitz.csGRAY,alpha=False)
    finally: page.set_rotation(rotation)
    image=Image.frombytes('L',(pix.width,pix.height),pix.samples); del pix
    image=ImageOps.autocontrast(image,cutoff=0.5)
    binary=image.point(lambda value:0 if value<180 else 255)
    horizontal=_segments(binary,scale); vertical=_segments(binary,scale,vertical=True)
    # A cap keeps noisy scans from turning intersection analysis quadratic without bound.
    if len(horizontal)*len(vertical)>2_000_000:
        raise ValueError('Há ruído demais para separar a estrutura. Limpe ou recorte a digitalização.')
    tolerance=max(3,scale*1.5)
    components=[]
    for hs,vs in _components(horizontal,vertical,tolerance):
        # Every ruling must meet the perpendicular borders. Rounded glyphs such
        # as O/D have gaps at these corners and must never be erased as boxes.
        if (vs[-1]['at']-vs[0]['at'])/scale<7 or (hs[-1]['at']-hs[0]['at'])/scale<7: continue
        if not all(line['start']<=vs[0]['at']+0.5 and line['end']>=vs[-1]['at']-0.5 for line in hs): continue
        if not all(line['start']<=hs[0]['at']+0.5 and line['end']>=hs[-1]['at']-0.5 for line in vs): continue
        components.append((hs,vs))
    structural_h=[]; structural_v=[]
    for hs,vs in components: structural_h.extend(hs); structural_v.extend(vs)
    # Suppress rules in an OCR-only image; the input PDF and exported image are untouched.
    cleaned=image.copy(); drawing=ImageDraw.Draw(cleaned)
    underlines=[line for line in horizontal if line not in structural_h and (line['end']-line['start'])/scale>=35]
    for axis,lines in (('h',structural_h+underlines),('v',structural_v)):
        for line in lines:
            half=line['thickness']/2+1
            box=(line['start'],line['at']-half,line['end'],line['at']+half) if axis=='h' else (line['at']-half,line['start'],line['at']+half,line['end'])
            drawing.rectangle(box,fill=255)
    with tempfile.TemporaryDirectory(prefix='pdf-ocr-structure-') as temporary:
        path=Path(temporary)/'page.png'; cleaned.save(path)
        response=external(['tesseract',path,'stdout','-l',language,'--psm',str(psm),'--dpi',str(dpi),'tsv'],timeout=180)
        words=_read_words(response.stdout,image.width,image.height)
    tables=[]; rectangles=[]
    for hs,vs in components:
        if (len(hs)-1)*(len(vs)-1)>4096: raise ValueError('A grade excede 4.096 células. Analise uma região menor.')
        rows=[]; cells=[]; complete=True
        for row,(top,bottom) in enumerate(zip(hs,hs[1:])):
            values=[]
            for column,(left,right) in enumerate(zip(vs,vs[1:])):
                rect=fitz.Rect(left['at'],top['at'],right['at'],bottom['at'])
                edges=(top['start']<=rect.x0+tolerance and top['end']>=rect.x1-tolerance and bottom['start']<=rect.x0+tolerance and bottom['end']>=rect.x1-tolerance and left['start']<=rect.y0+tolerance and left['end']>=rect.y1-tolerance and right['start']<=rect.y0+tolerance and right['end']>=rect.y1-tolerance)
                if not edges: complete=False; values.append(''); continue
                inside=_inside(words,rect)
                value='\n'.join(_lines(inside)); values.append(value)
                confidence=sum(word['confidence'] for word in inside)/len(inside) if inside else 0
                cells.append(dict(row=row,column=column,rect=list(rect/scale),text=value,confidence=round(confidence,4)))
                rectangles.append((rect,inside))
            rows.append(values)
        nonempty=sum(bool(value) for row in rows for value in row)
        if complete and len(rows)>=2 and len(vs)>=3 and nonempty>=2:
            confidence=sum(cell['confidence'] for cell in cells if cell['text'])/nonempty
            tables.append(dict(rect=[vs[0]['at']/scale,hs[0]['at']/scale,vs[-1]['at']/scale,hs[-1]['at']/scale],rows=rows,cells=cells,confidence=round(confidence,4),source='ocr-grid',review_required=True))
    fields=[]; seen=[]
    for rect,inside in rectangles:
        point_rect=(rect/scale) & bounds
        if inside or not 7<=point_rect.height<=100 or not 7<=point_rect.width<=450: continue
        # Failed OCR does not mean a cell is empty. Check its raster interior so
        # printed/handwritten marks never become apparently blank form fields.
        inset=max(3,round(2.5*scale))
        interior=(math.ceil(rect.x0+inset),math.ceil(rect.y0+inset),math.floor(rect.x1-inset),math.floor(rect.y1-inset))
        if interior[2]<=interior[0] or interior[3]<=interior[1]: continue
        region=binary.crop(interior)
        if region.histogram()[0]/(region.width*region.height)>0.006: continue
        if any(abs(rect.x0-prior.x0)<tolerance and abs(rect.y0-prior.y0)<tolerance for prior in seen): continue
        seen.append(rect)
        left=fitz.Rect(max(0,rect.x0-180*scale),rect.y0-4*scale,rect.x0,rect.y1+4*scale)
        above=fitz.Rect(max(0,rect.x0-20*scale),max(0,rect.y0-28*scale),rect.x1,rect.y0)
        kind='checkbox' if point_rect.width<=26 and point_rect.height<=26 else 'text'
        right=fitz.Rect(rect.x1,rect.y0-4*scale,min(image.width,rect.x1+180*scale),rect.y1+4*scale)
        label_words=(_inside(words,right) if kind=='checkbox' else []) or _inside(words,left) or _inside(words,above)
        label=' '.join(_lines(label_words))[-160:]
        confidence=sum(word['confidence'] for word in label_words)/len(label_words) if label_words else 0.45
        kind='checkbox' if point_rect.width<=26 and point_rect.height<=26 else 'text'
        fields.append(dict(name=f'ocr_{page_number}_{len(fields)+1}',page=page_number,type=kind,rect=[round(value,3) for value in point_rect],label=label,confidence=round(confidence,4),source='ocr-grid',review_required=True,low_confidence=confidence<minimum_confidence))
    # Underlined fields can be unconnected to a vertical border.
    for line in horizontal:
        if line in structural_h or (line['end']-line['start'])/scale<35: continue
        rect=fitz.Rect(line['start']/scale,max(0,line['at']/scale-18),line['end']/scale,line['at']/scale+2)
        if _inside(words,rect*scale) or not bounds.contains(rect): continue
        label_words=_inside(words,fitz.Rect(max(0,rect.x0-180),rect.y0-5,rect.x0,rect.y1+5)*scale)
        if not label_words: continue
        confidence=sum(word['confidence'] for word in label_words)/len(label_words)
        fields.append(dict(name=f'ocr_{page_number}_{len(fields)+1}',page=page_number,type='text',rect=list(rect),label=' '.join(_lines(label_words))[-160:],confidence=round(confidence*0.85,4),source='ocr-line',review_required=True,low_confidence=confidence<minimum_confidence))
    for word in words: word['rect']=[round(value/scale,3) for value in word['rect']]
    return dict(page=page_number,source='ocr',dpi=dpi,language=language,words=words,lines=_lines(words),tables=tables,fields=fields,review_required=True,
                low_confidence_words=sum(word['confidence']<minimum_confidence for word in words),
                limitations=['Scores are OCR evidence, not calibrated accuracy.','Upright ruled tables are supported; merged cells, borderless tables, handwriting and skew require review.'])


def elements(analysis):
    """Emit editable paragraphs and tables in approximate reading order."""
    entries=[dict(type=2,bbox=table['rect'],rows=table['rows']) for table in analysis['tables']]
    words=[word for word in analysis['words'] if not any(fitz.Rect(table['rect']).contains(fitz.Point((word['rect'][0]+word['rect'][2])/2,(word['rect'][1]+word['rect'][3])/2)) for table in analysis['tables'])]
    groups=[]
    for word in sorted(words,key=lambda word:(word['rect'][1],word['rect'][0])):
        rect=fitz.Rect(word['rect']); middle=(rect.y0+rect.y1)/2
        group=next((group for group in groups if abs(group['middle']-middle)<=max(group['height'],rect.height)*0.45),None)
        if group is None:
            group=dict(middle=middle,height=rect.height,words=[]); groups.append(group)
        group['words'].append(word)
    for group in groups:
        ordered=sorted(group['words'],key=lambda word:word['rect'][0]); bounds=fitz.Rect(ordered[0]['rect'])
        for word in ordered[1:]: bounds |= fitz.Rect(word['rect'])
        spans=[dict(text=word['text']+(' ' if index<len(ordered)-1 else ''),size=max(4,fitz.Rect(word['rect']).height),flags=0,color=0) for index,word in enumerate(ordered)]
        entries.append(dict(type=0,bbox=list(bounds),lines=[dict(spans=spans)]))
    return sorted(entries,key=lambda entry:(round(entry['bbox'][1]/8),entry['bbox'][0]))
