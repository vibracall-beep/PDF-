"""Measured raster table topology and bounded, reversible OCR preprocessing."""
from __future__ import annotations

import math
import statistics
import re
import fitz
from PIL import Image, ImageDraw


def _axes(lines, tolerance):
    groups=[]
    for line in sorted(lines,key=lambda item:item['at']):
        if groups and abs(line['at']-statistics.mean(item['at'] for item in groups[-1]))<=tolerance:
            groups[-1].append(line)
        else: groups.append([line])
    return [(statistics.mean(line['at'] for line in group),group) for group in groups]


def _edge(lines,start,end,tolerance):
    """Return present/absent/ambiguous; never interpret a broken rule as a merge."""
    spans=sorted((max(start,line['start']),min(end,line['end'])) for line in lines if line['end']>start and line['start']<end)
    covered=0;position=start;largest_gap=0
    for left,right in spans:
        if left>position: largest_gap=max(largest_gap,left-position)
        if right>position: covered+=right-max(position,left);position=right
    largest_gap=max(largest_gap,end-position)
    ratio=covered/max(0.001,end-start)
    if ratio>=0.92 and largest_gap<=2*tolerance: return True
    if ratio<=0.08 and covered<=2*tolerance: return False
    return None


def rectangular_grid(horizontal,vertical,tolerance):
    """Partition a strong outer frame across absent interior borders.

    Connected tiles must form rectangles with intact perimeter edges. L-shaped
    regions, partial/broken borders and overlapping aliases remain unsupported.
    """
    ys=_axes(horizontal,tolerance);xs=_axes(vertical,tolerance)
    if len(xs)<2 or len(ys)<2: return None
    rows,columns=len(ys)-1,len(xs)-1
    if rows*columns>4096: raise ValueError('A grade excede 4.096 células. Analise uma região menor.')
    if any(b[0]-a[0]<=2*tolerance for a,b in zip(xs,xs[1:])) or any(b[0]-a[0]<=2*tolerance for a,b in zip(ys,ys[1:])): return None
    h=[[_edge(lines,left[0],right[0],tolerance) for left,right in zip(xs,xs[1:])] for _,lines in ys]
    v=[[_edge(lines,top[0],bottom[0],tolerance) for _,lines in xs] for top,bottom in zip(ys,ys[1:])]
    if any(value is None for row in h+v for value in row): return None
    if not all(h[0]+h[-1]+[row[0] for row in v]+[row[-1] for row in v]): return None
    seen=set();cells=[]
    for r in range(rows):
        for c in range(columns):
            if (r,c) in seen: continue
            stack=[(r,c)];group=set()
            while stack:
                row,column=stack.pop()
                if (row,column) in group: continue
                group.add((row,column))
                if row and not h[row][column]: stack.append((row-1,column))
                if row+1<rows and not h[row+1][column]: stack.append((row+1,column))
                if column and not v[row][column]: stack.append((row,column-1))
                if column+1<columns and not v[row][column+1]: stack.append((row,column+1))
            top=min(row for row,_ in group);bottom=max(row for row,_ in group)+1
            left=min(column for _,column in group);right=max(column for _,column in group)+1
            if len(group)!=(bottom-top)*(right-left): return None
            if any(h[row][column] for row in range(top+1,bottom) for column in range(left,right)): return None
            if any(v[row][column] for row in range(top,bottom) for column in range(left+1,right)): return None
            seen.update(group)
            cells.append(dict(row=top,column=left,row_span=bottom-top,column_span=right-left,
                rect=[xs[left][0],ys[top][0],xs[right][0],ys[bottom][0]]))
    return dict(rows=rows,columns=columns,cells=cells,rect=[xs[0][0],ys[0][0],xs[-1][0],ys[-1][0]])


def _text_mask(binary):
    """Keep measured, disconnected glyph-sized components for projection.

    Long rules, filled artwork and tiny speckles cannot vote for a text angle.
    Run-length components bound memory independently from the full-resolution
    OCR raster; the caller supplies a sample of at most 1,000 pixels per side.
    """
    width,height=binary.size;data=binary.tobytes();runs=[];parents=[];previous=[]
    def root(index):
        while parents[index]!=index:
            parents[index]=parents[parents[index]];index=parents[index]
        return index
    for y in range(height):
        current=[];cursor=0
        for match in re.finditer(b'\x00+',data[y*width:(y+1)*width]):
            left,right=match.span();index=len(runs)
            if index>=100000: return None,None
            runs.append((left,right,y));parents.append(index);current.append(index)
            while cursor<len(previous) and runs[previous[cursor]][1]<left: cursor+=1
            for offset in range(cursor,len(previous)):
                prior=previous[offset]
                if runs[prior][0]>right: break
                a,b=root(index),root(prior)
                if a!=b: parents[a]=b
        previous=current
    boxes={}
    for index,(left,right,y) in enumerate(runs):
        identity=root(index)
        if identity not in boxes: boxes[identity]=[left,y,right,y+1,right-left]
        else:
            box=boxes[identity];box[0]=min(box[0],left);box[2]=max(box[2],right)
            box[3]=y+1;box[4]+=right-left
    retained={identity:box for identity,box in boxes.items()
        if 3<=box[3]-box[1]<=min(80,height*.12)
        and 1<=box[2]-box[0]<=min(100,width*.12)
        and .08<=(box[2]-box[0])/(box[3]-box[1])<=6
        and .06<=box[4]/((box[2]-box[0])*(box[3]-box[1]))<=.92}
    if len(retained)<30: return None,None
    mask=Image.new('L',binary.size,255);draw=ImageDraw.Draw(mask)
    for index,(left,right,y) in enumerate(runs):
        if root(index) in retained: draw.line((left,y,right-1,y),fill=0)
    return mask,statistics.median(box[3]-box[1] for box in retained.values())


def _text_angle(sample):
    """Require a strong interior projection maximum and several distinct lines."""
    mask,glyph_height=_text_mask(sample)
    if mask is None: return None
    def projection(angle):
        with mask.rotate(angle,Image.Resampling.NEAREST,expand=True,fillcolor=255) as rotated:
            width,height=rotated.size;data=rotated.tobytes()
            rows=[data.count(b'\x00',y*width,(y+1)*width) for y in range(height)]
            return sum(value*value for value in rows),rows
    try:
        zero,_=projection(0)
        candidates=[(projection(step/2)[0],step/2) for step in range(-14,15)]
        best,angle=max(candidates,key=lambda item:(item[0],-abs(item[1])))
        refined=[(projection(round(angle+step/10,1))[0],round(angle+step/10,1))
                 for step in range(-4,5) if abs(angle+step/10)<=7]
        best,angle=max([*refined,(best,angle)],key=lambda item:(item[0],-abs(item[1])))
        if abs(angle)<.5 or abs(angle)>=6.9 or not zero or best<zero*1.18: return None
        # Reject broad maxima (photographs/noise) and optimum at the angle cap.
        neighbours=[projection(angle+offset)[0] for offset in (-1,1)]
        if best<max(neighbours)*1.06: return None
        _,rows=projection(angle);threshold=max(12,max(rows)*.12)
        bands=[];start=None
        for index,value in enumerate([*rows,0]):
            if value>=threshold and start is None: start=index
            elif value<threshold and start is not None:
                if 2<=index-start<=glyph_height*2.2: bands.append((start,index))
                start=None
        if not 4<=len(bands)<=100: return None
        covered=sum(sum(rows[start:end]) for start,end in bands)
        if covered<sum(rows)*.6: return None
        return angle,dict(projection_gain=round(best/zero,4),text_line_bands=len(bands))
    finally: mask.close()


def deskew(image,scale,segments,components):
    """Estimate a small angle from a grid or several measured text baselines.

    Correction affects only the recognition raster, never the source pixels.
    Ambiguous, sparse, photographic and out-of-range pages stay unchanged.
    """
    original=image.size;ratio=min(1,1000/max(image.size))
    sample=image.resize((max(1,round(image.width*ratio)),max(1,round(image.height*ratio))),Image.Resampling.BILINEAR)
    sample=sample.point(lambda value:0 if value<180 else 255)
    def score(angle):
        rotated=sample.rotate(angle,Image.Resampling.NEAREST,expand=True,fillcolor=255)
        try:
            horizontal=[line for line in segments(rotated,scale*ratio) if line['end']-line['start']>=max(40,sample.width*0.15)]
            vertical=[line for line in segments(rotated,scale*ratio,vertical=True) if line['end']-line['start']>=max(40,sample.height*0.1)]
            if len(horizontal)<2 or len(vertical)<2: return 0
            if len(horizontal)*len(vertical)>250000: return 0
            tolerance=max(2,scale*ratio*1.5)
            if not any(rectangular_grid(hs,vs,tolerance) is not None for hs,vs in components(horizontal,vertical,tolerance)): return 0
            return sum((line['end']-line['start'])**2 for line in horizontal+vertical)
        finally: rotated.close()
    evidence={};status='ruling-line-evidence'
    try:
        zero=score(0);candidates=[(score(step/2),step/2) for step in range(-14,15)]
        best,angle=max(candidates,key=lambda item:(item[0],-abs(item[1])))
        refined=[(score(round(angle+step/10,1)),round(angle+step/10,1)) for step in range(-4,5) if abs(angle+step/10)<=7]
        best,angle=max([*refined,(best,angle)],key=lambda item:(item[0],-abs(item[1])))
        if not best or abs(angle)<0.5 or best<zero*1.35:
            # A measured upright frame takes precedence over differently tilted
            # text inside it. Do not rotate a valid table to follow a text inset.
            if best:
                return image,dict(applied=False,rotation_degrees=0,status='upright-or-insufficient-grid-evidence',original_size=list(original),processed_size=list(original))
            text_result=_text_angle(sample)
            if text_result is None:
                return image,dict(applied=False,rotation_degrees=0,status='upright-or-insufficient-evidence',original_size=list(original),processed_size=list(original))
            angle,evidence=text_result;status='text-line-projection-evidence'
    finally: sample.close()
    radians=math.radians(angle)
    predicted=(math.ceil(abs(image.width*math.cos(radians))+abs(image.height*math.sin(radians)))+2,
               math.ceil(abs(image.width*math.sin(radians))+abs(image.height*math.cos(radians)))+2)
    if predicted[0]*predicted[1]>40_000_000: raise ValueError('A correção de inclinação excede 40 milhões de pixels. Reduza o DPI.')
    corrected=image.rotate(angle,Image.Resampling.BICUBIC,expand=True,fillcolor=255)
    return corrected,dict(applied=True,rotation_degrees=angle,status=status,original_size=list(original),processed_size=list(corrected.size),**evidence)


def original_geometry(rect,preprocessing,scale,bounds):
    """Inverse-map all four corners; never silently clamp unrelated coordinates."""
    angle=math.radians(preprocessing['rotation_degrees']);cosine=math.cos(angle);sine=math.sin(angle)
    width,height=preprocessing['original_size'];new_width,new_height=preprocessing['processed_size']
    area=fitz.Rect(rect);quad=[]
    for point in (area.tl,area.tr,area.br,area.bl):
        x,y=point.x-new_width/2,point.y-new_height/2
        quad.append(fitz.Point((cosine*x-sine*y+width/2)/scale,(sine*x+cosine*y+height/2)/scale))
    result=fitz.Rect(min(point.x for point in quad),min(point.y for point in quad),max(point.x for point in quad),max(point.y for point in quad))
    if not (bounds+(-2,-2,2,2)).contains(result): raise ValueError('O OCR retornou conteúdo fora da página após corrigir a inclinação. Recorte a digitalização antes de continuar.')
    result &= bounds
    return [round(value,3) for value in result],[[round(point.x,3),round(point.y,3)] for point in quad]
