#!/usr/bin/env python3
"""Local PDF tools with no-clobber publication and explicit document preservation.

Coordinates are PDF points, measured from the upper-left corner of an unrotated
page. Page selectors are one-based. Every operation writes a new destination.
"""
from __future__ import annotations
import argparse
import base64
import ctypes
import difflib
import html
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import subprocess
import sys
import tempfile
import fitz

TOOLS = {
    'merge':'Juntar PDF', 'split':'Dividir PDF', 'compress':'Comprimir PDF',
    'word':'PDF para Word', 'powerpoint':'PDF para PowerPoint', 'excel':'PDF para Excel',
    'office':'Office para PDF', 'text':'Adicionar texto', 'edit':'Editar texto',
    'image':'Inserir imagem', 'shape':'Desenhar forma', 'jpg':'PDF para JPG',
    'images':'Imagens para PDF', 'signature':'Assinatura visual', 'watermark':'Marca d’água',
    'rotate':'Rodar PDF', 'html':'HTML para PDF', 'unlock':'Desbloquear PDF',
    'protect':'Proteger PDF', 'organize':'Organizar PDF', 'pdfa':'PDF para PDF/A',
    'repair':'Reparar PDF', 'numbers':'Números de página', 'ocr':'OCR PDF',
    'compare':'Comparar texto', 'compare-visual':'Comparar visualmente',
    'redact':'Remover conteúdo', 'crop':'Recortar PDF', 'forms':'Inspecionar formulários',
    'form-create':'Criar formulários', 'form-fill':'Preencher formulários', 'form-detect':'Detectar campos',
    'layout-extract':'Extrair blocos de layout', 'translate-layout':'Aplicar tradução ao layout',
    'markdown':'PDF para Markdown', 'workflow':'Executar fluxo'
}
ALIASES = {'edit_text':'edit', 'form_create':'form-create', 'form_fill':'form-fill', 'compare_visual':'compare-visual'}
PDF_OPERATIONS = {'merge','compress','office','text','edit','image','shape','images','signature','watermark','rotate','html','unlock','protect','organize','pdfa','repair','numbers','ocr','redact','crop','form-create','form-fill','translate-layout'}
MULTI_INPUT = {'merge','images','compare','compare-visual'}
DIRECTORY_OUTPUT = {'split','jpg'}


def open_pdf(path, password=''):
    doc = fitz.open(path)
    if doc.needs_pass and not doc.authenticate(password):
        doc.close()
        raise ValueError('Senha necessária ou incorreta.')
    return doc


def save(doc, output, **kwargs):
    options = dict(garbage=4, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    options.update(kwargs)
    doc.save(str(output), **options)


def number(value, name, minimum=None, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name}: informe um número válido.') from None
    if not math.isfinite(result) or (minimum is not None and result < minimum) or (maximum is not None and result > maximum):
        raise ValueError(f'{name}: valor fora do intervalo permitido.')
    return result


def color(value, default=(0.2, 0.2, 0.25)):
    if value is None:
        return default
    if isinstance(value, str):
        value = value.removeprefix('#')
        if not re.fullmatch(r'[0-9a-fA-F]{6}', value):
            raise ValueError('Cor inválida; use #RRGGBB.')
        return tuple(int(value[i:i+2],16)/255 for i in (0,2,4))
    if not isinstance(value,(list,tuple)) or len(value) != 3:
        raise ValueError('Cor inválida.')
    return tuple(number(v,'Cor',0,1) for v in value)


def parse_pages(selector, count, allow_duplicates=False):
    if selector is None or str(selector).strip() in ('','all','*'):
        return list(range(count))
    result = []
    tokens = selector if isinstance(selector,list) else str(selector).split(',')
    for token in tokens:
        value = str(token).strip()
        match = re.fullmatch(r'(\d+)(?:\s*-\s*(\d+))?',value)
        if not match:
            raise ValueError('Páginas inválidas. Use, por exemplo, 1,3-5.')
        first = int(match[1]); last = int(match[2] or first)
        for page in range(first,last+(1 if last >= first else -1),1 if last >= first else -1):
            if page < 1 or page > count:
                raise ValueError(f'Página {page} fora do documento ({count} páginas).')
            if allow_duplicates or page-1 not in result:
                result.append(page-1)
    if not result:
        raise ValueError('Selecione ao menos uma página.')
    return result


def _page_bounds(page):
    return page.rect * page.derotation_matrix


def rectangle(options, page, default=None):
    bounds = _page_bounds(page)
    if 'rect' in options:
        values = options['rect']
        if not isinstance(values,(list,tuple)) or len(values) != 4:
            raise ValueError('rect deve conter [x0,y0,x1,y1].')
        rect = fitz.Rect([number(v,'Coordenada') for v in values])
    elif any(key in options for key in ('x','y','width','height')):
        x = number(options.get('x',36),'x'); y = number(options.get('y',72),'y')
        rect = fitz.Rect(x,y,x+number(options.get('width',200),'Largura',1),y+number(options.get('height',80),'Altura',1))
    else:
        rect = fitz.Rect(default or [36,72,min(236,bounds.width-36),min(152,bounds.height-36)])
    if rect.is_empty or rect.is_infinite or not bounds.contains(rect):
        raise ValueError('A área deve estar inteiramente dentro da página e ter tamanho positivo.')
    return rect


def _encrypted_output(doc, password):
    # New documents cannot use ENCRYPT_KEEP because they have no source crypt dict.
    if doc.metadata.get('encryption'):
        if not password:
            raise ValueError('Informe a senha para preservar a proteção da cópia.')
        return dict(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password,
                    owner_pw=secrets.token_urlsafe(24), permissions=doc.permissions)
    return {}


def _publish(payload, output):
    """Publish complete output without ever replacing a concurrently created path."""
    if payload.is_file():
        os.link(payload, output)  # atomic EEXIST on destination, including symlinks
        payload.unlink()
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint]
        status = rename(os.fsencode(payload),os.fsencode(output),4)  # RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(libc,'renameat2'):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        status = rename(-100,os.fsencode(payload),-100,os.fsencode(output),1)  # RENAME_NOREPLACE
    else:
        raise RuntimeError('Publicação atômica de diretórios exige macOS ou Linux compatível.')
    if status:
        error = ctypes.get_errno()
        raise OSError(error,os.strerror(error),str(output))


def _external(command, timeout=180):
    """Own a separate process group so cancel never leaves converters running."""
    try:
        process = subprocess.Popen([str(v) for v in command],stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,text=True,start_new_session=True)
    except FileNotFoundError:
        raise RuntimeError(f'Dependência indisponível: {command[0]}. Execute o instalador completo.') from None
    try:
        stdout,stderr = process.communicate(timeout=timeout)
    except BaseException:
        try: os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        try: process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            process.communicate()
        raise
    result = subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
    if result.returncode:
        message = (result.stderr or result.stdout).strip()[-2500:]
        raise RuntimeError(f'{Path(command[0]).name} falhou ({result.returncode}): {message}')
    return result


def run(operation, inputs, output, options=None):
    options = options or {}
    if not isinstance(options,dict):
        raise ValueError('As opções devem ser um objeto JSON.')
    operation = ALIASES.get(operation,operation)
    if operation == 'compare' and options.get('mode') == 'visual': operation = 'compare-visual'
    if operation not in TOOLS: raise ValueError('Operação desconhecida: '+str(operation))
    inputs = [str(path) for path in inputs]
    if not inputs: raise ValueError('Selecione ao menos um arquivo.')
    if operation not in MULTI_INPUT | {'workflow'} and len(inputs) != 1:
        raise ValueError('Esta operação aceita um arquivo por vez.')
    if operation in ('compare','compare-visual') and len(inputs) != 2:
        raise ValueError('Selecione dois PDFs para comparar.')
    requested = Path(output).expanduser().absolute()
    output = requested.parent.resolve() / requested.name
    if os.path.lexists(output) or any(output.resolve() == Path(p).expanduser().resolve() for p in inputs if not p.startswith(('https://','http://'))):
        raise ValueError('O destino já existe. Escolha um novo nome para preservar os arquivos.')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pdf-output-',dir=output.parent) as temporary:
        payload = Path(temporary)/output.name
        _execute(operation,inputs,payload,options)
        if not payload.exists(): raise RuntimeError('A operação não produziu o arquivo esperado.')
        if payload.is_file():
            with payload.open('rb') as handle: os.fsync(handle.fileno())
        try: _publish(payload,output)
        except FileExistsError:
            raise ValueError('Outro processo criou o destino. Nenhum arquivo foi substituído.') from None
    return str(output)


def _execute(operation, inputs, output, options):
    password = options.get('password','')
    if operation == 'workflow':
        steps = options.get('steps',[])
        if not isinstance(steps,list) or not 1 <= len(steps) <= 64:
            raise ValueError('O fluxo precisa de 1 a 64 etapas.')
        for i, step in enumerate(steps):
            if not isinstance(step,dict) or step.get('operation') not in TOOLS or step['operation'] == 'workflow':
                raise ValueError(f'Etapa {i+1} inválida; fluxos recursivos não são permitidos.')
            if i < len(steps)-1 and step['operation'] not in PDF_OPERATIONS:
                raise ValueError('Etapas intermediárias precisam produzir um PDF único.')
            if i > 0 and step['operation'] in ('merge','images','compare','compare-visual'):
                raise ValueError('Esta operação só pode ser a primeira etapa do fluxo.')
        with tempfile.TemporaryDirectory() as tmp:
            current = inputs
            for i,step in enumerate(steps):
                target = output if i == len(steps)-1 else Path(tmp)/f'{i}.pdf'
                step_options = dict(step.get('options') or {})
                if password and 'password' not in step_options: step_options['password'] = password
                run(step['operation'],current,target,step_options)
                if step['operation'] == 'protect': password = step_options.get('new_password','')
                if step['operation'] == 'unlock': password = ''
                current = [str(target)]
        return
    if operation == 'office':
        executable = shutil.which('soffice') or '/Applications/LibreOffice.app/Contents/MacOS/soffice'
        with tempfile.TemporaryDirectory() as tmp:
            source = inputs[0]
            if Path(source).suffix.lower() == '.xlsx' and (options.get('fit_width') or options.get('landscape') or options.get('orientation')):
                from openpyxl import load_workbook
                book = load_workbook(source)
                for sheet in book:
                    sheet.page_setup.orientation = 'landscape' if options.get('landscape') or options.get('orientation') == 'landscape' else 'portrait'
                    if options.get('fit_width'):
                        sheet.sheet_properties.pageSetUpPr.fitToPage = True
                        sheet.page_setup.fitToWidth = 1; sheet.page_setup.fitToHeight = 0
                source = str(Path(tmp)/'input.xlsx'); book.save(source); book.close()
            _external([executable,'-env:UserInstallation='+(Path(tmp)/'profile').as_uri(),'--headless','--convert-to','pdf','--outdir',tmp,source])
            generated = Path(tmp)/(Path(source).stem+'.pdf')
            if not generated.exists(): raise RuntimeError('LibreOffice não produziu um PDF.')
            with fitz.open(generated) as doc:
                if len(doc) == 0: raise RuntimeError('LibreOffice produziu um documento vazio.')
            shutil.copyfile(generated,output)
        return
    if operation in ('ocr','pdfa'):
        with open_pdf(inputs[0],password) as doc, tempfile.TemporaryDirectory() as tmp:
            protection = _encrypted_output(doc,password)
            if protection and operation == 'pdfa':
                raise ValueError('PDF/A não permite criptografia. Desbloqueie uma cópia explicitamente antes de converter.')
            source = inputs[0]
            if protection:
                source = str(Path(tmp)/'source.pdf'); save(doc,source,encryption=fitz.PDF_ENCRYPT_NONE)
            generated = Path(tmp)/'result.pdf'
            _external(['ocrmypdf','--output-type','pdfa' if operation == 'pdfa' else 'pdf','--skip-text','--language',options.get('language','por+eng'),source,generated],timeout=1800)
            with open_pdf(generated) as result:
                if protection: save(result,output,**protection)
                else: shutil.copyfile(generated,output)
        return
    if operation == 'html':
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.getenv('PDF_CHROMIUM_EXECUTABLE') or None)
            try:
                page = browser.new_page()
                if inputs[0].startswith(('https://','http://')):
                    page.goto(inputs[0],wait_until='networkidle',timeout=60000)
                else:
                    page.set_content(Path(inputs[0]).read_text(encoding='utf-8'),wait_until='networkidle',timeout=60000)
                page.pdf(path=str(output),format=options.get('paper','A4'),print_background=True,landscape=bool(options.get('landscape',False)))
            finally: browser.close()
        return
    if operation in ('merge','images'):
        protection = {}
        with fitz.open() as result:
            for path in inputs:
                with open_pdf(path,password) as source:
                    source_protection = _encrypted_output(source,password) if source.is_pdf else {}
                    if source_protection:
                        if protection: source_protection['permissions'] &= protection['permissions']
                        protection = source_protection
                    if operation == 'images':
                        with fitz.open('pdf',source.convert_to_pdf()) as converted:
                            for i in range(len(converted)):
                                if any(k in options for k in ('paper','margin','landscape','orientation')):
                                    width,height = fitz.paper_size(options.get('paper','a4'))
                                    if width <= 0 or height <= 0: raise ValueError('Papel desconhecido.')
                                    if options.get('landscape') or options.get('orientation') == 'landscape': width,height = height,width
                                    page = result.new_page(width=width,height=height)
                                    margin = number(options.get('margin',20),'Margem',0,min(width,height)/3)
                                    page.show_pdf_page(page.rect+(margin,margin,-margin,-margin),converted,i)
                                else: result.insert_pdf(converted,from_page=i,to_page=i)
                    else: result.insert_pdf(source)
            if not len(result): raise ValueError('Nenhuma página encontrada.')
            save(result,output,**protection)
        return
    with open_pdf(inputs[0],password) as doc:
        if not doc.is_pdf or not len(doc): raise ValueError('Selecione um PDF com ao menos uma página.')
        pages = parse_pages(options.get('pages'),len(doc),allow_duplicates=operation=='organize')
        if operation == 'split':
            output.mkdir()
            groups = options.get('groups')
            selected_groups = [parse_pages(group,len(doc)) for group in groups] if groups else [[p] for p in pages]
            for i, group in enumerate(selected_groups):
                with fitz.open() as part:
                    for p in group: part.insert_pdf(doc,from_page=p,to_page=p)
                    save(part,output/f'parte-{i+1:04}.pdf',**_encrypted_output(doc,password))
        elif operation == 'jpg':
            output.mkdir(); dpi = int(number(options.get('dpi',150),'DPI',36,600))
            if options.get('mode') == 'embedded':
                from PIL import Image
                seen = set(); count = 0
                for i in pages:
                    for item in doc[i].get_images(full=True):
                        if item[0] in seen: continue
                        seen.add(item[0]); data = doc.extract_image(item[0])
                        with Image.open(io.BytesIO(data['image'])) as image:
                            count += 1; image.convert('RGB').save(output/f'imagem-{count:04}.jpg',quality=95)
                if count == 0: raise ValueError('Nenhuma imagem incorporada foi encontrada.')
            else:
                for i in pages: doc[i].get_pixmap(dpi=dpi,alpha=False).save(str(output/f'pagina-{i+1:04}.jpg'))
        elif operation == 'layout-extract':
            output.write_text(json.dumps(_layout(doc,pages),ensure_ascii=False,indent=2),encoding='utf-8')
        elif operation == 'translate-layout':
            _translate_layout(doc,options); save(doc,output)
        elif operation == 'form-detect':
            output.write_text(json.dumps(dict(heuristic=True,review_required=True,fields=_detect_forms(doc,pages)),ensure_ascii=False,indent=2),encoding='utf-8')
        elif operation == 'forms':
            content = [dict(page=i+1,name=w.field_name,value=w.field_value,type=w.field_type_string,rect=list(w.rect),choices=w.choice_values) for i in pages for w in (doc[i].widgets() or [])]
            output.write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding='utf-8')
        elif operation == 'markdown':
            output.write_text(_markdown(doc,pages),encoding='utf-8')
        elif operation in ('compare','compare-visual'):
            with open_pdf(inputs[1],options.get('second_password',password)) as other:
                if operation == 'compare-visual': _visual_compare(doc,other,output)
                else:
                    first = ''.join(p.get_text() for p in doc).splitlines(True)
                    second = ''.join(p.get_text() for p in other).splitlines(True)
                    diff = ''.join(difflib.unified_diff(first,second,fromfile=Path(inputs[0]).name,tofile=Path(inputs[1]).name))
                    output.write_text(diff or 'Nenhuma diferença textual. Imagens e layout não foram comparados.\n',encoding='utf-8')
        elif operation == 'word': _word(doc,pages,output)
        elif operation == 'powerpoint': _powerpoint(doc,pages,output,options)
        elif operation == 'excel': _excel(doc,pages,output)
        elif operation == 'organize':
            if not options.get('pages'): raise ValueError('Informe a nova ordem das páginas.')
            doc.select(pages); save(doc,output)
        elif operation == 'form-create':
            _create_forms(doc,options); save(doc,output)
        elif operation == 'form-fill':
            _fill_forms(doc,options); save(doc,output)
        elif operation in PDF_OPERATIONS:
            _modify(doc,pages,operation,options)
            kwargs = {}
            if operation == 'protect':
                secret = options.get('new_password','')
                if not isinstance(secret,str) or not 8 <= len(secret) <= 40: raise ValueError('Use uma senha de 8 a 40 caracteres.')
                kwargs = dict(encryption=fitz.PDF_ENCRYPT_AES_256,owner_pw=secrets.token_urlsafe(24),user_pw=secret)
            elif operation == 'unlock': kwargs['encryption'] = fitz.PDF_ENCRYPT_NONE
            save(doc,output,**kwargs)
        else: raise ValueError('Operação não implementada: '+operation)


def _font(options):
    font_file = options.get('font_file')
    if font_file:
        path = Path(font_file)
        if not path.is_file(): raise ValueError('Arquivo de fonte não encontrado.')
        return 'customfont',str(path)
    font = options.get('font','helv')
    if font not in ('helv','hebo','heit','hebi','tiro','tibo','tiit','tibi','cour','cobo','coit','cobi'):
        raise ValueError('Fonte desconhecida. Escolha Helvetica, Times, Courier ou font_file.')
    return font,None


def _text(page,text,options,operation):
    bounds = _page_bounds(page)
    fontsize = number(options.get('font_size',14),'Tamanho da fonte',4,300)
    opacity = number(options.get('opacity',0.5 if operation=='watermark' else 1),'Opacidade',0,1)
    ink = color(options.get('color'))
    font,fontfile = _font(options)
    margin = number(options.get('margin',36),'Margem',0,min(bounds.width,bounds.height)/2)
    if 'rect' in options or 'width' in options or 'height' in options:
        rect = rectangle(options,page)
        remaining = page.insert_textbox(rect,text,fontname=font,fontfile=fontfile,fontsize=fontsize,color=ink,fill_opacity=opacity,align=int(number(options.get('align',0),'Alinhamento',0,3)))
        if remaining < 0: raise ValueError('O texto não cabe na área escolhida. Aumente a área ou diminua a fonte.')
    else:
        measure = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font(fontname=font)
        width = max((measure.text_length(line,fontsize=fontsize) for line in text.splitlines()),default=0)
        position = options.get('position','bottom-left' if operation=='numbers' else 'top-left')
        if position not in ('top-left','top-center','top-right','center','bottom-left','bottom-center','bottom-right'):
            raise ValueError('Posição desconhecida.')
        x = margin if position.endswith('left') else (bounds.width-width)/2 if position.endswith('center') or position=='center' else bounds.width-margin-width
        y = bounds.height-margin if position.startswith('bottom') else bounds.height/2 if position=='center' else margin+fontsize
        x = number(options.get('x',x),'x'); y = number(options.get('y',y),'y')
        if x < 0 or y-fontsize < 0 or x+width > bounds.width or y > bounds.height:
            raise ValueError('O texto não cabe na página. Ajuste posição ou tamanho.')
        page.insert_text((x,y),text,fontname=font,fontfile=fontfile,fontsize=fontsize,color=ink,fill_opacity=opacity)


def _modify(doc,pages,operation,options):
    if operation == 'compress' and options.get('image_dpi'):
        # Recompress embedded images while preserving vectors, searchable text and widgets.
        from PIL import Image
        dpi = number(options['image_dpi'],'DPI',36,600)
        quality = int(number(options.get('quality',80),'Qualidade JPEG',20,95))
        visited = set()
        for page in doc:
            for item in page.get_images(full=True):
                xref = item[0]
                if xref in visited or item[1]: continue  # preserve alpha masks
                visited.add(xref)
                rects = page.get_image_rects(xref)
                if not rects: continue
                target_w = max(1,int(max(r.width for r in rects)*dpi/72))
                target_h = max(1,int(max(r.height for r in rects)*dpi/72))
                try:
                    source = doc.extract_image(xref)
                    with Image.open(io.BytesIO(source['image'])) as image:
                        if image.width <= target_w and image.height <= target_h: continue
                        image.thumbnail((target_w,target_h))
                        buffer = io.BytesIO(); image.convert('RGB').save(buffer,format='JPEG',quality=quality,optimize=True)
                        page.replace_image(xref,stream=buffer.getvalue())
                except (OSError,ValueError): continue
    matches = 0
    for i in pages:
        page = doc[i]
        if operation == 'rotate':
            degrees = number(options.get('degrees',90),'Rotação')
            if degrees % 90: raise ValueError('A rotação deve ser múltipla de 90 graus.')
            page.set_rotation((page.rotation+int(degrees))%360)
        elif operation in ('text','watermark','numbers'):
            if operation == 'watermark' and options.get('image'):
                _insert_image(page,options,watermark=True)
            else:
                value = options.get('text','PDF')
                if operation == 'numbers':
                    start = int(number(options.get('start',1),'Número inicial',0))
                    value = options.get('format','{n}').replace('{n}',str(start+pages.index(i))).replace('{total}',str(len(pages)))
                _text(page,str(value),options,operation)
        elif operation in ('image','signature'): _insert_image(page,options)
        elif operation == 'shape':
            rect = rectangle(options,page)
            drawing = page.new_shape(); kind = options.get('shape','rectangle')
            if kind == 'rectangle': drawing.draw_rect(rect)
            elif kind == 'ellipse': drawing.draw_oval(rect)
            elif kind == 'line': drawing.draw_line(rect.tl,rect.br)
            else: raise ValueError('Escolha rectangle, ellipse ou line.')
            drawing.finish(color=color(options.get('color')),fill=color(options['fill']) if options.get('fill') else None,width=number(options.get('line_width',1),'Espessura',0.1,50),fill_opacity=number(options.get('opacity',1),'Opacidade',0,1),stroke_opacity=number(options.get('opacity',1),'Opacidade',0,1))
            drawing.commit()
        elif operation in ('redact','edit'):
            term = options.get('search',options.get('text',''))
            rects = [rectangle({'rect':r},page) for r in options.get('rects',[])] if operation=='redact' and options.get('rects') else page.search_for(term) if term else []
            if not term and not rects: raise ValueError('Informe o texto ou as áreas a remover.')
            replacement = options.get('replacement','')
            font,_ = _font(options)
            if operation=='edit' and options.get('font_file'): raise ValueError('Substituição direta usa fontes PDF padrão; use sobreposição para fontes externas.')
            for rect in rects:
                matches += 1
                page.add_redact_annot(rect,fill=color(options.get('fill'),(1,1,1) if operation=='edit' else (0,0,0)))
            if rects:
                if operation=='edit': page.apply_redactions(images=0,graphics=0,text=0)
                else: page.apply_redactions()
            if operation=='edit' and replacement:
                for rect in rects:
                    size=number(options.get('font_size',11),'Fonte',4,300)
                    minimum=number(options.get('min_font_size',min(8,size)),'Fonte mínima',4,size)
                    fitted=False
                    while size >= minimum:
                        spare=page.insert_textbox(rect,str(replacement),fontname=font,fontsize=size,color=color(options.get('color')))
                        if spare>=0: fitted=True; break
                        size-=0.5
                    if not fitted: raise ValueError('O texto substituto não cabe na área original. Reduza o texto ou ajuste a fonte mínima; nenhuma cópia foi criada.')
        elif operation == 'crop':
            margin = number(options.get('margin',20),'Margem',0)
            rect = rectangle(options,page) if 'rect' in options else page.cropbox+(margin,margin,-margin,-margin)
            if rect.is_empty: raise ValueError('Margem inválida.')
            page.set_cropbox(rect)
    if operation in ('redact','edit') and matches == 0:
        raise ValueError('Nenhuma ocorrência encontrada. Nenhuma cópia foi criada.')
    if operation == 'redact':
        # Purge metadata, embedded attachments and XML metadata along with removed streams.
        doc.set_metadata({})
        doc.del_xml_metadata()
        for name in list(doc.embfile_names()): doc.embfile_del(name)


def _insert_image(page,options,watermark=False):
    image = options.get('image')
    if not image or not Path(image).is_file(): raise ValueError('Selecione uma imagem válida.')
    rect = rectangle(options,page)
    opacity = number(options.get('opacity',0.35 if watermark else 1),'Opacidade',0,1)
    if opacity < 1:
        from PIL import Image
        with Image.open(image) as source:
            rgba = source.convert('RGBA'); rgba.putalpha(rgba.getchannel('A').point(lambda a:int(a*opacity)))
            buffer = io.BytesIO(); rgba.save(buffer,format='PNG')
            page.insert_image(rect,stream=buffer.getvalue(),keep_proportion=True,overlay=bool(options.get('overlay',True)))
    else: page.insert_image(rect,filename=image,keep_proportion=True,overlay=bool(options.get('overlay',True)))


def _layout(doc,pages):
    blocks=[]
    for i in pages:
        for j,block in enumerate(doc[i].get_text('dict',sort=True)['blocks']):
            if block['type']!=0: continue
            text='\n'.join(''.join(span['text'] for span in line['spans']) for line in block['lines']).strip()
            if not text: continue
            spans=[span for line in block['lines'] for span in line['spans'] if span['text'].strip()]
            if not spans: continue
            ink=spans[0].get('color',0)
            blocks.append(dict(id=f'p{i+1}-b{j}',page=i+1,rect=list(block['bbox']),text=text,font_size=max(span['size'] for span in spans),color=f'#{ink:06x}'))
    return blocks


def _translate_layout(doc,options):
    edits=options.get('edits',[])
    if not isinstance(edits,list) or not edits: raise ValueError('Informe os blocos traduzidos.')
    grouped={}
    for edit in edits:
        page_number=int(number(edit.get('page',1),'Página',1,len(doc)))-1
        page=doc[page_number]; rect=rectangle(edit,page)
        text=str(edit.get('text',''))
        if not text.strip(): raise ValueError('O texto traduzido não pode estar vazio.')
        if edit.get('source_text') and page.get_textbox(rect).strip()!=edit['source_text'].strip():
            raise ValueError('O bloco original mudou. Extraia o layout novamente.')
        if any((rect & previous[1]).get_area() > 0.5 for previous in grouped.get(page_number,[])):
            raise ValueError('Blocos de tradução sobrepostos. Selecione blocos sem sobreposição.')
        grouped.setdefault(page_number,[]).append((edit,rect,text))
    for index,items in grouped.items():
        page=doc[index]
        for edit,rect,text in items: page.add_redact_annot(rect,fill=False)
        page.apply_redactions(images=0,graphics=0,text=0)
        for edit,rect,text in items:
            size=number(edit.get('font_size',11),'Fonte',4,300)
            minimum=number(edit.get('min_font_size',options.get('min_font_size',min(8,size))),'Fonte mínima',4,size)
            ink=color(edit.get('color'),(0,0,0)); css_color='#'+''.join(f'{round(v*255):02x}' for v in ink)
            content='<div>'+html.escape(text).replace('\n','<br>')+'</div>'
            spare,scale=page.insert_htmlbox(rect,content,css=f'* {{font-family: sans-serif;font-size:{size}pt;color:{css_color};margin:0;padding:0;line-height:1.0}}',scale_low=minimum/size)
            if spare < 0: raise ValueError(f'A tradução não cabe no bloco da página {index+1}. Reduza o texto ou o tamanho mínimo da fonte.')


def _detect_forms(doc,pages):
    """Suggest vector boxes/blank lines for human review, never claim OCR inference."""
    fields=[]
    for i in pages:
        page=doc[i]; rectangles=[]
        for drawing in page.get_drawings():
            for item in drawing['items']:
                if item[0]=='re':
                    rect=fitz.Rect(item[1])
                    if 8<=rect.width<=400 and 8<=rect.height<=100: rectangles.append(rect)
                elif item[0]=='l':
                    start,end=item[1:3]
                    if abs(start.y-end.y)<1 and abs(start.x-end.x)>=35:
                        rectangles.append(fitz.Rect(min(start.x,end.x),max(0,start.y-18),max(start.x,end.x),start.y+2))
        seen=[]
        for rect in rectangles:
            if not page.rect.contains(rect) or any((rect & previous).get_area()>rect.get_area()*0.8 for previous in seen): continue
            # Occupied cells are labels/content, not blank input fields.
            if page.get_textbox(rect).strip(): continue
            seen.append(rect)
            kind='checkbox' if rect.width<=24 and rect.height<=24 else 'text'
            label=page.get_textbox(fitz.Rect(max(0,rect.x0-180),max(0,rect.y0-20),rect.x1,rect.y0)).strip()
            fields.append(dict(name=f'campo_{i+1}_{len(seen)}',page=i+1,type=kind,rect=list(rect),label=label[-120:],confidence='heuristic'))
    return fields


def _create_forms(doc,options):
    fields = options.get('fields',[])
    if not isinstance(fields,list) or not fields: raise ValueError('Defina ao menos um campo.')
    names = {w.field_name for p in doc for w in (p.widgets() or [])}
    types = {'text':fitz.PDF_WIDGET_TYPE_TEXT,'checkbox':fitz.PDF_WIDGET_TYPE_CHECKBOX,'choice':fitz.PDF_WIDGET_TYPE_COMBOBOX,'list':fitz.PDF_WIDGET_TYPE_LISTBOX}
    for field in fields:
        name = str(field.get('name','')).strip()
        if not name or name in names: raise ValueError('Os campos precisam de nomes únicos e não vazios.')
        names.add(name)
        index = int(number(field.get('page',1),'Página',1,len(doc)))-1
        page = doc[index]
        kind = field.get('type','text')
        if kind not in types: raise ValueError('Tipo de campo inválido.')
        widget = fitz.Widget(); widget.field_name = name; widget.field_type = types[kind]
        widget.rect = rectangle(field,page); widget.text_fontsize = number(field.get('font_size',12),'Fonte',4,100)
        widget.text_color = color(field.get('color'),(0,0,0)); widget.border_color = color(field.get('border_color'),(.5,.5,.5)); widget.border_width = 1
        if kind in ('choice','list'):
            choices = field.get('choices',field.get('options',[]))
            if not choices: raise ValueError('Defina as opções do campo de escolha.')
            widget.choice_values = [str(v) for v in choices]
        value = field.get('value','')
        widget.field_value = ('Yes' if value else 'Off') if kind=='checkbox' else str(value)
        if field.get('multiline') and kind=='text': widget.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
        page.add_widget(widget)


def _fill_forms(doc,options):
    values = options.get('values',{})
    if not isinstance(values,dict) or not values: raise ValueError('Informe os valores dos campos.')
    existing = {w.field_name for page in doc for w in (page.widgets() or [])}
    missing = set(values)-existing
    if missing: raise ValueError('Campos inexistentes: '+', '.join(sorted(missing)))
    for page in doc:
        for widget in page.widgets() or []:
            if widget.field_name not in values: continue
            value = values[widget.field_name]
            if widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                widget.field_value = widget.on_state() if bool(value) else 'Off'
            elif widget.field_type in (fitz.PDF_WIDGET_TYPE_LISTBOX,fitz.PDF_WIDGET_TYPE_COMBOBOX):
                if str(value) not in (widget.choice_values or []): raise ValueError('Escolha inválida para '+widget.field_name)
                widget.field_value = str(value)
            else: widget.field_value = str(value)
            widget.update()


def _page_elements(page):
    """Reading-order blocks and extracted tables, avoiding duplicated table text."""
    tables = page.find_tables().tables
    entries = [dict(type=2,bbox=table.bbox,rows=table.extract()) for table in tables]
    for block in page.get_text('dict',sort=True)['blocks']:
        bounds = fitz.Rect(block['bbox'])
        if block['type']==0 and any((bounds & fitz.Rect(table.bbox)).get_area() > bounds.get_area()*0.65 for table in tables):
            continue
        entries.append(block)
    return sorted(entries,key=lambda b:(round(b['bbox'][1]/8),b['bbox'][0]))


def _markdown(doc,pages):
    chunks = []
    def escaped(value):
        return str(value or '').replace('\\','\\\\').replace('<','&lt;').replace('>','&gt;')
    for i in pages:
        page = doc[i]; elements = _page_elements(page)
        sizes = [s['size'] for b in elements if b['type']==0 for line in b['lines'] for s in line['spans'] if s['text'].strip()]
        body = sorted(sizes)[len(sizes)//2] if sizes else 11
        chunks.append(f'<!-- Página {i+1} -->')
        for block in elements:
            if block['type']==2:
                rows = block['rows']
                if not rows: continue
                width = max(map(len,rows))
                for n,row in enumerate(rows):
                    chunks.append('| '+' | '.join(escaped(value).replace('|','\\|').replace('\n','<br>') for value in [*row,*['']*(width-len(row))])+' |')
                    if n==0: chunks.append('| '+' | '.join(['---']*width)+' |')
                chunks.append('')
                continue
            if block['type']!=0:
                # Inline image data keeps Markdown export self-contained.
                encoded = base64.b64encode(block['image']).decode()
                chunks.append(f'![Imagem da página {i+1}](data:image/{block.get("ext","png")};base64,{encoded})')
                continue
            for line in block['lines']:
                text = ''.join(s['text'] for s in line['spans']).strip()
                if not text: continue
                size = max(s['size'] for s in line['spans'])
                prefix = '# ' if size >= body*1.7 else '## ' if size >= body*1.3 else ''
                chunks.append(prefix+escaped(text))
            chunks.append('')
        for link in page.get_links():
            if link.get('uri'):
                uri = str(link['uri'])
                if uri.startswith(('https://','http://','mailto:')):
                    label = escaped(page.get_textbox(link['from']).strip() or 'Link').replace('[','\\[').replace(']','\\]')
                    chunks.append(f'[{label}]({uri.replace("(","%28").replace(")","%29")})')
    return '\n'.join(chunks)


def _word(doc,pages,output):
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    result = Document()
    for count,i in enumerate(pages):
        page = doc[i]
        if count: result.add_page_break()
        for block in _page_elements(page):
            if block['type']==2:
                rows=block['rows']
                if rows:
                    table=result.add_table(rows=len(rows),cols=max(map(len,rows)))
                    table.style='Table Grid'
                    for r,row in enumerate(rows):
                        for c,value in enumerate(row): table.cell(r,c).text=str(value or '')
                continue
            if block['type']==1:
                try: result.add_picture(io.BytesIO(block['image']),width=Inches(min(6,(block['bbox'][2]-block['bbox'][0])/72)))
                except (ValueError,TypeError): pass
                continue
            paragraph=result.add_paragraph()
            for j,line in enumerate(block['lines']):
                if j: paragraph.add_run('\n')
                for span in line['spans']:
                    run=paragraph.add_run(span['text']); run.font.size=Pt(span['size'])
                    run.bold=bool(span['flags']&16); run.italic=bool(span['flags']&2)
                    ink=span.get('color',0); run.font.color.rgb=RGBColor((ink>>16)&255,(ink>>8)&255,ink&255)
    result.save(output)


def _powerpoint(doc,pages,output,options):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    result = Presentation(); result.slide_width = Inches(10)
    result.slide_height = Inches(min(20,max(1,10*doc[pages[0]].rect.height/doc[pages[0]].rect.width)))
    mode = options.get('mode','editable')
    if mode not in ('editable','image'): raise ValueError('Modo inválido: editable ou image.')
    for i in pages:
        page = doc[i]; slide = result.slides.add_slide(result.slide_layouts[6])
        sx = result.slide_width/page.rect.width; sy = result.slide_height/page.rect.height
        if mode == 'image':
            slide.shapes.add_picture(io.BytesIO(page.get_pixmap(dpi=150).tobytes('png')),0,0,width=result.slide_width,height=result.slide_height)
            continue
        for block in page.get_text('dict')['blocks']:
            x0,y0,x1,y1 = block['bbox']
            if block['type']==1:
                slide.shapes.add_picture(io.BytesIO(block['image']),int(x0*sx),int(y0*sy),width=max(1,int((x1-x0)*sx)),height=max(1,int((y1-y0)*sy)))
            else:
                box = slide.shapes.add_textbox(int(x0*sx),int(y0*sy),max(1,int((x1-x0)*sx)),max(1,int((y1-y0)*sy)))
                frame = box.text_frame; frame.word_wrap=False
                frame.margin_left=frame.margin_right=frame.margin_top=frame.margin_bottom=0
                for n,line in enumerate(block['lines']):
                    paragraph = frame.paragraphs[0] if n==0 else frame.add_paragraph()
                    for span in line['spans']:
                        run = paragraph.add_run(); run.text=span['text']; run.font.size=Pt(span['size']*sx/12700)
                        run.font.bold=bool(span['flags']&16); run.font.italic=bool(span['flags']&2)
                        ink=span.get('color',0); run.font.color.rgb=RGBColor((ink>>16)&255,(ink>>8)&255,ink&255)
    result.save(output)


def _excel(doc,pages,output):
    from openpyxl import Workbook
    result = Workbook(); result.remove(result.active)
    for i in pages:
        page = doc[i]; sheet = result.create_sheet(f'Página {i+1}'); sheet.freeze_panes='A2'
        tables = page.find_tables().tables
        rows = [row for table in tables for row in table.extract()] if tables else [[line] for line in page.get_text(sort=True).splitlines()]
        for row in rows:
            sheet.append(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in row])
    result.save(output)


def _visual_compare(first,second,output):
    from PIL import Image, ImageChops, ImageEnhance
    rows=[]
    for i in range(max(len(first),len(second))):
        images=[]
        for document in (first,second):
            if i < len(document):
                pix=document[i].get_pixmap(dpi=96,alpha=False)
                images.append(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
            else: images.append(Image.new('RGB',(1,1),'white'))
        size=(max(im.width for im in images),max(im.height for im in images))
        canvases=[]
        for im in images:
            canvas=Image.new('RGB',size,'white'); canvas.paste(im,(0,0)); canvases.append(canvas)
        diff=ImageChops.difference(*canvases); changed=diff.getbbox() is not None
        previews=[]
        for im in [*canvases,ImageEnhance.Contrast(diff).enhance(3)]:
            data=io.BytesIO(); im.save(data,format='PNG'); previews.append('data:image/png;base64,'+base64.b64encode(data.getvalue()).decode())
        rows.append(f'<section><h2>Página {i+1}: {"alterada" if changed else "igual"}</h2><div class="row">'+''.join(f'<figure><img alt="{label}" src="{source}"><figcaption>{label}</figcaption></figure>' for label,source in zip(('Original','Comparação','Diferenças'),previews))+'</div></section>')
    output.write_text('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Comparação PDF</title><style>body{font-family:system-ui;margin:24px;background:#f4f5fa;color:#202533}.row{display:flex;gap:16px}figure{margin:0;width:33%}img{width:100%;border:1px solid #ccd}section{margin-bottom:32px}figcaption{padding:8px}</style><h1>Comparação visual de PDFs</h1><p>Renderização a 96 DPI. Diferenças pequenas devem ser revisadas no documento original.</p>'+''.join(rows)+'</html>',encoding='utf-8')


def capabilities():
    office=shutil.which('soffice') or ('/Applications/LibreOffice.app/Contents/MacOS/soffice' if Path('/Applications/LibreOffice.app/Contents/MacOS/soffice').exists() else None)
    return dict(version='0.2.0',operations=list(TOOLS),dependencies=dict(office=bool(office),ocr=bool(shutil.which('ocrmypdf')),tesseract=bool(shutil.which('tesseract')),html=importlib.util.find_spec('playwright') is not None),features=dict(atomic_outputs=True,preserves_pdf_encryption=True,editable_powerpoint=True),limitations=['Layout reconstruction is approximate.','Visual signatures are not cryptographic signatures.','PDF/A requires independent conformance validation.'])


def _cancel_signal(signum, frame):
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGTERM,_cancel_signal)
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',nargs='?',choices=[*TOOLS,*ALIASES])
    parser.add_argument('inputs',nargs='*'); parser.add_argument('--output')
    parser.add_argument('--options',default='{}',help='JSON; use PDF_OPTIONS_STDIN=1 para opções sensíveis.')
    parser.add_argument('--capabilities',action='store_true')
    args=parser.parse_args()
    try:
        if args.capabilities:
            print(json.dumps(capabilities(),ensure_ascii=False)); return
        if not args.operation or not args.output: parser.error('operation e --output são obrigatórios.')
        options=json.load(sys.stdin) if os.getenv('PDF_OPTIONS_STDIN')=='1' else json.loads(args.options)
        run(args.operation,args.inputs,args.output,options)
        print(json.dumps(dict(ok=True,output=args.output),ensure_ascii=False))
    except KeyboardInterrupt:
        print(json.dumps(dict(ok=False,error='Operação cancelada.',code='Cancelled'),ensure_ascii=False),file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(json.dumps(dict(ok=False,error=str(exc),code=type(exc).__name__),ensure_ascii=False),file=sys.stderr)
        sys.exit(1)
if __name__=='__main__': main()
