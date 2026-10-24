import base64
from email.parser import BytesParser
from email.policy import default
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
import signature_requests as adapter


class SignatureRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.pdf=self.root/'document.pdf';self.draft=self.root/'draft.json'
        with fitz.open() as pdf: pdf.new_page().insert_text((30,50),'Private attachment fixture');pdf.save(self.pdf)
        self.options={'signers':[{'name':'Local Test','email_address':'test@example.invalid'}],
            'test_mode':True,'fields':[{'page':1,'x':50,'y':100,'width':200,'height':40,'signer':0,'type':'signature'}]}
        self.record=adapter.prepare_request(self.pdf,self.draft,self.options)
        self.requests=[];self.response_code=200;owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self): self.respond(b'')
            def do_POST(self): self.respond(self.rfile.read(int(self.headers['Content-Length'])))
            def respond(self,body):
                owner.requests.append((self.command,self.path,dict(self.headers),body))
                self.send_response(owner.response_code)
                if owner.response_code==302:self.send_header('Location','http://127.0.0.1:1/credential-trap')
                self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'signature_request':{'signature_request_id':'fixture-id','test_mode':True,
                    'is_complete':False,'has_error':False,'signatures':[{'signer_name':'Local Test',
                    'signer_email_address':'test@example.invalid','status_code':'awaiting_signature'}],
                    'signing_url':'https://must-not-be-persisted.invalid'}}).encode())
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def send_options(self):return {'api_key':'local-contract-secret','draft':str(self.draft),'confirm_send':True,
        'confirmed_sha256':self.record['input_sha256'],'confirmed_draft_sha256':hashlib.sha256(self.draft.read_bytes()).hexdigest()}

    def test_preparation_never_uses_network_and_records_exact_attachment(self):
        self.assertEqual(self.requests,[])
        self.assertFalse(self.record['network_access'])
        self.assertEqual(self.record['input_sha256'],hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        self.assertEqual(self.record['configuration']['fields'][0]['signer'],'0')
        self.assertNotIn('api_key',self.draft.read_text())

    def test_actual_http_multipart_contract_and_allowlisted_result(self):
        output=self.root/'sent.json'
        with patch.object(adapter,'BASE_URL',self.url):result=adapter.send_request(self.pdf,output,self.send_options())
        method,path,headers,body=self.requests[0]
        self.assertEqual((method,path),('POST','/signature_request/send'))
        self.assertEqual(headers['Authorization'],'Basic '+base64.b64encode(b'local-contract-secret:').decode())
        message=BytesParser(policy=default).parsebytes(('Content-Type: '+headers['Content-Type']+'\r\n\r\n').encode()+body)
        fields={part.get_param('name',header='content-disposition'):part.get_payload(decode=True) for part in message.iter_parts()}
        self.assertEqual(fields['files[0]'],self.pdf.read_bytes())
        self.assertEqual(fields['test_mode'],b'1')
        self.assertEqual(fields['signers[0][email_address]'],b'test@example.invalid')
        self.assertEqual(json.loads(fields['form_fields_per_document'])[0]['type'],'signature')
        self.assertEqual(result['signature_request_id'],'fixture-id')
        self.assertNotIn('local-contract-secret',output.read_text());self.assertNotIn('signing_url',output.read_text())

    def test_status_get_and_invalid_request_path(self):
        with patch.object(adapter,'BASE_URL',self.url):
            result=adapter.request_status(self.pdf,self.root/'status.json',{'request_id':'fixture-id','api_key':'secret'})
            with self.assertRaises(ValueError):adapter.request_status(self.pdf,self.root/'bad.json',{'request_id':'../send','api_key':'secret'})
        self.assertEqual(self.requests[0][:2],('GET','/signature_request/fixture-id'))
        self.assertFalse(result['is_complete']);self.assertEqual(len(self.requests),1)

    def test_changed_attachment_draft_missing_consent_and_existing_output_do_not_send(self):
        for changes in ({'confirm_send':False},{'confirmed_sha256':'0'*64},{'confirmed_draft_sha256':'0'*64}):
            with patch.object(adapter,'BASE_URL',self.url),self.assertRaises(ValueError):
                adapter.send_request(self.pdf,self.root/'no.json',{**self.send_options(),**changes})
        output=self.root/'existing.json';output.write_text('keep')
        with patch.object(adapter,'BASE_URL',self.url),self.assertRaises(FileExistsError):adapter.send_request(self.pdf,output,self.send_options())
        self.assertEqual(self.requests,[]);self.assertEqual(output.read_text(),'keep')

    def test_redirect_auth_failure_and_rate_limit_are_never_retried(self):
        for status in (302,401,429):
            if self.draft.exists():self.draft.unlink()
            self.record=adapter.prepare_request(self.pdf,self.draft,self.options)
            self.response_code=status
            with patch.object(adapter,'BASE_URL',self.url),self.assertRaises(ValueError):
                adapter.send_request(self.pdf,self.root/'no.json',self.send_options())
        self.assertEqual(len(self.requests),3);self.assertFalse((self.root/'no.json').exists())

    def test_durable_attempt_receipt_prevents_duplicate_after_success_and_failure(self):
        with patch.object(adapter,'BASE_URL',self.url):
            adapter.send_request(self.pdf,self.root/'sent.json',self.send_options())
            with self.assertRaisesRegex(ValueError,'tentativa'):adapter.send_request(self.pdf,self.root/'again.json',self.send_options())
        receipts=list(self.root.glob('.pdf-signature-attempt-*.json'));self.assertEqual(len(receipts),1)
        record=json.loads(receipts[0].read_text());self.assertEqual(record['state'],'confirmed')
        self.assertEqual(record['signature_request_id'],'fixture-id');self.assertEqual(receipts[0].stat().st_mode&0o777,0o600)
        self.assertNotIn('secret',receipts[0].read_text());self.assertNotIn('example.invalid',receipts[0].read_text())
        self.assertEqual(len(self.requests),1)

    def test_lost_response_still_blocks_second_post(self):
        async def disconnected(*args):raise RuntimeError('Response unknown')
        with patch.object(adapter,'_call',disconnected),self.assertRaises(RuntimeError):adapter.send_request(self.pdf,self.root/'sent.json',self.send_options())
        with patch.object(adapter,'BASE_URL',self.url),self.assertRaisesRegex(ValueError,'tentativa'):adapter.send_request(self.pdf,self.root/'again.json',self.send_options())
        self.assertEqual(self.requests,[])
        record=json.loads(next(self.root.glob('.pdf-signature-attempt-*.json')).read_text())
        self.assertEqual(record['state'],'response_not_confirmed')

    def test_missing_signature_field_or_page_refused(self):
        for options in ({**self.options,'fields':[]},{**self.options,'fields':[{**self.options['fields'][0],'page':3}]},
                        {**self.options,'fields':[{**self.options['fields'][0],'type':'date_signed'}]}):
            with self.assertRaises(ValueError):adapter.prepare_request(self.pdf,self.root/'bad.json',options)
        self.assertEqual(self.requests,[])

    def test_owner_only_encryption_is_refused_despite_open_without_user_password(self):
        protected=self.root/'owner-only.pdf'
        with fitz.open(self.pdf) as document:
            document.save(protected,encryption=fitz.PDF_ENCRYPT_AES_256,owner_pw='synthetic-owner-secret',user_pw='',permissions=fitz.PDF_PERM_PRINT)
        with fitz.open(protected) as document:
            self.assertFalse(document.needs_pass);self.assertFalse(document.is_encrypted)
            self.assertTrue(document.metadata['encryption'])
        with self.assertRaisesRegex(ValueError,'não criptografada'):
            adapter.prepare_request(protected,self.root/'no.json',self.options)
        self.assertFalse((self.root/'no.json').exists());self.assertEqual(self.requests,[])

    def test_entire_field_must_fit_visible_page_at_provider_72dpi(self):
        for field in ({'x':590,'y':50,'width':10,'height':20},
                      {'x':50,'y':830,'width':100,'height':20}):
            with self.assertRaisesRegex(ValueError,'ultrapassa'):
                adapter.prepare_request(self.pdf,self.root/'out.json',{
                    **self.options,'fields':[{**self.options['fields'][0],**field}]})
        rotated=self.root/'rotated.pdf'
        with fitz.open() as document:
            page=document.new_page(width=612,height=792);page.set_rotation(90);document.save(rotated)
        before=rotated.read_bytes()
        result=adapter.prepare_request(rotated,self.root/'landscape.json',{
            **self.options,'fields':[{**self.options['fields'][0],'x':700,'y':500,'width':50,'height':40}]})
        self.assertEqual(result['pages'][0]['width_points'],792)
        self.assertEqual(rotated.read_bytes(),before)
        self.assertEqual(self.requests,[])

if __name__=='__main__':unittest.main()
