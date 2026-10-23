"""Real cryptographic signatures, no network and no permanent test credentials."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import fitz
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import pdf_signatures as signatures


class SignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='pdf signatures ')
        cls.root = Path(cls.temporary.name)
        now = dt.datetime.now(dt.timezone.utc)
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.ca_key = ca_key
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PDF temporary test root')])
        cls.ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
            .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-dt.timedelta(days=1)).not_valid_after(now+dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False), critical=True)
            .sign(ca_key, hashes.SHA256()))
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PDF temporary test signer')])
        cls.cert = (x509.CertificateBuilder().subject_name(name).issuer_name(ca_name)
            .public_key(cls.key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-dt.timedelta(days=1)).not_valid_after(now+dt.timedelta(days=10))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True,True,False,False,False,False,False,False,False), critical=True)
            .sign(ca_key, hashes.SHA256()))
        cls.pin = 'transient-test-PIN-987'
        cls.p12 = cls.root/'local certificate.p12'
        cls.p12.write_bytes(pkcs12.serialize_key_and_certificates(b'PDF',cls.key,cls.cert,[cls.ca],
            serialization.BestAvailableEncryption(cls.pin.encode())))
        cls.trust = cls.root/'explicit root.pem'
        cls.trust.write_bytes(cls.ca.public_bytes(serialization.Encoding.PEM))
        cls.source = cls.root/'original.pdf'
        with fitz.open() as doc:
            page=doc.new_page(); page.insert_text((50,70),'Cryptographic integrity fixture.')
            doc.save(cls.source)
        cls.original = cls.source.read_bytes()
        cls.signed = cls.root/'signed.pdf'
        signatures.sign_pdf(cls.source,cls.signed,{'certificate':str(cls.p12),'certificate_password':cls.pin})

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def report(self, source=None, roots=True):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'report.json'
            # A successful test must not depend on DNS, revocation or AIA fetches.
            with patch('socket.socket.connect', side_effect=AssertionError('Unexpected network access')):
                report=signatures.verify_pdf(source or self.signed,output,
                    {'trust_roots':[str(self.trust)] if roots is True else [str(root) for root in roots]} if roots else {})
            self.assertEqual(report,json.loads(output.read_text()))
            self.assertNotIn(self.pin,output.read_text())
            return report

    def test_real_signature_trusted_explicit_root_and_original_preserved(self):
        report=self.report()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertTrue(report['all_integrity_ok'],report)
        self.assertTrue(report['all_chains_trusted'],report)
        self.assertTrue(report['all_cover_current_file'],report)
        self.assertEqual(report['signatures'][0]['subfilter'],'/ETSI.CAdES.detached')
        self.assertEqual(len(report['signatures'][0]['chain']),2)
        self.assertEqual(report['revocation_status'],'not_checked_offline')
        self.assertEqual(report['identity_assurance'],'not_assessed')

    def test_valid_signature_is_untrusted_without_explicit_roots(self):
        report=self.report(roots=False)
        self.assertTrue(report['all_integrity_ok'])
        self.assertFalse(report['all_chains_trusted'])
        self.assertEqual(report['trust_anchors'],[])

    def test_changed_signed_bytes_fail_integrity(self):
        with tempfile.TemporaryDirectory() as temporary:
            data=self.signed.read_bytes()
            self.assertIn(b'/MediaBox[0 0 595 842]',data)
            changed=data.replace(b'/MediaBox[0 0 595 842]',b'/MediaBox[0 0 594 842]',1)
            tampered=Path(temporary)/'tampered.pdf'; tampered.write_bytes(changed)
            report=self.report(tampered)
            self.assertFalse(report['all_integrity_ok'])
            self.assertTrue(any(f['rule']=='signature-integrity' for f in report['findings']))

    def test_unsigned_file_not_reported_as_verified(self):
        report=self.report(self.source)
        self.assertEqual(report['signature_count'],0)
        self.assertFalse(report['all_integrity_ok'])

    def test_wrong_pin_is_not_echoed_or_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'wrong.pdf'
            with self.assertRaises(ValueError) as result:
                signatures.sign_pdf(self.source,output,{'certificate':str(self.p12),'certificate_password':'never-log-this-pin'})
            self.assertNotIn('never-log-this-pin',str(result.exception))
            self.assertFalse(output.exists())

    def test_output_is_never_overwritten(self):
        before=self.signed.read_bytes()
        with self.assertRaises(FileExistsError):
            signatures.sign_pdf(self.source,self.signed,{'certificate':str(self.p12),'certificate_password':self.pin})
        self.assertEqual(before,self.signed.read_bytes())

    def test_fifo_certificate_trust_root_and_pdf_fail_without_hanging(self):
        engine=Path(__file__).resolve().parents[1]/'engine/pdf_engine.py'
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); fifo=root/'blocked.p12';os.mkfifo(fifo)
            environment={**os.environ,'PDF_OPTIONS_STDIN':'1'}
            cases=[
                ('digital-sign',self.source,{'certificate':str(fifo),'certificate_password':'transient'}),
                ('verify-signatures',self.signed,{'trust_roots':[str(fifo)]}),
                ('digital-sign',fifo,{'certificate':str(self.p12),'certificate_password':self.pin}),
                ('verify-signatures',fifo,{}),
            ]
            for index,(operation,source,options) in enumerate(cases):
                with self.subTest(operation=operation,source=str(source),index=index):
                    output=root/f'result-{index}.pdf'
                    result=subprocess.run([sys.executable,str(engine),operation,str(source),'--output',str(output)],
                        input=json.dumps(options),env=environment,capture_output=True,text=True,timeout=10)
                    self.assertNotEqual(result.returncode,0)
                    self.assertNotIn(self.pin,result.stdout+result.stderr)
                    self.assertFalse(output.exists())

    def test_final_symlinks_are_rejected_without_reading_certificate_or_pdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            certificate=root/'identity.p12';certificate.symlink_to(self.p12)
            pdf=root/'source.pdf';pdf.symlink_to(self.source)
            with self.assertRaises(ValueError): signatures._bounded_file(certificate)
            with self.assertRaises(ValueError):
                with signatures._snapshot(pdf): self.fail('A symlink must not yield document bytes')
            self.assertEqual(self.source.read_bytes(),self.original)
            self.assertTrue(certificate.is_symlink())
            self.assertTrue(pdf.is_symlink())

    def test_cli_refuses_certificate_pin_in_argv_direct_or_nested(self):
        engine=Path(__file__).resolve().parents[1]/'engine/pdf_engine.py'
        environment=dict(os.environ);environment.pop('PDF_OPTIONS_STDIN',None)
        fake_pin='must-not-appear-in-diagnostics'
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'forbidden.pdf'
            for operation,options in [('digital-sign',{'certificate_password':fake_pin}),
                    ('workflow',{'steps':[{'operation':'digital-sign','options':{'certificate_password':fake_pin}}]})]:
                result=subprocess.run([sys.executable,str(engine),operation,str(self.source),'--output',str(output),
                    '--options',json.dumps(options)],env=environment,capture_output=True,text=True,timeout=15)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('stdin',result.stderr)
                self.assertNotIn(fake_pin,result.stdout+result.stderr)
                self.assertFalse(output.exists())

    def test_unsigned_timestamp_endpoint_rejected_before_network(self):
        for url in ('http://example.com','https://user:secret@example.com','https://example.com/#secret'):
            with self.assertRaises(ValueError): signatures._timestamper(url)

    def issue(self, expired=False, self_signed=False, timestamp=False):
        now=dt.datetime.now(dt.timezone.utc)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Temporary '+('TSA' if timestamp else 'signer'))])
        builder=(x509.CertificateBuilder().subject_name(name)
            .issuer_name(name if self_signed else self.ca.subject)
            .public_key(self.key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-dt.timedelta(days=30))
            .not_valid_after(now+dt.timedelta(days=-1 if expired else 10))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
            .add_extension(x509.KeyUsage(True,True,False,False,False,False,False,False,False),critical=True))
        if timestamp: builder=builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]),critical=True)
        return builder.sign(self.key if self_signed else self.ca_key,hashes.SHA256())

    def raw_sign(self, certificate, output):
        # Fixtures bypass the application's expiry guard to prove actual verifier
        # behaviour on historical signatures, not merely the date helper.
        from pyhanko.sign import signers, fields
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        raw=pkcs12.serialize_key_and_certificates(b'test',self.key,certificate,[self.ca],serialization.NoEncryption())
        signer=signers.SimpleSigner.load_pkcs12_data(raw,other_certs=[])
        with self.source.open('rb') as source, output.open('wb') as target:
            signers.PdfSigner(signers.PdfSignatureMetadata(field_name='Test',subfilter=fields.SigSeedSubFilter.PADES),
                signer=signer).sign_pdf(IncrementalPdfFileWriter(source),output=target)

    def test_expired_certificate_keeps_integrity_but_fails_current_trust(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'expired.pdf'
            self.raw_sign(self.issue(expired=True),output)
            report=self.report(output)
            self.assertTrue(report['all_integrity_ok'])
            self.assertFalse(report['all_chains_trusted'])
            self.assertTrue(report['signatures'][0]['certificate']['expired'])
            self.assertTrue(any(f['rule']=='certificate-validity' for f in report['findings']))

    def test_explicit_self_signed_trust_is_not_identity_certification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); certificate=self.issue(self_signed=True)
            anchor=root/'self.pem';anchor.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            output=root/'self.pdf';self.raw_sign(certificate,output)
            report=self.report(output,roots=[anchor])
            self.assertTrue(report['all_integrity_ok'])
            self.assertTrue(report['all_chains_trusted'])
            self.assertTrue(report['signatures'][0]['certificate']['self_signed'])
            self.assertEqual(report['identity_assurance'],'not_assessed')

    def test_second_signature_preserves_prior_revision_and_reports_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'twice.pdf'
            signatures.sign_pdf(self.signed,output,{'certificate':str(self.p12),'certificate_password':self.pin,'field_name':'Second'})
            report=self.report(output)
            self.assertEqual(report['signature_count'],2)
            self.assertTrue(report['all_integrity_ok'])
            self.assertTrue(report['all_chains_trusted'])
            self.assertFalse(report['all_cover_current_file'])
            self.assertFalse(report['signatures'][0]['unchanged_since_signing'])
            self.assertTrue(report['signatures'][1]['unchanged_since_signing'])

    def test_timestamp_token_is_cryptographically_verified_offline(self):
        from asn1crypto import keys, x509 as asn1x509
        from pyhanko.sign.timestamps import DummyTimeStamper
        certificate=self.issue(timestamp=True)
        stamp=DummyTimeStamper(asn1x509.Certificate.load(certificate.public_bytes(serialization.Encoding.DER)),
            keys.PrivateKeyInfo.load(self.key.private_bytes(serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,serialization.NoEncryption())))
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'timestamped.pdf'
            with patch.object(signatures,'_timestamper',return_value=stamp):
                signatures.sign_pdf(self.source,output,{'certificate':str(self.p12),'certificate_password':self.pin,
                    'tsa_url':'https://explicit-test-only.invalid'})
            report=self.report(output)
            timestamp=report['signatures'][0]['timestamp']
            self.assertTrue(timestamp['intact'])
            self.assertTrue(timestamp['cryptographically_valid'])
            self.assertTrue(timestamp['trusted'])

if __name__=='__main__': unittest.main()
