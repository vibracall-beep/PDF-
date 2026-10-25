"""The URL conversion route must load relative assets from a real local server."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import io
import sys
import tempfile
import threading
import unittest

import fitz
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run


class HTMLURLIntegrationTests(unittest.TestCase):
    def test_http_page_stylesheet_and_relative_image_are_rendered(self):
        image = io.BytesIO()
        with Image.new('RGB', (40, 20), (20, 180, 70)) as logo: logo.save(image, format='PNG')
        assets = {
            '/document/index.html': ('text/html; charset=utf-8', '<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="print.css"><h1>Relatório URL — ação</h1><p>Documento por endereço HTTP.</p><img src="logo.png" width="120" height="60">'.encode()),
            '/document/print.css': ('text/css', b'h1 {color:#cc2200; font-family:sans-serif; font-size:24px} body {margin:40px}'),
            '/document/logo.png': ('image/png', image.getvalue()),
        }
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                content_type, data = assets.get(self.path, ('text/plain', b'not found'))
                self.send_response(200 if self.path in assets else 404)
                self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(len(data))); self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / 'url.pdf'
                run('html', [f'http://127.0.0.1:{server.server_port}/document/index.html'], target, {'paper': 'A4', 'landscape': True})
                self.assertTrue(set(assets).issubset(set(requests)))
                with fitz.open(target) as document:
                    self.assertEqual(len(document), 1)
                    self.assertGreater(document[0].rect.width, document[0].rect.height)
                    self.assertIn('Relatório URL — ação', document[0].get_text())
                    self.assertIn('Documento por endereço HTTP.', document[0].get_text())
                    spans = [span for block in document[0].get_text('dict')['blocks'] if block['type'] == 0 for line in block['lines'] for span in line['spans']]
                    heading = next(span for span in spans if 'Relatório URL' in span['text'])
                    self.assertEqual(heading['color'], 0xCC2200)
                    images = document[0].get_image_info()
                    self.assertEqual(len(images), 1)
                    rect = fitz.Rect(images[0]['bbox']); self.assertAlmostEqual(rect.width / rect.height, 2)
                    pixel = document[0].get_pixmap(clip=rect).pixel(5, 5)
                    self.assertEqual(pixel, (20, 180, 70))
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
