"""Actual PKI, HTTPS OCSP/CRL and RFC3161 responses on loopback only."""
import datetime as dt
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import fitz
from asn1crypto import x509 as asn1x509, keys,tsp
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509 import ocsp
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID,AuthorityInformationAccessOID
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.timestamps import DummyTimeStamper

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
import pdf_signatures as signatures
import signature_validation as validation


class LongTermSignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.root=Path(cls.temporary.name)
        cls.now=dt.datetime.now(dt.timezone.utc);cls.calls=[];cls.revoked=False;cls.stale=False;cls.redirect=False
        cls.ca_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Local audit root')])
        cls.ca=(x509.CertificateBuilder().subject_name(cls.ca_name).issuer_name(cls.ca_name).public_key(cls.ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(cls.now-dt.timedelta(days=3)).not_valid_after(cls.now+dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),True)
            .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),True).sign(cls.ca_key,hashes.SHA256()))
        cls.trust=cls.root/'ca.pem';cls.trust.write_bytes(cls.ca.public_bytes(serialization.Encoding.PEM))
        owner=cls
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):self.respond(None)
            def do_POST(self):self.respond(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            def respond(self,body):
                owner.calls.append((self.command,self.path,body))
                if owner.redirect:
                    self.send_response(302);self.send_header('Location','https://127.0.0.1:1/no-follow');self.end_headers();return
                if self.path=='/tsa':
                    payload=owner.stamper.request_tsa_response(tsp.TimeStampReq.load(body)).dump();mime='application/timestamp-reply'
                elif self.path=='/crl':payload=owner.crl_bytes();mime='application/pkix-crl'
                elif self.path=='/ocsp':
                    request=ocsp.load_der_ocsp_request(body)
                    if request.serial_number!=owner.cert.serial_number:
                        self.send_error(400);return
                    payload=owner.ocsp_bytes();mime='application/ocsp-response'
                else:self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(payload)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.base=f'https://127.0.0.1:{cls.server.server_port}'
        cls.key,cls.cert=cls.issue('Signer',ocsp_url=cls.base+'/ocsp')
        tsa_key,tsa_cert=cls.issue('Timestamp authority',eku=ExtendedKeyUsageOID.TIME_STAMPING)
        server_key,server_cert=cls.issue('localhost',eku=ExtendedKeyUsageOID.SERVER_AUTH,san=True)
        server_pem=cls.root/'server.pem';server_pem.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM)+server_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_context.load_cert_chain(server_pem)
        cls.server.socket=server_context.wrap_socket(cls.server.socket,server_side=True)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.client_context=ssl.create_default_context(cafile=str(cls.trust))
        cls.p12=cls.root/'signer.p12';cls.p12.write_bytes(pkcs12.serialize_key_and_certificates(b'Local',cls.key,cls.cert,[cls.ca],serialization.BestAvailableEncryption(b'audit-pin')))
        cls.stamper=DummyTimeStamper(asn1x509.Certificate.load(tsa_cert.public_bytes(serialization.Encoding.DER)),
            keys.PrivateKeyInfo.load(tsa_key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())),
            certs_to_embed=[asn1x509.Certificate.load(cls.ca.public_bytes(serialization.Encoding.DER))])
        cls.source=cls.root/'source.pdf'
        with fitz.open() as document:document.new_page().insert_text((40,60),'Actual long term signing audit');document.save(cls.source)
        cls.signed=cls.root/'base.pdf';signatures.sign_pdf(cls.source,cls.signed,cls.sign_options())

    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temporary.cleanup()
    @classmethod
    def issue(cls,name,eku=None,san=False,ocsp_url=None):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        builder=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,name)]))
            .issuer_name(cls.ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(cls.now-dt.timedelta(days=2)).not_valid_after(cls.now+dt.timedelta(days=10))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
            .add_extension(x509.KeyUsage(True,True,False,False,False,False,False,False,False),True))
        if eku:builder=builder.add_extension(x509.ExtendedKeyUsage([eku]),True)
        if san:builder=builder.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False)
        if ocsp_url:builder=builder.add_extension(x509.AuthorityInformationAccess([x509.AccessDescription(AuthorityInformationAccessOID.OCSP,x509.UniformResourceIdentifier(ocsp_url))]),False)
        return key,builder.sign(cls.ca_key,hashes.SHA256())
    @classmethod
    def crl_bytes(cls):
        start=cls.now-dt.timedelta(days=2) if cls.stale else cls.now-dt.timedelta(minutes=5)
        end=cls.now-dt.timedelta(days=1) if cls.stale else cls.now+dt.timedelta(days=1)
        builder=x509.CertificateRevocationListBuilder().issuer_name(cls.ca_name).last_update(start).next_update(end)
        if cls.revoked:builder=builder.add_revoked_certificate(x509.RevokedCertificateBuilder().serial_number(cls.cert.serial_number).revocation_date(cls.now-dt.timedelta(hours=1)).build())
        return builder.sign(cls.ca_key,hashes.SHA256()).public_bytes(serialization.Encoding.DER)
    @classmethod
    def ocsp_bytes(cls):
        return (ocsp.OCSPResponseBuilder().add_response(cert=cls.cert,issuer=cls.ca,algorithm=hashes.SHA256(),
            cert_status=ocsp.OCSPCertStatus.REVOKED if cls.revoked else ocsp.OCSPCertStatus.GOOD,
            this_update=cls.now-dt.timedelta(minutes=5),next_update=cls.now+dt.timedelta(hours=2),
            revocation_time=cls.now-dt.timedelta(hours=1) if cls.revoked else None,revocation_reason=None)
            .responder_id(ocsp.OCSPResponderEncoding.HASH,cls.ca).sign(cls.ca_key,hashes.SHA256()).public_bytes(serialization.Encoding.DER))
    @classmethod
    def sign_options(cls):return {'certificate':str(cls.p12),'certificate_password':'audit-pin','trust_roots':[str(cls.trust)]}
    def setUp(self):
        type(self).revoked=False;type(self).stale=False;type(self).redirect=False;self.calls.clear()
        self.patch=patch.object(validation,'tls_context',return_value=self.client_context);self.patch.start()
    def tearDown(self):self.patch.stop()
    def verify(self,**extra):
        with tempfile.TemporaryDirectory() as temporary:
            return signatures.verify_pdf(self.signed,Path(temporary)/'report.json',{'trust_roots':[str(self.trust)],'revocation_mode':'require',**extra})

    def test_missing_revocation_is_not_a_trusted_result(self):
        report=self.verify();self.assertTrue(report['all_integrity_ok']);self.assertFalse(report['all_chains_trusted'])

    def test_https_ocsp_good_and_revoked_responses_are_cryptographically_checked(self):
        options={'allow_revocation_network':True,'revocation_endpoints':[{'kind':'ocsp','url':self.base+'/ocsp'}]}
        good=self.verify(**options);self.assertTrue(good['all_chains_trusted'],good)
        self.assertEqual(good['signatures'][0]['revocation']['status'],'good')
        type(self).revoked=True
        revoked=self.verify(**options);self.assertTrue(revoked['all_integrity_ok']);self.assertFalse(revoked['all_chains_trusted'])
        self.assertEqual(revoked['signatures'][0]['revocation']['status'],'revoked')
        self.assertEqual([c[:2] for c in self.calls],[('POST','/ocsp')]*2)

    def test_https_crl_good_revoked_and_expired_are_distinct(self):
        options={'allow_revocation_network':True,'revocation_endpoints':[{'kind':'crl','url':self.base+'/crl'}]}
        self.assertTrue(self.verify(**options)['all_chains_trusted'])
        type(self).revoked=True;self.assertFalse(self.verify(**options)['all_chains_trusted'])
        type(self).revoked=False;type(self).stale=True;self.assertFalse(self.verify(**options)['all_chains_trusted'])

    def test_network_requires_consent_and_never_follows_redirect(self):
        options={'revocation_endpoints':[{'kind':'crl','url':self.base+'/crl'}]}
        report=self.verify(**options);self.assertFalse(report['all_chains_trusted']);self.assertEqual(self.calls,[])
        type(self).redirect=True
        report=self.verify(**options,allow_revocation_network=True);self.assertFalse(report['all_chains_trusted']);self.assertEqual(len(self.calls),1)

    def test_real_https_tsa_pades_lt_embeds_validation_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/'lt.pdf';before=hashlib.sha256(self.source.read_bytes()).digest()
            signatures.sign_pdf(self.source,target,{**self.sign_options(),'profile':'B-LT','tsa_url':self.base+'/tsa',
                'allow_revocation_network':True,'revocation_endpoints':[{'kind':'crl','url':self.base+'/crl'}]})
            with target.open('rb') as stream:
                reader=PdfFileReader(stream);self.assertTrue(reader.root['/DSS']['/CRLs']);self.assertTrue(reader.root['/DSS']['/Certs'])
            report=signatures.verify_pdf(target,Path(temporary)/'verify.json',{'trust_roots':[str(self.trust)]})
            self.assertTrue(report['all_integrity_ok']);self.assertTrue(report['signatures'][0]['timestamp']['trusted'])
            self.assertEqual(before,hashlib.sha256(self.source.read_bytes()).digest())
            for method,path,body in self.calls:
                if path=='/tsa':self.assertNotIn(b'%PDF',body);self.assertEqual(method,'POST')

    def test_real_pades_lta_document_timestamp_and_offline_ades_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/'lta.pdf'
            signatures.sign_pdf(self.source,target,{**self.sign_options(),'profile':'B-LTA','tsa_url':self.base+'/tsa',
                'allow_revocation_network':True,'revocation_endpoints':[{'kind':'crl','url':self.base+'/crl'}]})
            with target.open('rb') as stream:
                reader=PdfFileReader(stream)
                self.assertEqual(len(reader.embedded_signatures),2)
                self.assertEqual(str(reader.embedded_signatures[1].sig_object['/Type']),'/DocTimeStamp')
                result=validation.lta_status(reader.embedded_signatures[0],[asn1x509.Certificate.load(self.ca.public_bytes(serialization.Encoding.DER))])
                self.assertTrue(result['passed'],result)
            report=signatures.verify_pdf(target,Path(temporary)/'report.json',{'trust_roots':[str(self.trust)],'validate_lta':True})
            self.assertTrue(report['all_integrity_ok'],report)
            self.assertTrue(report['all_chains_trusted'],report)
            self.assertEqual(report['signatures'][1]['kind'],'document-timestamp')
            self.assertTrue(report['signatures'][0]['long_term_validation']['passed'])

if __name__=='__main__':unittest.main()
