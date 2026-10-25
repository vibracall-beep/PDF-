"""Explicit Dropbox Sign v3 adapter. Preparing a request is entirely local.

Contract: official hellosign/dropbox-sign-python docs/SignatureRequestApi.md,
SignatureRequestSendRequest.md and SubFormFieldsPerDocumentBase.md (2026-10).
Never retry a POST: a lost response can still mean the provider sent the request.
"""
from __future__ import annotations
import asyncio
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

import aiohttp
import fitz
from pdf_signatures import _bounded_file, _snapshot, _text

BASE_URL='https://api.hellosign.com/v3'
MAX_ATTACHMENT=40*1024*1024
MAX_COMPLETED_PDF=128*1024*1024


def _field_bounds(pdf,fields):
    # Official Dropbox Sign API demo uses A4 595x842 at72DPI and transfers
    # x/y/width/height unchanged to page-relative form_fields_per_document.
    # PDF points are1/72in. These checks do not resize or rasterize the upload.
    # https://github.com/hellosign/dropbox-sign-api-demo/blob/d60fa159b9c68dc3d8dd89d1f40992be6a05a216/public/main.js#L1987
    for field in fields:
        if field['page']>len(pdf):raise ValueError('Um campo aponta para uma página inexistente.')
        page=pdf[field['page']-1];bounds=page.rect
        if field['x']+field['width']>bounds.width or field['y']+field['height']>bounds.height:
            raise ValueError('Um campo de assinatura ultrapassa os limites visíveis da página (pixels a 72 DPI).')


def _configuration(options):
    signers=options.get('signers')
    if not isinstance(signers,list) or not 1<=len(signers)<=20:
        raise ValueError('Informe de 1 a 20 destinatários.')
    clean=[]
    for signer in signers:
        if not isinstance(signer,dict): raise ValueError('Destinatário inválido.')
        name=_text(signer,'name',limit=200).strip();email=_text(signer,'email_address',limit=254).strip()
        if not name or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email):
            raise ValueError('Cada destinatário precisa de nome e email válidos.')
        clean.append({'name':name,'email_address':email})
    if len({s['email_address'].lower() for s in clean})!=len(clean): raise ValueError('Não repita destinatários.')
    test_mode=options.get('test_mode',True)
    if type(test_mode) is not bool: raise ValueError('test_mode precisa ser booleano.')
    fields=options.get('fields')
    if not isinstance(fields,list) or not 1<=len(fields)<=200: raise ValueError('Defina os campos de assinatura no PDF (máximo 200).')
    validated=[]; signed=set()
    for index,field in enumerate(fields):
        if not isinstance(field,dict): raise ValueError('Campo inválido.')
        kind=field.get('type','signature'); signer=field.get('signer',0)
        if kind not in ('signature','initials','date_signed'): raise ValueError('Use campos de assinatura, iniciais ou data da assinatura.')
        if type(signer) is not int or not 0<=signer<len(clean): raise ValueError('O campo aponta para um destinatário inexistente.')
        shape={}
        for key in ('page','x','y','width','height'):
            value=field.get(key)
            minimum=0 if key in ('x','y') else 1
            if type(value) is not int or not minimum<=value<=20000: raise ValueError(f'Coordenada inválida: {key}.')
            shape[key]=value
        validated.append(dict(document_index=0,api_id=f'field-{index+1}',type=kind,signer=str(signer),required=True,**shape))
        if kind=='signature': signed.add(signer)
    if signed!=set(range(len(clean))): raise ValueError('Cada destinatário precisa de pelo menos um campo de assinatura.')
    return {'signers':clean,'fields':validated,'test_mode':test_mode,
            'title':_text(options,'title','Assinatura de documento',200),
            'subject':_text(options,'subject','Documento para assinatura',200),
            'message':_text(options,'message','',5000)}


def prepare_request(input_path,output_path,options):
    configuration=_configuration(options)
    with _snapshot(input_path,limit=MAX_ATTACHMENT) as snapshot:
        if snapshot.stat().st_size>MAX_ATTACHMENT: raise ValueError('O PDF excede o limite local de 40 MiB para envio.')
        with fitz.open(snapshot) as pdf:
            if pdf.needs_pass or (pdf.metadata or {}).get('encryption'): raise ValueError('Selecione uma cópia não criptografada para os destinatários.')
            if not len(pdf): raise ValueError('O PDF não contém páginas.')
            _field_bounds(pdf,configuration['fields'])
            pages=[{'page':i+1,'width_points':page.rect.width,'height_points':page.rect.height} for i,page in enumerate(pdf)]
        draft={'schema_version':1,'provider':'dropbox-sign','state':'prepared_not_sent','draft_id':uuid.uuid4().hex,
               'input_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),'file_name':Path(input_path).name,
               'bytes':snapshot.stat().st_size,'pages':pages,'configuration':configuration,
               'coordinate_system':'provider_page_pixels_72dpi_top_left','network_access':False,
               'notice':'Preparação local. Enviar transmite o PDF, nomes, emails e mensagem ao Dropbox Sign e pode enviar emails mesmo em modo de teste.'}
    with Path(output_path).open('x',encoding='utf-8') as destination:json.dump(draft,destination,ensure_ascii=False,indent=2)
    return draft


async def _call(method,path,key,form=None):
    # Fixed provider origin. No arbitrary URL, redirects, ambient proxies or retries.
    try:
        async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=90)) as session:
            async with session.request(method,BASE_URL+path,data=form,
                                       headers={'Accept':'application/json','Authorization':aiohttp.encode_basic_auth(key,'')},allow_redirects=False) as response:
                chunks=[];size=0
                async for chunk in response.content.iter_chunked(65536):
                    size+=len(chunk)
                    if size>2*1024*1024: raise ValueError('Resposta do serviço excede 2 MiB.')
                    chunks.append(chunk)
                if response.status!=200:
                    raise ValueError(f'O Dropbox Sign recusou a operação (HTTP {response.status}). Nenhuma repetição automática foi realizada.')
                data=json.loads(b''.join(chunks))
                if not isinstance(data,dict): raise ValueError('Resposta inválida do serviço.')
                return data
    except (aiohttp.ClientError,asyncio.TimeoutError,OSError,json.JSONDecodeError):
        message=('A resposta do Dropbox Sign não pôde ser confirmada. Um envio pode ter ocorrido: consulte a conta antes de repetir.'
                 if method=='POST' else 'A consulta ao Dropbox Sign não pôde ser concluída. Tente consultar o estado novamente.')
        raise RuntimeError(message) from None


def _key(options):
    value=options.get('api_key') or os.environ.get('PDF_DROPBOX_SIGN_API_KEY')
    if not isinstance(value,str) or not 1<=len(value)<=4096 or any(ord(c)<33 or ord(c)>126 or c==':' for c in value):
        raise ValueError('Configure a chave da API Dropbox Sign no Chaves do macOS ou em PDF_DROPBOX_SIGN_API_KEY.')
    return value


def _result(data,action):
    request=data.get('signature_request')
    if not isinstance(request,dict): raise ValueError('O serviço não retornou uma solicitação reconhecível.')
    identifier=request.get('signature_request_id')
    if not isinstance(identifier,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',identifier): raise ValueError('Identificador de solicitação inválido.')
    if any(type(request.get(key)) is not bool for key in ('is_complete','has_error','test_mode')):
        raise ValueError('O serviço retornou estados de solicitação inválidos.')
    signatures=request.get('signatures',[])
    if not isinstance(signatures,list) or len(signatures)>100: raise ValueError('Lista de assinaturas inválida.')
    # Whitelist response fields. Never persist OAuth tokens, signing URLs or keys.
    clean=[]
    for signature in signatures:
        if not isinstance(signature,dict): raise ValueError('Resposta de assinatura inválida.')
        for field,limit in (('signer_name',200),('signer_email_address',254),('status_code',80)):
            value=signature.get(field)
            if value is not None and (not isinstance(value,str) or len(value)>limit or '\0' in value):
                raise ValueError('O serviço retornou dados de destinatário inválidos.')
        signed_at=signature.get('signed_at')
        if signed_at is not None and (type(signed_at) is not int or not 0<=signed_at<=253402300799):
            raise ValueError('O serviço retornou uma data de assinatura inválida.')
        clean.append({k:signature.get(k) for k in ('signer_name','signer_email_address','status_code','signed_at')})
    return {'schema_version':1,'provider':'dropbox-sign','action':action,'network_access':True,
            'signature_request_id':identifier,'test_mode':request.get('test_mode'),
            'is_complete':request.get('is_complete') is True,'has_error':request.get('has_error') is True,
            'signatures':clean,'summary':'Estado informado pelo Dropbox Sign; verifique separadamente as assinaturas criptográficas do PDF final.'}


def send_request(input_path,output_path,options):
    if os.path.lexists(output_path): raise FileExistsError('O destino já existe.')
    if options.get('confirm_send') is not True: raise ValueError('O envio exige uma ação explícita após revisar documento, campos e destinatários.')
    draft_path=options.get('draft')
    if not isinstance(draft_path,str): raise ValueError('Selecione a preparação local revisada.')
    try:
        draft_bytes=_bounded_file(draft_path,2*1024*1024)
        draft=json.loads(draft_bytes)
    except (ValueError,TypeError): raise ValueError('Preparação local inválida.') from None
    if not isinstance(draft,dict) or draft.get('schema_version')!=1 or draft.get('provider')!='dropbox-sign' or draft.get('state')!='prepared_not_sent': raise ValueError('Preparação incompatível.')
    if hashlib.sha256(draft_bytes).hexdigest()!=options.get('confirmed_draft_sha256'):
        raise ValueError('Os destinatários ou campos mudaram. Revise novamente a preparação completa antes do envio.')
    draft_id=draft.get('draft_id')
    if not isinstance(draft_id,str) or not re.fullmatch('[a-f0-9]{32}',draft_id):raise ValueError('Identificador de preparação inválido.')
    configuration=_configuration({**draft.get('configuration',{}),
        'fields':[{**f,'signer':int(f['signer'])} for f in draft.get('configuration',{}).get('fields',[])]})
    key=_key(options)
    with _snapshot(input_path,limit=MAX_ATTACHMENT) as snapshot:
        if snapshot.stat().st_size>MAX_ATTACHMENT: raise ValueError('O PDF excede 40 MiB.')
        digest=hashlib.sha256(snapshot.read_bytes()).hexdigest()
        if digest!=draft.get('input_sha256') or digest!=options.get('confirmed_sha256'):
            raise ValueError('O documento mudou desde a preparação. Prepare e revise novamente antes do envio.')
        with fitz.open(snapshot) as pdf:
            if pdf.needs_pass or (pdf.metadata or {}).get('encryption'):
                raise ValueError('Selecione uma cópia não criptografada para os destinatários.')
            _field_bounds(pdf,configuration['fields'])
        form=aiohttp.FormData()
        for name in ('title','subject','message'): form.add_field(name,configuration[name])
        form.add_field('test_mode','1' if configuration['test_mode'] else '0')
        for index,signer in enumerate(configuration['signers']):
            for name,value in signer.items(): form.add_field(f'signers[{index}][{name}]',value)
        form.add_field('form_fields_per_document',json.dumps(configuration['fields']))
        form.add_field('metadata',json.dumps({'pdf_draft_id':draft.get('draft_id'),'pdf_sha256':digest}))
        # An exclusive durable receipt prevents retrying the same draft after a
        # lost response, app restart or local publication failure. It contains
        # only hashes, times and the provider request ID; never credentials/PII.
        journal=Path(draft_path).parent/('.pdf-signature-attempt-'+draft_id+'.json')
        try: descriptor=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError:
            raise ValueError('Este rascunho já teve uma tentativa de envio. Consulte o registro local e a conta Dropbox Sign antes de preparar outro; não houve repetição automática.') from None
        with os.fdopen(descriptor,'w',encoding='utf-8') as receipt:
            record={'schema_version':1,'draft_id':draft_id,'input_sha256':digest,
                'draft_sha256':hashlib.sha256(draft_bytes).hexdigest(),'state':'response_not_confirmed',
                'attempted_at':dt.datetime.now(dt.timezone.utc).isoformat()}
            json.dump(record,receipt);receipt.flush();os.fsync(receipt.fileno())
            directory_fd=os.open(journal.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try:os.fsync(directory_fd)
            finally:os.close(directory_fd)
            with snapshot.open('rb') as attachment:
                form.add_field('files[0]',attachment,filename=Path(input_path).name,content_type='application/pdf')
                result=_result(asyncio.run(_call('POST','/signature_request/send',key,form)),'sent')
            record.update(state='confirmed',signature_request_id=result['signature_request_id'])
            receipt.seek(0);receipt.truncate();json.dump(record,receipt);receipt.flush();os.fsync(receipt.fileno())
    result['input_sha256']=digest;result['draft_id']=draft.get('draft_id')
    result['local_attempt_record']=str(journal)
    with Path(output_path).open('x',encoding='utf-8') as destination:json.dump(result,destination,ensure_ascii=False,indent=2)
    return result


def request_status(input_path,output_path,options):
    if os.path.lexists(output_path): raise FileExistsError('O destino já existe.')
    identifier=_request_identifier(options)
    result=_result(asyncio.run(_call('GET','/signature_request/'+identifier,_key(options))),'status')
    if result['signature_request_id']!=identifier: raise ValueError('O serviço retornou outra solicitação.')
    with Path(output_path).open('x',encoding='utf-8') as destination:json.dump(result,destination,ensure_ascii=False,indent=2)
    return result


def _request_identifier(options):
    identifier=_text(options,'request_id',limit=128)
    if not re.fullmatch('[A-Za-z0-9_-]{1,128}',identifier):
        raise ValueError('Informe um identificador de solicitação válido.')
    return identifier


async def _download_completed_pdf(identifier,key,path):
    """Fetch bytes from the authenticated files endpoint, never an API-supplied URL.

    The service returns PDF bytes with file_type=pdf. Redirects and decompression
    are refused so neither credentials nor bytes can silently cross an origin or
    exceed the bounded streamed payload. No local PDF rewrite may invalidate a
    signature, and the returned receipt does not assert cryptographic validity.
    """
    try:
        async with aiohttp.ClientSession(trust_env=False,auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=120)) as session:
            async with session.get(BASE_URL+'/signature_request/files/'+identifier+'?file_type=pdf',
                    headers={'Accept':'application/pdf','Accept-Encoding':'identity',
                             'Authorization':aiohttp.encode_basic_auth(key,'')},allow_redirects=False) as response:
                if response.status!=200:
                    raise ValueError(f'O Dropbox Sign não disponibilizou o PDF (HTTP {response.status}). Nenhuma repetição automática foi realizada.')
                if response.content_type!='application/pdf' or response.headers.get('Content-Encoding','identity').lower()!='identity':
                    raise ValueError('O serviço não retornou um PDF sem compressão de transporte.')
                if response.content_length is not None and not 0<response.content_length<=MAX_COMPLETED_PDF:
                    raise ValueError('O PDF concluído está vazio ou excede o limite local de 128 MiB.')
                size=0;digest=hashlib.sha256()
                with path.open('xb') as destination:
                    os.chmod(path,0o600)
                    async for chunk in response.content.iter_chunked(65536):
                        size+=len(chunk)
                        if size>MAX_COMPLETED_PDF:
                            raise ValueError('O PDF concluído excede o limite local de 128 MiB.')
                        destination.write(chunk);digest.update(chunk)
                    destination.flush();os.fsync(destination.fileno())
                if not size:
                    raise ValueError('O serviço retornou um arquivo vazio.')
                return size,digest.hexdigest()
    except (aiohttp.ClientError,asyncio.TimeoutError,OSError):
        raise RuntimeError('O download do PDF não pôde ser concluído. Nenhum arquivo parcial foi publicado; consulte o estado antes de tentar novamente.') from None


def download_request(input_path,output_path,options):
    """Download a completed request on an explicit user action, without email."""
    output=Path(output_path)
    if os.path.lexists(output): raise FileExistsError('O destino já existe.')
    if options.get('confirm_download') is not True:
        raise ValueError('Confirme o download do PDF da solicitação selecionada.')
    identifier=_request_identifier(options);key=_key(options)
    result=_result(asyncio.run(_call('GET','/signature_request/'+identifier,key)),'downloaded')
    if result['signature_request_id']!=identifier:
        raise ValueError('O serviço retornou outra solicitação.')
    if not result['is_complete'] or result['has_error']:
        raise ValueError('A solicitação ainda não está concluída sem erros; nenhum PDF foi baixado.')
    # Private staging and no-clobber hard-link publication also protect direct
    # callers; pdf_engine adds its outer transaction and destination race checks.
    with tempfile.TemporaryDirectory(prefix='.pdf-signature-download-',dir=output.parent) as temporary:
        staged=Path(temporary)/'completed.pdf'
        size,digest=asyncio.run(_download_completed_pdf(identifier,key,staged))
        with staged.open('rb') as stream:
            if not stream.read(8).startswith(b'%PDF-'):
                raise ValueError('O arquivo recebido não tem um cabeçalho PDF válido.')
        try:
            with fitz.open(staged) as document:
                if not document.is_pdf or document.is_repaired or document.needs_pass or (document.metadata or {}).get('encryption') or not 1<=len(document)<=10000:
                    raise ValueError('O serviço retornou um PDF danificado, criptografado, vazio ou com mais de 10 mil páginas.')
                pages=len(document)
                # Resolve every page now; a readable header alone is insufficient.
                for page in document:
                    if page.rect.is_empty or page.rect.is_infinite:
                        raise ValueError('O PDF recebido contém uma página inválida.')
        except (fitz.FileDataError,RuntimeError):
            raise ValueError('O serviço retornou um PDF ilegível; nenhum arquivo foi publicado.') from None
        os.link(staged,output,follow_symlinks=False)
        directory_fd=os.open(output.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)
    result.update(output_sha256=digest,output_bytes=size,pages=pages,
                  cryptographic_signatures_verified=False,
                  summary='PDF concluído recebido do Dropbox Sign, preservado byte a byte. Use Verificar assinaturas para examinar integridade e confiança; a conclusão do serviço não é uma validação criptográfica.')
    return result
