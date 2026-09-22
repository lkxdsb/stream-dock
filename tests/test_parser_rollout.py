import tempfile
import unittest
import os
import functools
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
import httpx
from cryptography.fernet import Fernet
from PIL import Image

from app import app, probe_stream_http_info
from fetchers.auth_context import AuthStore, cookie_jar, current_auth, use_auth, scoped_request
from fetchers.link_normalization import normalize_share_url
from fetchers.models import ImageAsset, MediaFetchResult, MediaStream
from fetchers.pipeline import resolve_media_selection
from fetchers.stream_identity import stream_id
from fetchers.diagnostic_download import validate_full_download


class ParserRolloutTests(unittest.TestCase):
    def test_weibo_share_variants_resolve_same_fid(self):
        expected = 'https://weibo.com/tv/show/1034:4418343294440212'
        self.assertEqual(normalize_share_url('复制 https://video.h5.weibo.cn/1034:4418343294440212/4418343899391020！'), expected)
        self.assertEqual(normalize_share_url('https://video.weibo.com/show?fid=1034%3A4418343294440212'), expected)
        with self.assertRaises(ValueError):
            normalize_share_url('https://video.h5.weibo.cn/no-fid/x')

    def test_tcn_redirect_rejects_unrelated_host(self):
        response = MagicMock(headers={'location': 'https://weibo.com.evil.invalid/video'})
        with patch('fetchers.link_normalization.requests.get', return_value=response):
            with self.assertRaises(ValueError):
                normalize_share_url('https://t.cn/audit')

    def test_stream_id_separates_same_label_codecs_and_survives_signed_query(self):
        avc = MediaStream('https://cdn.example/a.mp4?sig=old', 'video', 'mp4', 'avc', 1280, 720, 1_000_000, None, '高清')
        hevc = MediaStream('https://cdn.example/b.mp4?sig=old', 'video', 'mp4', 'hevc', 1280, 720, 1_000_000, None, '高清')
        refreshed = MediaStream('https://cdn.example/b.mp4?sig=new', 'video', 'mp4', 'hevc', 1280, 720, 1_000_000, None, '高清')
        self.assertNotEqual(stream_id(avc), stream_id(hevc))
        self.assertEqual(stream_id(hevc), stream_id(refreshed))
        result = MediaFetchResult('kuaishou', 'video', 'test', '', '', None, None,
                                  video_streams=[avc, refreshed], preferred_video=avc)
        self.assertEqual(resolve_media_selection(result, output_type='mp4', video_quality=stream_id(hevc)).video_stream, refreshed)

    def test_error_page_does_not_set_media_size(self):
        response = MagicMock(status_code=403, headers={'content-type': 'text/xml', 'content-length': '393'}, url='https://cdn.example/error')
        response.iter_content.return_value = iter([b'<?xml version="1.0"?><Error/>'])
        with patch('app.requests.get', return_value=response):
            info = probe_stream_http_info('https://cdn.example/video.mp4', headers={'Referer': 'https://www.bilibili.com/'})
        self.assertEqual(info['resourceStatus'], 'invalid')
        self.assertNotIn('contentLength', info)

    def test_range_total_not_prefix_length(self):
        response = MagicMock(status_code=206, headers={'content-type': 'video/mp4', 'content-range': 'bytes 0-1023/6283953', 'content-length': '1024'}, url='https://cdn.example/video.mp4')
        response.iter_content.return_value = iter([b'\0\0\0\x18ftyp' + b'a' * 1016])
        with patch('app.requests.get', return_value=response) as fetch:
            info = probe_stream_http_info('https://cdn.example/video.mp4', headers={'Referer': 'https://m.gifshow.com/'})
        self.assertEqual(info['contentLength'], 6283953)
        self.assertEqual(fetch.call_args.kwargs['headers']['Range'], 'bytes=0-1023')
        self.assertEqual(fetch.call_args.kwargs['headers']['Referer'], 'https://m.gifshow.com/')

    def test_auth_public_status_and_revocation_never_return_cookie(self):
        store = AuthStore()
        profile = store.put('bilibili', 'SESSDATA=secret')
        self.assertNotIn('secret', str(store.list_public()))
        self.assertEqual(store.get('bilibili', profile.id, 1), profile)
        store.put('bilibili', 'SESSDATA=new')
        with self.assertRaises(ValueError):
            store.get('bilibili', profile.id, 1)
        store.delete('bilibili')
        with self.assertRaises(ValueError):
            store.get('bilibili', profile.id)

    def test_auth_cookie_is_domain_scoped(self):
        store = AuthStore()
        profile = store.put('bilibili', 'SESSDATA=secret')
        jar = cookie_jar(profile)
        prepared = requests.Request('GET', 'https://api.bilibili.com/x').prepare()
        prepared.prepare_cookies(jar)
        self.assertIn('SESSDATA=secret', prepared.headers['Cookie'])
        other = requests.Request('GET', 'https://evilbilibili.com/x').prepare()
        other.prepare_cookies(jar)
        self.assertNotIn('Cookie', other.headers)
        with use_auth(profile):
            with patch('fetchers.auth_context.requests.get') as get:
                scoped_request('get', 'https://example.com/no-cookie')
                self.assertNotIn('cookies', get.call_args.kwargs)

    def test_persisted_auth_is_encrypted_and_versioned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.bin'
            key = Fernet.generate_key().decode()
            store = AuthStore(path, key)
            profile = store.put('douyin', 'sessionid=private', save=True)
            self.assertNotIn(b'private', path.read_bytes())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(AuthStore(path, key).get('douyin').id, profile.id)

    def test_full_download_uses_real_media_and_cleans_temp_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / 'sample.mp4'
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=320x240:d=1.5',
                            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1.5', '-shortest',
                            '-c:v', 'libx264', '-c:a', 'aac', str(media)], check=True)
            handler = functools.partial(SimpleHTTPRequestHandler, directory=directory)
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                stream = MediaStream(f'http://127.0.0.1:{server.server_port}/sample.mp4', 'video', 'mp4')
                result = MediaFetchResult('fixture', 'video', 'fixture', '', '', None, None,
                                          video_streams=[stream], preferred_video=stream)
                check = validate_full_download(result, user_agent='test', referer='http://127.0.0.1/')
                self.assertTrue(check['valid'])
                self.assertTrue(check['video']['hasVideo'])
                self.assertEqual(check['scope'], 'selected-stream-only')
            finally:
                server.shutdown()
                server.server_close()

    def test_full_hls_manifest_download_is_compared_to_playlist_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            playlist = Path(directory) / 'clip.m3u8'
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=2.5',
                            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2.5', '-shortest',
                            '-c:v', 'libx264', '-c:a', 'aac', '-f', 'hls', '-hls_time', '1',
                            '-hls_playlist_type', 'vod', str(playlist)], check=True)
            handler = functools.partial(SimpleHTTPRequestHandler, directory=directory)
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            Thread(target=server.serve_forever, daemon=True).start()
            try:
                stream = MediaStream(f'http://127.0.0.1:{server.server_port}/clip.m3u8', 'video', 'm3u8')
                result = MediaFetchResult('fixture', 'video', 'fixture', '', '', None, None,
                                          video_streams=[stream], preferred_video=stream)
                check = validate_full_download(result, user_agent='test', referer='http://127.0.0.1/')
                self.assertTrue(check['valid'])
                self.assertGreater(check['video']['durationSeconds'], 2)
            finally:
                server.shutdown()
                server.server_close()

    def test_full_image_collection_is_decoded_and_temp_files_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            Image.new('RGB', (24, 16), color='green').save(Path(directory) / 'page.png')
            handler = functools.partial(SimpleHTTPRequestHandler, directory=directory)
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            Thread(target=server.serve_forever, daemon=True).start()
            try:
                asset = ImageAsset(f'http://127.0.0.1:{server.server_port}/page.png')
                result = MediaFetchResult('fixture', 'images', 'fixture', '', '', None, None,
                                          image_assets=[asset])
                check = validate_full_download(result, user_agent='test', referer='http://127.0.0.1/')
                self.assertTrue(check['valid'])
                self.assertEqual(check['imageCount'], 1)
                self.assertEqual(check['images'][0]['format'], 'PNG')
                self.assertEqual(check['scope'], 'all-extracted-images')
            finally:
                server.shutdown()
                server.server_close()


class ParserApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_resource_sampling_keeps_platform_auth_context(self):
        store = AuthStore()
        profile = store.put('bilibili', 'SESSDATA=private')
        result = MediaFetchResult('bilibili', 'video', 'fixture', '', '', None, None)
        transport = httpx.ASGITransport(app=app)
        with patch('app.auth_store', store), patch('app.probe_media', return_value=result), \
             patch('app.serialize_probe_result', side_effect=lambda _: {
                 'success': True, 'authProfileId': current_auth().id if current_auth() else None,
             }):
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                response = await client.post('/api/media/probe', json={
                    'link': 'https://www.bilibili.com/video/BV1xx411c7mD',
                    'authProfileId': profile.id,
                })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['authProfileId'], profile.id)

    async def test_auth_status_api_never_echoes_cookie(self):
        store = AuthStore()
        transport = httpx.ASGITransport(app=app)
        with patch('app.auth_store', store):
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                put = await client.put('/api/media/auth/bilibili', json={'cookie': 'SESSDATA=supersecret'})
                self.assertEqual(put.status_code, 200)
                listed = await client.get('/api/media/auth')
                self.assertNotIn('supersecret', listed.text)
                self.assertTrue(any(row.get('configured') for row in listed.json()['profiles']))
                deleted = await client.delete('/api/media/auth/bilibili')
                self.assertEqual(deleted.status_code, 200)

    async def test_diagnostics_reject_unbounded_full_download(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.post('/api/media/diagnostics', json={
                'links': ['https://weibo.com/tv/show/1034:123'] * 3, 'fullDownload': True,
            })
        self.assertEqual(response.status_code, 400)

    async def test_server_probe_is_bounded_subprocess_and_auth_import_requires_https(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {
                'STREAMDOCK_MODE': 'server', 'STREAMDOCK_ALLOW_LAN_API': '0',
                'STREAMDOCK_API_TOKEN': 'parser-test-token-at-least-24-chars',
                'STREAMDOCK_TRUSTED_HOSTS': 'streamdock.test',
                'STREAMDOCK_ALLOWED_ORIGINS': 'http://streamdock.test',
                'STREAMDOCK_SERVER_OUTPUT_ROOT': directory,
            }
            with patch.dict(os.environ, env):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url='http://streamdock.test',
                                             headers={'Authorization': 'Bearer parser-test-token-at-least-24-chars'}) as client:
                    denied = await client.put('/api/media/auth/bilibili', json={'cookie': 'SESSDATA=private'})
                    result = await client.post('/api/media/probe', json={'link': 'not-a-link'})
                self.assertEqual(denied.status_code, 403)
                self.assertEqual(result.status_code, 200)
                self.assertFalse(result.json()['success'])
                self.assertIn('traceId', result.json())


if __name__ == '__main__':
    unittest.main()
