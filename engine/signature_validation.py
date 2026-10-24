"""Bounded, explicit OCSP/CRL acquisition and strict certificate policy.

Certificate URLs never authorize network access by themselves. The user must
select each HTTPS endpoint. Responses are authenticated by certvalidator, not
trusted merely because transport succeeded. Default operation stays offline.
"""
from __future__ import annotations
import asyncio
import hashlib
import ssl
from urllib.parse import urlsplit

import aiohttp
from asn1crypto import crl,ocsp,pem,x509
from cryptography import x509 as crypto_x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.x509 import ocsp as crypto_ocsp
from cryptography.x509.oid import AuthorityInformationAccessOID
from pyhanko_certvalidator import ValidationContext

MAX_RESPONSE=4*1024*1024

def tls_context():
    return ssl.create_default_context()


def _https(url):
    if not isinstance(url,str) or len(url)>2048: raise ValueError('URL de revogação inválida.')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('OCSP/CRL requer HTTPS explícito, sem credenciais nem fragmento.')
    return url


async def _fetch(url,request=None):
    method='POST' if request is not None else 'GET'
    headers={'Accept':'application/ocsp-response' if request is not None else 'application/pkix-crl'}
    if request is not None: headers['Content-Type']='application/ocsp-request'
    try:
        async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.request(method,url,data=request,headers=headers,allow_redirects=False,ssl=tls_context()) as response:
                if response.status!=200: raise ValueError('O serviço de revogação não retornou sucesso; nenhuma consulta alternativa foi realizada.')
                pieces=[];total=0
                async for piece in response.content.iter_chunked(65536):
                    total+=len(piece)
                    if total>MAX_RESPONSE: raise ValueError('A resposta de revogação excede 4 MiB.')
                    pieces.append(piece)
                return b''.join(pieces)
    except (aiohttp.ClientError,asyncio.TimeoutError,OSError):
        raise ValueError('Não foi possível consultar o endpoint de revogação autorizado.') from None


def material(options,certificates=()):
    from pdf_signatures import _bounded_file
    mode=options.get('revocation_mode','offline')
    if mode not in ('offline','require'): raise ValueError('revocation_mode deve ser offline ou require.')
    result={'ocsps':[],'crls':[],'evidence':[],'network_access':False,'mode':mode}
    for key,kind,parser in [('ocsp_responses','ocsp',ocsp.OCSPResponse),('crls','crl',crl.CertificateList)]:
        paths=options.get(key,[])
        if not isinstance(paths,list) or len(paths)>64 or not all(isinstance(p,str) for p in paths): raise ValueError(f'{key}: informe até 64 arquivos.')
        for path in paths:
            data=_bounded_file(path,MAX_RESPONSE)
            if pem.detect(data): _,_,data=pem.unarmor(data)
            try: value=parser.load(data,strict=True);value.native
            except (ValueError,TypeError,KeyError):raise ValueError('Resposta OCSP/CRL inválida.') from None
            result['ocsps' if kind=='ocsp' else 'crls'].append(value)
            result['evidence'].append({'kind':kind,'source':'local','sha256':hashlib.sha256(data).hexdigest()})
    endpoints=options.get('revocation_endpoints',[])
    if not isinstance(endpoints,list) or len(endpoints)>32: raise ValueError('Informe até 32 endpoints de revogação.')
    if endpoints and (mode!='require' or options.get('allow_revocation_network') is not True):
        raise ValueError('Confirme explicitamente a consulta de revogação pela rede.')
    parsed_certs=[crypto_x509.load_der_x509_certificate(c.dump()) for c in certificates]
    for endpoint in endpoints:
        if not isinstance(endpoint,dict) or endpoint.get('kind') not in ('ocsp','crl'):raise ValueError('Endpoint OCSP/CRL inválido.')
        url=_https(endpoint.get('url'));kind=endpoint['kind'];requests=[]
        if kind=='crl': requests=[None]
        else:
            for certificate in parsed_certs:
                try: aia=certificate.extensions.get_extension_for_class(crypto_x509.AuthorityInformationAccess).value
                except crypto_x509.ExtensionNotFound:continue
                urls=[item.access_location.value for item in aia if item.access_method==AuthorityInformationAccessOID.OCSP]
                if url not in urls:continue
                issuers=[c for c in parsed_certs if c.subject==certificate.issuer]
                for issuer in issuers:
                    try: certificate.verify_directly_issued_by(issuer)
                    except (ValueError,TypeError,InvalidSignature):continue
                    request=crypto_ocsp.OCSPRequestBuilder().add_certificate(certificate,issuer,hashes.SHA256()).build()
                    requests.append(request.public_bytes(serialization.Encoding.DER));break
            if not requests:raise ValueError('O endpoint OCSP não corresponde a um certificado com emissor verificável na cadeia fornecida.')
        for request in requests:
            data=asyncio.run(_fetch(url,request));parser=ocsp.OCSPResponse if kind=='ocsp' else crl.CertificateList
            if pem.detect(data): _,_,data=pem.unarmor(data)
            try:value=parser.load(data,strict=True);value.native
            except (ValueError,TypeError,KeyError):raise ValueError('O endpoint retornou uma resposta OCSP/CRL inválida.') from None
            result['ocsps' if kind=='ocsp' else 'crls'].append(value)
            result['evidence'].append({'kind':kind,'source':'explicit_https','sha256':hashlib.sha256(data).hexdigest()})
            result['network_access']=True
    return result


def context(roots,material,other_certs=()):
    # `require` checks every non-anchor certificate, including those without a
    # CDP/AIA extension. `hard-fail` alone would silently exempt those cases.
    return ValidationContext(trust_roots=roots,other_certs=other_certs,allow_fetching=False,
        crls=material['crls'],ocsps=material['ocsps'],
        revocation_mode='require' if material['mode']=='require' else 'soft-fail')


def add_embedded(reader,result):
    """DSS evidence is untrusted input until normal certificate validation succeeds."""
    from pyhanko.pdf_utils import generic
    dss=reader.root.get('/DSS')
    if dss is None:return []
    dss=dss.get_object()
    if not isinstance(dss,generic.DictionaryObject):raise ValueError('DSS inválido.')
    certificates=[]
    for key,kind,parser in [('/CRLs','crl',crl.CertificateList),('/OCSPs','ocsp',ocsp.OCSPResponse),('/Certs','certificate',x509.Certificate)]:
        entries=dss.get(key,generic.ArrayObject()).get_object()
        if not isinstance(entries,generic.ArrayObject) or len(entries)>256:raise ValueError('DSS contém evidências demais ou uma lista inválida.')
        for entry in entries:
            value=entry.get_object()
            if not isinstance(value,generic.StreamObject):raise ValueError('Evidência DSS sem stream válido.')
            data=value.data
            if len(data)>MAX_RESPONSE:raise ValueError('Uma evidência DSS excede 4 MiB.')
            try:parsed=parser.load(data,strict=True);parsed.native
            except (ValueError,TypeError,KeyError):raise ValueError('Evidência DSS malformada.') from None
            if kind=='certificate':certificates.append(parsed)
            else:
                result['crls' if kind=='crl' else 'ocsps'].append(parsed)
                result['evidence'].append({'kind':kind,'source':'embedded_dss','sha256':hashlib.sha256(data).hexdigest()})
    return certificates


def lta_status(signature,roots):
    from pyhanko.sign.validation.ades import ades_lta_validation
    from pyhanko.sign.validation.policy_decl import (PdfSignatureValidationSpec,SignatureValidationSpec,
        RevocationInfoGatheringSpec,RevinfoOnlineFetchingRule,CertificateFetchingRule)
    from pyhanko_certvalidator.context import CertValidationPolicySpec
    from pyhanko_certvalidator.registry import SimpleTrustManager
    from pyhanko_certvalidator.policy_decl import CertRevTrustPolicy,RevocationCheckingPolicy
    structure={'has_document_timestamp':any(s.sig_object_type=='/DocTimeStamp' and s.signed_revision>signature.signed_revision for s in signature.reader.embedded_signatures),
        'has_embedded_validation_info':'/DSS' in signature.reader.root,
        'has_signature_timestamp':any(attribute['type'].native=='signature_time_stamp_token' for attribute in signature.signer_info['unsigned_attrs']),
        'pades_subfilter':str(signature.sig_object.get('/SubFilter',''))=='/ETSI.CAdES.detached'}
    if not all(structure.values()):
        return {'validation':'ETSI_AdES_LTA','status':'MISSING_LTA_STRUCTURE','passed':False,'network_access':False,**structure}
    policy=CertValidationPolicySpec(trust_manager=SimpleTrustManager.build(trust_roots=roots),
        revinfo_policy=CertRevTrustPolicy(RevocationCheckingPolicy.from_legacy('require')))
    spec=PdfSignatureValidationSpec(SignatureValidationSpec(cert_validation_policy=policy,
        revinfo_gathering_policy=RevocationInfoGatheringSpec(
            online_fetching_rule=RevinfoOnlineFetchingRule.LOCAL_ONLY,
            certificate_fetching_rule=CertificateFetchingRule.NEVER_FETCH)))
    result=asyncio.run(ades_lta_validation(signature,spec))
    indication=result.ades_subindic
    return {'validation':'ETSI_AdES_LTA','status':indication.name,
            'passed':indication.name=='OK','network_access':False,**structure,
            'note':'A validação usa provas de tempo e revogação embutidas; preservação exige renovação antes de algoritmos e certificados perderem validade.'}
