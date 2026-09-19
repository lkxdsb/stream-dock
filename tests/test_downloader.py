import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fetchers.downloader import download_media


class DownloaderResumeTests(unittest.TestCase):
    def test_real_http_download_rejects_content_length_over_budget(self):
        payload = b'x' * 64

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args): return
            def do_GET(self):
                self.send_response(200); self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch('fetchers.downloader.MAX_REMOTE_DOWNLOAD_BYTES', 16):
                destination = Path(tmp) / 'media.bin'
                with self.assertRaisesRegex(RuntimeError, '下载上限'):
                    download_media(f'http://127.0.0.1:{server.server_port}/media', destination, user_agent='test')
                self.assertFalse(destination.exists())
        finally:
            server.shutdown(); server.server_close()

    def test_real_http_download_resumes_partial_file_with_range(self):
        payload = b'StreamDock-real-resume-' * 100_000

        class Handler(BaseHTTPRequestHandler):
            requests = 0

            def log_message(self, *_args):
                return

            def do_GET(self):
                Handler.requests += 1
                if Handler.requests == 1:
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload[:len(payload) // 2])
                    self.wfile.flush()
                    self.connection.shutdown(1)
                    return
                start = int(self.headers['Range'].split('=', 1)[1].split('-', 1)[0])
                self.send_response(206)
                self.send_header('Content-Length', str(len(payload) - start))
                self.send_header('Content-Range', f'bytes {start}-{len(payload) - 1}/{len(payload)}')
                self.end_headers()
                self.wfile.write(payload[start:])

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                destination = Path(tmp) / 'media.bin'
                url = f'http://127.0.0.1:{server.server_port}/media'
                with self.assertRaises(Exception):
                    download_media(url, destination, user_agent='StreamDock test')
                partial = destination.with_name(f'{destination.name}.download')
                self.assertGreater(partial.stat().st_size, 0)

                download_media(url, destination, user_agent='StreamDock test')

                self.assertEqual(destination.read_bytes(), payload)
                self.assertFalse(partial.exists())
                self.assertEqual(Handler.requests, 2)
        finally:
            server.shutdown(); server.server_close()
