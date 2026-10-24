"""Conservative geometry-based reading order and table-aware extraction.

PDF geometry does not encode semantic reading order reliably. This module uses
observable whitespace to separate columns and keeps ambiguous content in a
stable visual order. It never discards an entire paragraph for intersecting a
table: only characters inside an extracted table are replaced by its cells.
"""
from __future__ import annotations

from collections import Counter
import math
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


def page_elements(page):
    tables=page.find_tables().tables
    blocks=page.get_text('rawdict',sort=False)['blocks']
    # A detected grid is not evidence that all its text was extracted. If any
    # non-whitespace source character is absent from the cells, retain ordinary
    # text for that region rather than silently dropping it during deduplication.
    verified=[]
    for table in tables:
        bounds=fitz.Rect(table.bbox)
        source=Counter(char['c'] for block in blocks if block['type']==0 for line in block['lines'] for span in line['spans'] for char in span['chars']
            if not char['c'].isspace() and bounds.contains((fitz.Rect(char['bbox']).tl+fitz.Rect(char['bbox']).br)/2))
        recovered=Counter(char for row in table.extract() for cell in row for char in str(cell or '') if not char.isspace())
        if not source-recovered: verified.append(table)
    tables=verified
    table_rects=[fitz.Rect(table.bbox) for table in tables]
    entries=[dict(type=2,bbox=tuple(table.bbox),rows=table.extract(),
        cells=[tuple(cell) if cell else None for cell in table.cells]) for table in tables]
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


def table_groups(page):
    """Tables remain separate; prose outside them remains available in Excel."""
    return page_elements(page)


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

