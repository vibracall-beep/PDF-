"""Conservative geometry-based reading order and table-aware extraction.

PDF geometry does not encode semantic reading order reliably. This module uses
observable whitespace to separate columns and keeps ambiguous content in a
stable visual order. It never discards an entire paragraph for intersecting a
table: only characters inside an extracted table are replaced by its cells.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
import fitz


def _bounds(items):
    result=fitz.Rect(items[0]['bbox'])
    for item in items[1:]: result|=fitz.Rect(item['bbox'])
    return result


def _gaps(items, axis):
    intervals=sorted((item['bbox'][axis],item['bbox'][axis+2]) for item in items)
    end=intervals[0][1];gaps=[]
    for start,stop in intervals[1:]:
        if start>end: gaps.append((start-end,(start+end)/2))
        end=max(end,stop)
    return gaps


def reading_order(items, depth=0):
    """Recursive whitespace cuts: columns first, then separated vertical bands."""
    if len(items)<2: return list(items)
    if depth>=32: return sorted(items,key=lambda item:(item['bbox'][1],item['bbox'][0]))
    bounds=_bounds(items)
    vertical=max(_gaps(items,0),default=(0,0))
    horizontal=max(_gaps(items,1),default=(0,0))
    if vertical[0]>=max(12,bounds.width*0.025): axis=0;cut=vertical[1]
    elif horizontal[0]>=6: axis=1;cut=horizontal[1]
    else: return sorted(items,key=lambda item:(round(item['bbox'][1]/3),item['bbox'][0]))
    first=[item for item in items if item['bbox'][axis+2]<=cut]
    second=[item for item in items if item['bbox'][axis]>=cut]
    if not first or not second or len(first)+len(second)!=len(items):
        return sorted(items,key=lambda item:(item['bbox'][1],item['bbox'][0]))
    return reading_order(first,depth+1)+reading_order(second,depth+1)


@dataclass(frozen=True)
class _Table:
    bbox: tuple
    cells: tuple
    row_cells: tuple
    values: list


def _find_tables(page, **options):
    # PyMuPDF Table.extract() reads module-global CHARS from the most recent
    # find_tables call. Snapshot immediately before another clipped search can
    # replace that state and silently empty an earlier table.
    return [_Table(tuple(table.bbox),tuple(table.cells),tuple(tuple(row.cells) for row in table.rows),table.extract())
        for table in page.find_tables(**options).tables]


def _table_geometry(table, rows):
    """Require a complete rectangular tiling before claiming merged cells."""
    cells=[fitz.Rect(cell) for cell in table.cells if cell]
    if not cells or len(cells)>10000: return None
    def boundaries(values):
        groups=[]
        for value in sorted(values):
            if groups and abs(value-groups[-1][-1])<=0.5: groups[-1].append(value)
            else: groups.append([value])
        return [sum(group)/len(group) for group in groups]
    xs=boundaries([coordinate for cell in cells for coordinate in (cell.x0,cell.x1)])
    ys=boundaries([coordinate for cell in cells for coordinate in (cell.y0,cell.y1)])
    if len(xs)<2 or len(ys)<2 or len(rows)!=len(ys)-1 or any(len(row)!=len(xs)-1 for row in rows): return None
    if (len(xs)-1)*(len(ys)-1)>10000: return None
    occupied=set();merges=[]
    for cell in cells:
        column,end_column=[min(range(len(xs)),key=lambda index:abs(xs[index]-value)) for value in (cell.x0,cell.x1)]
        row,end_row=[min(range(len(ys)),key=lambda index:abs(ys[index]-value)) for value in (cell.y0,cell.y1)]
        if end_column<=column or end_row<=row: return None
        tiles={(r,c) for r in range(row,end_row) for c in range(column,end_column)}
        if occupied & tiles: return None
        if any(rows[r][c] not in (None,'') for r,c in tiles-{(row,column)}): return None
        occupied.update(tiles)
        if len(tiles)>1: merges.append(dict(row=row,column=column,row_span=end_row-row,column_span=end_column-column,rect=tuple(cell)))
    if len(occupied)!=(len(xs)-1)*(len(ys)-1): return None
    return dict(merges=merges,column_widths=[b-a for a,b in zip(xs,xs[1:])],row_heights=[b-a for a,b in zip(ys,ys[1:])])


def _aligned_rows(rows):
    """Explicit borderless mode still requires repeated numeric columns."""
    rows=[row for row in rows if any(str(cell or '').strip() for cell in row)]
    if not 3<=len(rows)<=1000: return None
    width=len(rows[0])
    if not 2<=width<=12 or any(len(row)!=width for row in rows): return None
    if any(sum(bool(str(cell or '').strip()) for cell in row)<2 for row in rows): return None
    if sum(bool(str(cell or '').strip()) for row in rows for cell in row)<0.8*width*len(rows): return None
    number=re.compile(r'^[\s$€£¥R()+−\-]*\d[\d\s.,:/%()+−\-]*$')
    if not any(sum(bool(number.fullmatch(str(row[column] or '').strip())) for row in rows[1:])>=max(2,0.8*(len(rows)-1)) for column in range(width)): return None
    return rows


def _aligned_regions(page, table, exclusions):
    """Trim non-tabular titles/footers, then rerun detection on that region.

    Text-strategy detection may extend its inferred columns through nearby
    prose. A row participates only when at least two column cells have text;
    fully empty spacer rows do not create or remove cell content.
    """
    rows=table.values;active=[];regions=[]
    def finish():
        if len(active)<3: return
        candidate=[rows[index] for index in active]
        if _aligned_rows(candidate) is None: return
        cells=[fitz.Rect(cell) for index in active for cell in table.row_cells[index] if cell]
        area=cells[0]
        for cell in cells[1:]: area|=cell
        regions.append(area)
    for index,row in enumerate(rows):
        if any(not (fitz.Rect(cell)&area).is_empty for cell in table.row_cells[index] if cell for area in exclusions):
            finish();active=[];continue
        count=sum(bool(str(cell or '').strip()) for cell in row)
        if count>=2: active.append(index)
        elif count==1: finish();active=[]
    finish()
    result=[]
    for area in regions:
        result.extend(_find_tables(page,clip=area,strategy='text',min_words_vertical=3,min_words_horizontal=2))
    return result


def page_elements(page, options=None):
    mode=(options or {}).get('table_detection','ruled')
    if mode not in ('ruled','aligned'): raise ValueError('Detecção de tabela inválida: use ruled ou aligned.')
    tables=[(table,'ruled') for table in _find_tables(page)]
    if mode=='aligned':
        ruled=[fitz.Rect(table.bbox) for table,_ in tables]
        inferred=_find_tables(page,strategy='text',min_words_vertical=3,min_words_horizontal=2)
        for table in inferred:
            # A prose line spanning two inferred cells is not a header: table
            # evidence starts at a full-width row followed by numeric data.
            raw=table.values;width=max(map(len,raw),default=0)
            first=next((index for index,row in enumerate(raw) if width>=2 and all(str(cell or '').strip() for cell in row)),None)
            if first is None: continue
            if first:
                area=fitz.Rect(table.bbox);area.y0=min(cell[1] for cell in table.row_cells[first] if cell)
                candidates=_find_tables(page,clip=area,strategy='text',min_words_vertical=3,min_words_horizontal=2)
            else: candidates=[table]
            for candidate in candidates:
                for region in _aligned_regions(page,candidate,ruled):
                    if not any(not (fitz.Rect(region.bbox)&rect).is_empty for rect in ruled): tables.append((region,'aligned'))
    blocks=page.get_text('rawdict',sort=False)['blocks']
    # A detected grid is not evidence that all its text was extracted. If any
    # non-whitespace source character is absent from the cells, retain ordinary
    # text for that region rather than silently dropping it during deduplication.
    verified=[]
    for table,detection in tables:
        rows=table.values
        geometry=_table_geometry(table,rows) if detection=='ruled' else None
        if detection=='ruled' and geometry is None: continue
        if detection=='aligned':
            rows=_aligned_rows(rows)
            if rows is None: continue
            geometry=dict(merges=[])
        bounds=fitz.Rect(table.bbox)
        source=Counter(char['c'] for block in blocks if block['type']==0 for line in block['lines'] for span in line['spans'] for char in span['chars']
            if not char['c'].isspace() and bounds.contains((fitz.Rect(char['bbox']).tl+fitz.Rect(char['bbox']).br)/2))
        recovered=Counter(char for row in rows for cell in row for char in str(cell or '') if not char.isspace())
        if not source-recovered:
            verified.append(dict(type=2,bbox=tuple(table.bbox),rows=rows,detection=detection,
                cells=[tuple(cell) if cell else None for cell in table.cells],**geometry))
    table_rects=[fitz.Rect(table['bbox']) for table in verified]
    entries=list(verified)
    for block in blocks:
        if block['type']!=0:
            entries.append(block);continue
        # Keep individual lines so a PDF text block spanning two columns does
        # not force row-wise interleaving. Character boxes retain mixed spans.
        for line in block['lines']:
            spans=[]
            for source in line['spans']:
                kept=[]
                for char in source['chars']:
                    area=fitz.Rect(char['bbox']);middle=(area.tl+area.br)/2
                    if not any(rect.contains(middle) for rect in table_rects): kept.append(char)
                if not kept: continue
                span={key:value for key,value in source.items() if key!='chars'}
                span['text']=''.join(char['c'] for char in kept)
                area=fitz.Rect(kept[0]['bbox'])
                for char in kept[1:]: area|=fitz.Rect(char['bbox'])
                span['bbox']=tuple(area);spans.append(span)
            if not spans or not any(span['text'].strip() for span in spans): continue
            area=_bounds(spans)
            new_line={**line,'spans':spans,'bbox':tuple(area)}
            entries.append(dict(type=0,bbox=tuple(area),lines=[new_line]))
    if len(entries)>25000: raise ValueError('A página excede 25.000 elementos de layout. Selecione uma região menor.')
    return reading_order(entries)


def table_groups(page, options=None):
    """Tables remain separate; prose outside them remains available in Excel."""
    return page_elements(page,options)


def spreadsheet_text(value):
    """An XLSX string cell is safe without changing its visible source text."""
    value='' if value is None else str(value)
    if len(value)>32767: raise ValueError('Uma célula excede o limite de 32.767 caracteres do Excel; nenhum arquivo foi publicado.')
    if any(ord(character)<32 and character not in '\n\r\t' for character in value):
        raise ValueError('Uma célula contém caracteres de controle que o Excel não representa.')
    return value


def format_sheet(sheet):
    from openpyxl.styles import Alignment
    from openpyxl.utils import get_column_letter
    widths={}
    for row in sheet:
        for cell in row:
            text=str(cell.value or '')
            longest=max((len(line) for line in text.splitlines()),default=0)
            widths[cell.column]=max(widths.get(cell.column,10),min(60,longest+2))
            cell.alignment=Alignment(vertical='top',wrap_text=True)
    for column,width in widths.items(): sheet.column_dimensions[get_column_letter(column)].width=width
    for row in sheet:
        needed=max((sum(max(1,math.ceil(len(line)/max(1,widths[cell.column]-2))) for line in str(cell.value or '').split('\n')) for cell in row),default=1)
        # Excel cannot show more than409.5pt per row. Keeping the value is
        # insufficient when a printed row silently clips most of the text.
        if needed*15>409: raise ValueError('Uma linha excede a altura legível do Excel. Exporte este conteúdo para Word ou Markdown.')
        sheet.row_dimensions[row[0].row].height=max(18,needed*15)
    sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0


def _editable_structure(data, extension):
    """Count actual editable XML objects, without evaluating formulas/macros."""
    class SafeXMLBuilder(ET.TreeBuilder):
        def doctype(self,*args):
            raise ValueError('Declarações XML externas não são aceitas na inspeção.')
    if extension=='.rtf': return dict(format='rtf',inspected=False,reason='RTF structure is not counted by this inspector.')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries=archive.infolist()
            if len(entries)>10000 or sum(entry.file_size for entry in entries)>128*1024*1024 or any(entry.file_size>32*1024*1024 for entry in entries):
                raise ValueError('O documento Office excede os limites de inspeção ZIP.')
            if len({entry.filename for entry in entries})!=len(entries): raise ValueError('O documento Office contém entradas ZIP duplicadas.')
            names=archive.namelist()
            patterns={'.docx':r'word/document\.xml', '.pptx':r'ppt/slides/slide\d+\.xml', '.xlsx':r'xl/worksheets/sheet\d+\.xml', '.odt':r'content\.xml'}
            selected=[name for name in names if re.fullmatch(patterns[extension],name)]
            if not selected: raise ValueError('A estrutura Office não corresponde ao formato selecionado.')
            counts=Counter()
            for name in selected:
                encoded=archive.read(name)
                if b'<!DOCTYPE' in encoded.upper() or b'<!ENTITY' in encoded.upper(): raise ValueError('Declarações XML externas não são aceitas na inspeção.')
                root=ET.fromstring(encoded,parser=ET.XMLParser(target=SafeXMLBuilder()))
                for element in root.iter():
                    local=element.tag.rsplit('}',1)[-1]
                    if extension=='.docx':
                        if local=='t' and element.text: counts['text_runs']+=1
                        elif local=='tbl': counts['tables']+=1
                    elif extension=='.pptx':
                        if local=='t' and element.text: counts['text_runs']+=1
                        elif local=='pic': counts['pictures']+=1
                        elif local=='sp': counts['shapes']+=1
                    elif extension=='.xlsx':
                        if local=='c' and len(element): counts['value_cells']+=1
                        elif local=='f': counts['formula_cells']+=1
                    elif extension=='.odt':
                        if local in ('p','h') and ''.join(element.itertext()).strip(): counts['paragraphs']+=1
                        elif local=='table': counts['tables']+=1
            if extension in ('.docx','.odt'): counts['embedded_images']=sum(name.startswith(('word/media/','Pictures/')) and not name.endswith('/') for name in names)
            return dict(format=extension[1:],inspected=True,parts=len(selected),counts=dict(counts))
    except (zipfile.BadZipFile,ET.ParseError,KeyError,RuntimeError):
        raise ValueError('O documento Office não contém uma estrutura válida para comparar.') from None


def _tokens(page):
    return Counter(re.findall(r'\w+',unicodedata.normalize('NFKC',page.get_text()).casefold()))


def _comparison_metrics(source, converted):
    from PIL import Image, ImageChops, ImageStat
    pages=[];source_words=Counter();converted_words=Counter();source_fonts=set();converted_fonts=set()
    for index in range(max(len(source),len(converted))):
        original=source[index] if index<len(source) else None
        result=converted[index] if index<len(converted) else None
        for page in (original,result):
            if page is not None and page.rect.width*page.rect.height*(96/72)**2>40_000_000:
                raise ValueError('Uma página excede o limite de 40 milhões de pixels do relatório visual.')
        a=_tokens(original) if original is not None else Counter();b=_tokens(result) if result is not None else Counter()
        source_words.update(a);converted_words.update(b)
        for page,fonts in ((original,source_fonts),(result,converted_fonts)):
            if page is not None:
                fonts.update(re.sub(r'^[A-Z]{6}\+','',span['font']) for block in page.get_text('dict')['blocks'] if block['type']==0 for line in block['lines'] for span in line['spans'])
        record=dict(page=index+1,source_present=original is not None,converted_present=result is not None,
            source_words=sum(a.values()),converted_words=sum(b.values()),matched_words=sum((a&b).values()))
        if original is not None and result is not None:
            record['source_size']=[original.rect.width,original.rect.height];record['converted_size']=[result.rect.width,result.rect.height]
            width=max(1,round(max(original.rect.width,result.rect.width)));height=max(1,round(max(original.rect.height,result.rect.height)))
            scale=min(1,1200/max(width,height),math.sqrt(1_000_000/(width*height)))
            size=(max(1,math.ceil(width*scale)),max(1,math.ceil(height*scale)))
            canvases=[]
            try:
                for page in (original,result):
                    pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),colorspace=fitz.csGRAY,alpha=False)
                    image=Image.frombytes('L',(pix.width,pix.height),pix.samples);del pix
                    canvas=Image.new('L',size,255);canvas.paste(image,(0,0));image.close();canvases.append(canvas)
                with ImageChops.difference(*canvases) as diff:
                    record['mean_pixel_difference']=round(ImageStat.Stat(diff).mean[0]/255,6)
            finally:
                for image in canvases: image.close()
            bounds=result.rect*result.derotation_matrix
            record['text_words_outside_page']=sum(not bounds.contains(fitz.Rect(word[:4])) for word in result.get_text('words',clip=fitz.INFINITE_RECT()))
        pages.append(record)
    overlap=sum((source_words&converted_words).values());total=sum(source_words.values())
    return dict(source_pages=len(source),converted_pages=len(converted),pages=pages,
        source_word_count=total,converted_word_count=sum(converted_words.values()),matched_word_count=overlap,
        source_word_recall=round(overlap/total,6) if total else None,
        font_name_differences=dict(only_source=sorted(source_fonts-converted_fonts),only_converted=sorted(converted_fonts-source_fonts)))


def conversion_audit(source, converted, output, options):
    """Round-trip the actual Office output, then compare its rendered PDF."""
    import pdf_engine as engine
    from ocr_page import _read_regular, _private_write
    from pdf_content import _source, _canonical
    extension=Path(converted).suffix.lower()
    if extension not in ('.docx','.xlsx','.pptx','.odt','.rtf'):
        raise ValueError('Compare um PDF original com DOCX, XLSX, PPTX, ODT ou RTF convertido.')
    data=_read_regular(converted,256*1024*1024)
    structure=_editable_structure(data,extension)
    original,source_hash=_source(source,options)
    try:
        if len(original)>500: raise ValueError('O relatório visual aceita até 500 páginas por comparação.')
        output=Path(output);output.mkdir(mode=0o700)
        roundtrip=output/'roundtrip.pdf'
        with tempfile.TemporaryDirectory(prefix='.conversion-audit-',dir=output.parent) as temporary:
            stable=Path(temporary)/('converted'+extension);_private_write(stable,data)
            settings={key:options[key] for key in ('fit_width','orientation','landscape') if key in options}
            engine.run('office',[stable],roundtrip,settings)
        with fitz.open(roundtrip) as restored:
            if len(restored)>500: raise ValueError('O documento convertido excede 500 páginas; compare uma parte menor.')
            report=dict(version=1,source_sha256=source_hash,converted_sha256=hashlib.sha256(data).hexdigest(),
                roundtrip_sha256=hashlib.sha256(roundtrip.read_bytes()).hexdigest(),editable_structure=structure,
                metrics=_comparison_metrics(original,restored),review_required=True,conformance_claim=False,
                limitations=['Office round-trip depends on LibreOffice and installed fonts.',
                    'Word overlap ignores order and is not semantic equivalence.',
                    'Pixel differences use page-aligned rendering and are not a fidelity score.',
                    'Text outside page bounds is reported; hidden frame overflow is not universally detectable.',
                    'Font-name changes can indicate substitution, but do not prove glyph or metric equivalence.',
                    'Editable object counts do not establish correct layout or accessibility.'])
            engine._visual_compare(original,restored,output/'comparison.html')
        _private_write(output/'report.json',_canonical(report))
        for path in output.iterdir(): os.chmod(path,0o600)
    finally: original.close()
