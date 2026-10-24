"""PAdES signatures with explicit trust and opt-in bounded revocation endpoints.

The caller's transaction publishes output. PINs arrive over stdin in the CLI and
live only in process memory; Python/Swift cannot guarantee zeroisation of copies.
"""
from __future__ import annotations

import datetime as dt
import asyncio
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit


@contextmanager
def _regular_stream(path):
    # O_NONBLOCK closes the FIFO/device hang before fstat can establish its type;
    # O_NOFOLLOW refuses a final symlink instead of loading a different identity.
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
    try:
        descriptor = os.open(Path(path).expanduser(), flags)
    except OSError:
        raise ValueError('Selecione um arquivo local regular e legível, sem link simbólico.') from None
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('A entrada precisa ser um arquivo regular; dispositivos e pipes não são permitidos.')
        yield stream


@contextmanager
def _snapshot(path):
    with _regular_stream(path) as source, tempfile.TemporaryDirectory(prefix='pdf-signatures-') as temporary:
        snapshot = Path(temporary)/'document.pdf'
        before = os.fstat(source.fileno())
        remaining = before.st_size
        with snapshot.open('xb') as destination:
            while remaining:
                chunk = source.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise ValueError('O PDF mudou durante a leitura. Selecione uma cópia estável.')
                destination.write(chunk)
                remaining -= len(chunk)
        after = os.fstat(source.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('O PDF mudou durante a leitura. Selecione uma cópia estável.')
        yield snapshot


@contextmanager
def _structured_validation_diagnostics():
    # pyHanko logs expected untrusted/expired certificate paths as tracebacks.
    # Their complete structured status is returned below; do not leak personal
    # certificate fields into incidental terminal/application diagnostic logs.
    logger = logging.getLogger('pyhanko.sign.validation.generic_cms')
    previous = logger.disabled
    logger.disabled = True
    try:
        yield
    finally:
        logger.disabled = previous


def _bounded_file(path, limit=16 * 1024 * 1024):
    with _regular_stream(path) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > limit:
            raise ValueError('O certificado excede o limite de 16 MB.')
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if len(data) > limit:
            raise ValueError('O certificado excede o limite de 16 MB.')
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('O certificado mudou durante a leitura. Selecione uma cópia estável.')
    return data


def _text(options, key, default='', limit=500):
    value = options.get(key, default)
    if not isinstance(value, str) or len(value) > limit or '\0' in value:
        raise ValueError(f'Opção inválida: {key}.')
    return value


def _certificate_summary(certificate, now):
    validity = certificate['tbs_certificate']['validity']
    start = validity['not_before'].native
    end = validity['not_after'].native
    self_signed = False
    if certificate.subject == certificate.issuer:
        from cryptography import x509
        from cryptography.exceptions import InvalidSignature
        parsed = x509.load_der_x509_certificate(certificate.dump())
        try:
            parsed.verify_directly_issued_by(parsed)
            self_signed = True
        except (ValueError, TypeError, InvalidSignature):
            pass
    return {
        'self_signed': self_signed,
        'subject': certificate.subject.human_friendly,
        'issuer': certificate.issuer.human_friendly,
        'serial_number': str(certificate.serial_number),
        'sha256': hashlib.sha256(certificate.dump()).hexdigest(),
        'not_before': start.isoformat(), 'not_after': end.isoformat(),
        'expired': now > end, 'not_yet_valid': now < start,
        # Equal subject/issuer alone does not prove a self-signature.
        'self_issued': certificate.subject == certificate.issuer,
    }


def _roots(options):
    from asn1crypto import pem, x509
    paths = options.get('trust_roots', [])
    if not isinstance(paths, list) or len(paths) > 64 or not all(isinstance(p, str) for p in paths):
        raise ValueError('trust_roots deve conter até 64 arquivos locais PEM ou DER.')
    result = []
    for path in paths:
        data = _bounded_file(path)
        try:
            if pem.detect(data):
                for kind, _, der in pem.unarmor(data, multiple=True):
                    if kind != 'CERTIFICATE':
                        raise ValueError('Selecione certificados públicos PEM ou DER, sem chaves privadas.')
                    result.append(x509.Certificate.load(der, strict=True))
            else:
                result.append(x509.Certificate.load(data, strict=True))
        except (ValueError, TypeError):
            raise ValueError('Não foi possível ler um certificado público de confiança.') from None
    if len(result) > 256:
        raise ValueError('O conjunto de confiança contém certificados demais (máximo 256).')
    return result


def _timestamper(url):
    """Send only RFC3161 message imprints, with no redirects or implicit proxies."""
    from pyhanko.sign.timestamps import HTTPTimeStamper
    from pyhanko.sign.timestamps.common_utils import TimestampRequestError
    from asn1crypto import tsp
    import aiohttp
    from signature_validation import tls_context
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('O carimbo do tempo requer uma URL HTTPS sem credenciais nem fragmento.')

    class ExplicitTimeStamper(HTTPTimeStamper):
        async def async_request_tsa_response(self, req):
            try:
                async with aiohttp.ClientSession(trust_env=False) as session:
                    async with session.post(url, data=req.dump(),
                            headers={'Content-Type': 'application/timestamp-query'},
                            allow_redirects=False, ssl=tls_context(), timeout=aiohttp.ClientTimeout(total=20)) as response:
                        if response.status != 200 or response.content_type != 'application/timestamp-reply':
                            raise TimestampRequestError('A TSA não respondeu com um carimbo do tempo válido.')
                        chunks = []; total = 0
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            total += len(chunk)
                            if total > 1024 * 1024:
                                raise TimestampRequestError('A resposta da TSA excede 1 MB.')
                            chunks.append(chunk)
                        return tsp.TimeStampResp.load(b''.join(chunks), strict=True)
            except (aiohttp.ClientError, OSError, ValueError) as exc:
                raise TimestampRequestError('Falha no carimbo do tempo HTTPS; a cópia não foi publicada.') from None

    return ExplicitTimeStamper(url, https=True, timeout=20)


def sign_pdf(input_path, output_path, options):
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    certificate = _text(options, 'certificate', limit=4096)
    if not certificate:
        raise ValueError('Selecione seu certificado PKCS#12 (.p12 ou .pfx).')
    pin = _text(options, 'certificate_password', limit=4096)
    try:
        signer = signers.SimpleSigner.load_pkcs12_data(
            _bounded_file(certificate), other_certs=[], passphrase=pin.encode('utf-8') if pin else None)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Não foi possível abrir o PKCS#12. Confira o PIN e se contém certificado e chave privada.') from None
    finally:
        pin = ''
    now = dt.datetime.now(dt.timezone.utc)
    cert = _certificate_summary(signer.signing_cert, now)
    if cert['expired'] or cert['not_yet_valid']:
        raise ValueError('O certificado não está dentro do seu período de validade.')
    field = _text(options, 'field_name', 'AssinaturaPDF', 128)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', field):
        raise ValueError('Nome do campo: use letras sem acentos, números, hífen ou sublinhado.')
    tsa_url = _text(options, 'tsa_url', limit=2048).strip()
    stamper = _timestamper(tsa_url) if tsa_url else None
    profile=options.get('profile','B-T' if tsa_url else 'B-B')
    if profile not in ('B-B','B-T','B-LT','B-LTA'): raise ValueError('Perfil PAdES inválido.')
    if profile!='B-B' and stamper is None: raise ValueError('PAdES B-T/LT/LTA exige uma TSA HTTPS explícita.')
    validation=None
    if profile in ('B-LT','B-LTA'):
        from signature_validation import material,context
        roots=_roots(options)
        if not roots: raise ValueError('PAdES LT/LTA exige raízes de confiança explícitas.')
        certificates=[signer.signing_cert,*list(signer.cert_registry),*roots]
        revinfo=material({**options,'revocation_mode':'require'},certificates)
        if not revinfo['crls'] and not revinfo['ocsps']:
            raise ValueError('PAdES LT/LTA exige evidência OCSP ou CRL verificável para a cadeia.')
        validation=context(roots,revinfo,certificates)
    metadata = signers.PdfSignatureMetadata(
        field_name=field, md_algorithm='sha256',
        reason=_text(options, 'reason') or None,
        location=_text(options, 'location') or None,
        subfilter=fields.SigSeedSubFilter.PADES,
        embed_validation_info=profile in ('B-LT','B-LTA'), use_pades_lta=profile=='B-LTA',
        validation_context=validation,
    )
    with _snapshot(input_path) as snapshot, snapshot.open('rb') as source:
        writer = IncrementalPdfFileWriter(source, strict=True)
        if writer.prev.encrypted:
            raise ValueError('Desbloqueie uma cópia do PDF antes de assinar digitalmente.')
        # New invisible field: a visual mark is a separate, earlier editing step.
        # Incremental writing preserves prior signatures and the original file.
        existing = [name for name, _, _ in fields.enumerate_sig_fields(writer.prev)]
        if field in existing:
            raise ValueError('Já existe um campo com esse nome. Escolha outro nome para a nova assinatura.')
        with Path(output_path).open('xb') as destination:
            signers.PdfSigner(metadata, signer=signer, timestamper=stamper,
                new_field_spec=fields.SigFieldSpec(field)).sign_pdf(writer, output=destination)


def verify_pdf(input_path, output_path, options):
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext
    roots = _roots(options)
    from signature_validation import material,context as revocation_context,lta_status
    mode=options.get('revocation_mode','offline')
    if mode not in ('offline','require'): raise ValueError('revocation_mode deve ser offline ou require.')
    now = dt.datetime.now(dt.timezone.utc)
    report = {
        'schema_version': 1, 'kind': 'digital-signatures',
        'checked_at': now.isoformat(), 'file': Path(input_path).name,
        'trust_policy': 'explicit_local_roots_only',
        'trust_anchors': [_certificate_summary(root, now) for root in roots],
        'network_access': False,
        'revocation_status': 'not_checked_offline' if mode=='offline' else 'required_for_every_non_anchor_certificate',
        'identity_assurance': 'not_assessed',
        'limitations': [
            'A integridade criptográfica não comprova a identidade civil do titular.',
            'As raízes selecionadas são uma decisão de confiança sua; certificados autoemitidos não certificam identidade.',
            ('Sem exigência de revogação: o relatório não comprova que o certificado continua não revogado.' if mode=='offline' else
             'OCSP/CRL deve cobrir todos os certificados não âncora; resposta ausente, inválida ou expirada não confirma não revogação.'),
            'A data declarada pelo assinante não é prova de tempo. Carimbos são verificados separadamente quando presentes.',
            'Esta verificação não atribui assinatura qualificada nem validade jurídica. A avaliação AdES-LTA, quando solicitada, aparece separadamente.',
        ], 'signatures': [], 'findings': [],
    }
    with _snapshot(input_path) as snapshot, snapshot.open('rb') as source:
        report['input_sha256'] = hashlib.file_digest(source, 'sha256').hexdigest()
        source.seek(0)
        reader = PdfFileReader(source, strict=True)
        if reader.encrypted:
            raise ValueError('A verificação exige uma cópia de PDF não criptografada.')
        embedded = reader.embedded_signatures
        if len(embedded) > 256:
            raise ValueError('O documento excede o limite de 256 assinaturas por verificação.')
        for signature in embedded:
            item = {'field_name': signature.field_name}
            try:
                certificates=[entry.chosen for entry in signature.signed_data['certificates'] if entry.name=='certificate']
                revinfo=material(options,[*certificates,*roots])
                context=revocation_context(roots,revinfo,certificates)
                report['network_access']=report['network_access'] or revinfo['network_access']
                with _structured_validation_diagnostics():
                    is_document_timestamp=signature.sig_object_type=='/DocTimeStamp'
                    if is_document_timestamp:
                        from pyhanko.sign.validation import async_validate_pdf_timestamp
                        status=asyncio.run(async_validate_pdf_timestamp(signature,validation_context=context))
                    else:
                        status = validate_pdf_signature(signature, signer_validation_context=context,
                                                        ts_validation_context=context)
                certificate = _certificate_summary(status.signing_cert, now)
                item.update(certificate=certificate, intact=bool(status.intact),
                    cryptographically_valid=bool(status.valid), trusted=bool(status.trusted),
                    coverage=status.coverage.name if status.coverage else 'UNKNOWN',
                    docmdp_ok=status.docmdp_ok,
                    trust_problem=status.trust_problem_indic.name if status.trust_problem_indic else None,
                    digest_algorithm=status.md_algorithm,
                    signature_algorithm=status.pkcs7_signature_mechanism,
                    signer_reported_time=getattr(status,'signer_reported_dt',None).isoformat() if getattr(status,'signer_reported_dt',None) else None,
                    modification_level=getattr(status,'modification_level',None).name if getattr(status,'modification_level',None) else None,
                    chain=[_certificate_summary(cert, now) for cert in status.validation_path] if status.validation_path else [],
                    subfilter=str(signature.sig_object.get('/SubFilter', '')),
                )
                item['kind']='document-timestamp' if is_document_timestamp else 'signature'
                timestamp = status if is_document_timestamp else status.timestamp_validity
                item['timestamp'] = None if timestamp is None else {
                    'time': timestamp.timestamp.isoformat(), 'intact': timestamp.intact,
                    'cryptographically_valid': timestamp.valid, 'trusted': timestamp.trusted,
                    'trust_problem': timestamp.trust_problem_indic.name if timestamp.trust_problem_indic else None,
                }
                item['unchanged_since_signing'] = item['coverage'] == 'ENTIRE_FILE'
                item['integrity_ok'] = item['intact'] and item['cryptographically_valid']
                item['revocation']={'policy':mode,'status':('not_required' if mode=='offline' else
                    'revoked' if status.revoked else 'good' if status.trusted else 'failed_or_unknown'),
                    'evidence':revinfo['evidence']}
                if options.get('validate_lta') is True and not is_document_timestamp:
                    item['long_term_validation']=lta_status(signature,roots)
                if not item['integrity_ok']:
                    report['findings'].append({'severity': 'error', 'rule': 'signature-integrity', 'field': signature.field_name,
                        'message': 'A assinatura não corresponde aos bytes assinados ou é criptograficamente inválida.'})
                if not item['trusted']:
                    report['findings'].append({'severity': 'warning', 'rule': 'certificate-trust', 'field': signature.field_name,
                        'message': 'Não foi possível estabelecer uma cadeia válida até as raízes locais selecionadas.'})
                if not item['unchanged_since_signing']:
                    report['findings'].append({'severity': 'warning', 'rule': 'later-revision', 'field': signature.field_name,
                        'message': 'Existem bytes ou revisões posteriores à assinatura; consulte cobertura e alterações permitidas.'})
                if certificate['expired'] or certificate['not_yet_valid']:
                    report['findings'].append({'severity': 'error', 'rule': 'certificate-validity', 'field': signature.field_name,
                        'message': 'O certificado está fora do período de validade na data desta verificação.'})
            except Exception as exc:
                item.update(integrity_ok=False, trusted=False, error='Falha ao verificar esta assinatura: ' + type(exc).__name__)
                report['findings'].append({'severity': 'error', 'rule': 'signature-parse', 'field': signature.field_name,
                                          'message': item['error']})
            report['signatures'].append(item)
    signatures = report['signatures']
    report['signature_count'] = len(signatures)
    report['all_integrity_ok'] = bool(signatures) and all(s['integrity_ok'] for s in signatures)
    report['all_chains_trusted'] = bool(signatures) and all(s['trusted'] for s in signatures)
    report['all_cover_current_file'] = bool(signatures) and all(s.get('unchanged_since_signing', False) for s in signatures)
    if not signatures:
        report['summary'] = 'Nenhuma assinatura digital criptográfica encontrada.'
    elif not report['all_integrity_ok']:
        report['summary'] = 'Verificação com falhas de integridade ou assinatura ilegível.'
    elif not report['all_chains_trusted']:
        report['summary'] = 'Integridade confirmada; a confiança da cadeia não foi estabelecida para todas as assinaturas.'
    else:
        report['summary'] = ('Integridade, cadeias e evidência de revogação confirmadas segundo a política explícita; identidade civil não certificada.'
                             if mode=='require' else 'Integridade e cadeias locais confirmadas. Revogação e identidade civil não foram certificadas.')
    with Path(output_path).open('x', encoding='utf-8') as destination:
        json.dump(report, destination, ensure_ascii=False, indent=2)
    return report
