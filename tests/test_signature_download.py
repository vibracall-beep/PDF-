"""Download contracts use a real loopback server, never a provider account.

The PDF fixture carries a real temporary PAdES signature. Tests compare its bytes
and independently verify that signature after download; remote completion alone
never certifies the PDF's cryptographic status.
"""
import base64
import datetime as dt
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import fitz
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import signature_requests as adapter
import pdf_signatures
import pdf_engine


class SignatureDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        root = Path(cls.fixture.name)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Download local fixture')])
        now = dt.datetime.now(dt.timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-dt.timedelta(days=1)).not_valid_after(now+dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
            .sign(key, hashes.SHA256()))
        credential = root/'signer.p12'
        credential.write_bytes(pkcs12.serialize_key_and_certificates(b'fixture', key, certificate, [],
            serialization.BestAvailableEncryption(b'local-only-pin')))
        cls.trust = root/'trust.pem'; cls.trust.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        source = root/'source.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((40, 60), 'Completed document for real byte-preserving download.')
            pdf.save(source)
        cls.plain_pdf = source.read_bytes()
        signed = root/'signed.pdf'
        pdf_signatures.sign_pdf(source, signed, {'certificate': str(credential), 'certificate_password': 'local-only-pin'})
        cls.signed_pdf = signed.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.output = self.root/'received.pdf'
        self.requests = []; self.response_code = 200; self.status_code = 200
        self.content_type = 'application/pdf'; self.encoding = None; self.length = None; self.invalid_status_json = False
        self.payload = self.signed_pdf; self.response_id = 'fixture-id'; self.complete = True; self.failed = False
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                owner.requests.append((self.command, self.path, dict(self.headers)))
                files = self.path.startswith('/signature_request/files/')
                if files:
                    status = owner.response_code; payload = owner.payload; mime = owner.content_type
                else:
                    status = owner.status_code; mime = 'application/json'
                    payload = json.dumps({'signature_request': {
                        'signature_request_id': owner.response_id, 'is_complete': owner.complete,
                        'has_error': owner.failed, 'test_mode': True, 'signatures': [],
                        'files_url': 'http://127.0.0.1:1/never-follow-with-credentials',
                        'signing_url': 'https://never-follow.invalid'}}).encode()
                if not files and owner.invalid_status_json: payload = b'not-json'
                self.send_response(status)
                self.send_header('Content-Type', mime)
                if files and owner.encoding: self.send_header('Content-Encoding', owner.encoding)
                if files and owner.length is not None: self.send_header('Content-Length', str(owner.length))
                if status == 302: self.send_header('Location', 'http://127.0.0.1:1/never-follow-with-credentials')
                self.end_headers()
                try: self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.options = {'request_id': 'fixture-id', 'confirm_download': True, 'api_key': 'local-download-secret'}

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def download(self, options=None, engine=False):
        with patch.object(adapter, 'BASE_URL', self.url):
            if engine:
                return pdf_engine.run('signature-request-download', ['/dev/null'], self.output, options or self.options)
            return adapter.download_request('/dev/null', self.output, options or self.options)

    def assert_no_partial(self):
        self.assertFalse(os.path.lexists(self.output))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_signed_bytes_are_preserved_and_signature_independently_validates(self):
        result = self.download()
        self.assertEqual(self.output.read_bytes(), self.signed_pdf)
        self.assertEqual(result['output_sha256'], hashlib.sha256(self.signed_pdf).hexdigest())
        self.assertEqual(result['output_bytes'], len(self.signed_pdf)); self.assertEqual(result['pages'], 1)
        self.assertFalse(result['cryptographic_signatures_verified'])
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        with patch('socket.socket.connect', side_effect=AssertionError('Verification must remain offline')):
            report = pdf_signatures.verify_pdf(self.output, self.root/'verification.json', {'trust_roots': [str(self.trust)]})
        self.assertTrue(report['all_integrity_ok'], report)
        self.assertTrue(report['all_cover_current_file'], report)
        self.assertEqual([item[:2] for item in self.requests], [
            ('GET', '/signature_request/fixture-id'), ('GET', '/signature_request/files/fixture-id?file_type=pdf')])
        for _, _, headers in self.requests:
            self.assertEqual(headers['Authorization'], 'Basic '+base64.b64encode(b'local-download-secret:').decode())
        self.assertEqual(self.requests[-1][2]['Accept-Encoding'], 'identity')
        self.assertNotIn('local-download-secret', json.dumps(result)); self.assertNotIn('files_url', result)

    def test_engine_dispatch_publishes_pdf_with_exact_bytes(self):
        self.download(engine=True)
        self.assertEqual(self.output.read_bytes(), self.signed_pdf)
        self.assertEqual(list(self.root.iterdir()), [self.output])

    def test_incomplete_error_and_wrong_id_stop_before_file_request(self):
        for complete, failed, identifier in [(False, False, 'fixture-id'), (True, True, 'fixture-id'), (True, False, 'someone-else')]:
            self.complete, self.failed, self.response_id = complete, failed, identifier
            self.requests.clear()
            with self.assertRaises(ValueError): self.download()
            self.assertEqual(len(self.requests), 1); self.assert_no_partial()

    def test_failed_status_consultation_does_not_claim_that_an_email_was_sent(self):
        self.invalid_status_json = True
        with self.assertRaises(RuntimeError) as result: self.download()
        self.assertNotIn('envio pode ter ocorrido', str(result.exception))
        self.assertEqual(len(self.requests), 1); self.assert_no_partial()

    def test_malformed_service_state_cannot_be_interpreted_as_completed(self):
        for complete, failed in [(True, "true"), (1, False), (True, 0), (None, False)]:
            self.complete, self.failed = complete, failed
            self.requests.clear()
            with self.assertRaisesRegex(ValueError, 'estados'): self.download()
            self.assertEqual(len(self.requests), 1); self.assert_no_partial()

    def test_missing_consent_invalid_id_and_existing_output_never_access_network(self):
        for changes in [{'confirm_download': False}, {'request_id': '../other'}, {'request_id': 'a?file_type=zip'}, {'request_id': ''}]:
            with self.assertRaises(ValueError): self.download({**self.options, **changes})
        self.output.write_bytes(b'keep this file')
        with self.assertRaises(FileExistsError): self.download()
        self.assertEqual(self.output.read_bytes(), b'keep this file'); self.assertEqual(self.requests, [])

    def test_redirects_auth_errors_rate_limits_and_not_ready_never_retry(self):
        for code in [302, 401, 409, 429, 500]:
            self.response_code = code; self.requests.clear()
            with self.assertRaises(ValueError): self.download()
            self.assertEqual(len(self.requests), 2); self.assert_no_partial()

    def test_mime_transport_encoding_and_non_pdf_are_refused(self):
        for mime, encoding, payload in [('text/html', None, self.signed_pdf), ('application/pdf', 'gzip', self.signed_pdf),
                                       ('application/pdf', None, b'not a PDF'), ('application/pdf', None, b'')]:
            self.content_type, self.encoding, self.payload = mime, encoding, payload
            with self.assertRaises(ValueError): self.download()
            self.assert_no_partial()

    def test_both_declared_and_streamed_size_limits_remove_temporaries(self):
        with patch.object(adapter, 'MAX_COMPLETED_PDF', 100):
            self.length = len(self.signed_pdf)
            with self.assertRaisesRegex(ValueError, 'excede'): self.download()
            self.assert_no_partial()
            self.length = None
            with self.assertRaisesRegex(ValueError, 'excede'): self.download()
            self.assert_no_partial()

    def test_truncated_network_transfer_has_no_output_and_no_secret_in_error(self):
        self.length = len(self.signed_pdf)+20
        with self.assertRaises(RuntimeError) as result: self.download()
        self.assertNotIn(self.options['api_key'], str(result.exception)); self.assert_no_partial()

    def test_repaired_malformed_or_encrypted_document_is_not_published(self):
        encrypted = self.root/'protected.pdf'
        with fitz.open(stream=self.plain_pdf, filetype='pdf') as pdf:
            pdf.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='synthetic-owner', user_pw='', permissions=fitz.PDF_PERM_PRINT)
        protected = encrypted.read_bytes(); encrypted.unlink()
        for payload in [b'%PDF-1.7\nnot a complete PDF\n', self.plain_pdf.split(b'startxref')[0], protected]:
            self.payload = payload
            with self.assertRaises(ValueError): self.download()
            self.assert_no_partial()

    def test_concurrent_destination_is_never_replaced(self):
        real_link = os.link
        def race(source, destination, **kwargs):
            if Path(destination) == self.output:
                self.output.write_bytes(b'concurrent document')
            return real_link(source, destination, **kwargs)
        with patch.object(adapter.os, 'link', race), self.assertRaises(FileExistsError): self.download()
        self.assertEqual(self.output.read_bytes(), b'concurrent document')
        self.assertEqual(list(self.root.iterdir()), [self.output])

    def test_cli_download_credentials_must_arrive_over_stdin(self):
        environment = dict(os.environ); environment.pop('PDF_OPTIONS_STDIN', None)
        result = subprocess.run([sys.executable, str(Path(pdf_engine.__file__)), 'signature-request-download', '/dev/null',
            '--output', str(self.output), '--options', json.dumps(self.options)], env=environment,
            capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stdin', result.stderr); self.assertNotIn(self.options['api_key'], result.stderr)
        self.assertEqual(self.requests, []); self.assert_no_partial()


if __name__ == '__main__': unittest.main()
