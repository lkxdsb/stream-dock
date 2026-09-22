import tempfile
import unittest
import os
import functools
import subprocess
import sys
import time
from concurrent.futures import Future
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from threading import Event
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
import httpx
from cryptography.fernet import Fernet
from PIL import Image

from app import app, probe_stream_http_info, serialize_probe_result
from fetchers.auth_context import AuthStore, browser_cookies, cookie_jar, current_auth, parse_cookie_file, use_auth, scoped_request
from fetchers.link_normalization import normalize_share_url
from fetchers.models import ImageAsset, MediaFetchResult, MediaStream
from fetchers.pipeline import resolve_media_selection
from fetchers.stream_identity import stream_id
from fetchers.diagnostic_download import validate_full_download
from fetchers.errors import MediaProbeError
from fetchers.browser_runtime import BrowserUnavailableError
from tasks.models import TaskKind, TaskStatus
from tasks.store import TaskStore
from error_catalog import classify_probe_exception


class ParserRolloutTests(unittest.TestCase):
    def test_typed_http_error_does_not_guess_cookie_expiry(self):
        response = requests.Response()
        response.status_code = 403
        info = classify_probe_exception(requests.HTTPError('403 Client Error', response=response))
        self.assertEqual(info['code'], 'upstream_access_rejected')
        self.assertFalse(info['retryable'])
        limited = requests.Response()
        limited.status_code = 429
        limited.headers['Retry-After'] = '12'
        info = classify_probe_exception(requests.HTTPError('429 Client Error', response=limited))
        self.assertEqual((info['code'], info['retryAfter']), ('rate_limited', 12))

    def test_browser_failure_keeps_sanitized_prior_stage(self):
        from fetchers.adapters.weibo import WeiboAdapter
        response = MagicMock(text='<html></html>', url='https://weibo.com/demo/post')
        with patch('fetchers.adapters.weibo.scoped_request', return_value=response), \
             patch('fetchers.adapters.weibo.capture_media_with_browser', side_effect=BrowserUnavailableError(['chromium missing'])):
            with self.assertRaises(BrowserUnavailableError) as captured:
                WeiboAdapter().fetch_media('https://weibo.com/demo/post')
        info = classify_probe_exception(captured.exception)
        self.assertEqual(info['code'], 'browser_unavailable')
        self.assertIn('http_parser:', info['causes'][0])

    def test_diagnostic_result_is_persisted_without_raw_link(self):
        from app import _run_media_diagnostic
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.json'
            store = TaskStore(storage_path=path)
            link = 'https://weibo.com/tv/show/1034:12345?credential=private'
            task = store.create(TaskKind.DIAGNOSTIC, '媒体解析诊断', {'inputIds': ['hash-only'], 'linkCount': 1})
            result = MediaFetchResult('weibo', 'video', 'fixture', '', '', None, None)
            with patch('app.task_store', store), patch('app._diagnostic_runs', {task.id: {'id': task.id, 'results': []}}), \
                 patch('app._diagnostic_cancels', {task.id: Event()}), patch('app._diagnostic_futures', {}), \
                 patch('fetchers.probe_worker.probe_with_budget', return_value=result):
                _run_media_diagnostic(task.id, [link], False)
            recovered = TaskStore(storage_path=path).get(task.id)
            self.assertEqual(recovered.status, TaskStatus.COMPLETED)
            self.assertEqual(recovered.result['results'][0]['platform'], 'weibo')
            self.assertNotIn('private', path.read_text())

    def test_queued_diagnostic_never_switches_to_replaced_auth(self):
        from app import _run_media_diagnostic
        store = TaskStore()
        auth = AuthStore()
        original = auth.put('bilibili', 'SESSDATA=old')
        auth.put('bilibili', 'SESSDATA=new')
        task = store.create(TaskKind.DIAGNOSTIC, '诊断', {'inputIds': ['hash-only']})
        with patch('app.task_store', store), patch('app.auth_store', auth), \
             patch('app._diagnostic_runs', {task.id: {'id': task.id, 'results': []}}), \
             patch('app._diagnostic_cancels', {task.id: Event()}), patch('app._diagnostic_futures', {}), \
             patch('fetchers.probe_worker.probe_with_budget') as probe:
            _run_media_diagnostic(task.id, ['https://www.bilibili.com/video/BV1xx411c7mD'], False,
                                  [(original.id, original.version)])
        probe.assert_not_called()
        row = store.get(task.id).result['results'][0]
        self.assertEqual(row['errorCode'], 'authorization_revoked')
        self.assertEqual(row['errorStage'], 'auth')

    def test_diagnostic_subprocess_cancellation_is_bounded(self):
        from fetchers.diagnostic_download import _run_command
        cancel = Event()
        from threading import Timer
        timer = Timer(.1, cancel.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(RuntimeError):
                _run_command([sys.executable, '-c', 'import time; time.sleep(10)'],
                             time.monotonic() + 20, cancel_event=cancel)
            self.assertLess(time.monotonic() - started, 3)
        finally:
            timer.join()

    def test_cookie_file_import_stays_on_chosen_platform(self):
        self.assertEqual(parse_cookie_file('bilibili', b'Cookie: SESSDATA=fixture'), 'SESSDATA=fixture')
        jar = b'# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tfixture\n'
        self.assertEqual(parse_cookie_file('bilibili', jar), 'SESSDATA=fixture')
        state = b'{"cookies":[{"domain":".bilibili.com","path":"/","name":"SESSDATA","value":"fixture"}],"origins":[]}'
        self.assertEqual(parse_cookie_file('bilibili', state), 'SESSDATA=fixture')
        with self.assertRaises(ValueError):
            parse_cookie_file('bilibili', jar.replace(b'.bilibili.com', b'.evil.test'))
        with self.assertRaises(ValueError):
            parse_cookie_file('bilibili', state.replace(b'"origins":[]', b'"origins":[{"origin":"https://evil.test"}]'))

    def test_imported_cookie_keeps_source_domain_scope(self):
        source = b'# Netscape HTTP Cookie File\napi.bilibili.com\tFALSE\t/\tTRUE\t0\tSESSDATA\tfixture\n'
        header, scopes = parse_cookie_file('bilibili', source, with_scopes=True)
        profile = AuthStore().put('bilibili', header, cookie_scopes=scopes)
        self.assertEqual([item['domain'] for item in browser_cookies(profile)], ['api.bilibili.com'])
        self.assertEqual([item.domain for item in cookie_jar(profile)], ['api.bilibili.com'])
        self.assertFalse(any(item.domain == '.bilibili.com' for item in cookie_jar(profile)))

    def test_weibo_share_variants_resolve_same_fid(self):
        expected = 'https://weibo.com/tv/show/1034:4418343294440212'
        self.assertEqual(normalize_share_url('复制 https://video.h5.weibo.cn/1034:4418343294440212/4418343899391020！'), expected)
        self.assertEqual(normalize_share_url('https://video.weibo.com/show?fid=1034%3A4418343294440212'), expected)
        with self.assertRaises(ValueError):
            normalize_share_url('https://video.h5.weibo.cn/no-fid/x')
        self.assertEqual(normalize_share_url('https://m.weibo.cn/detail/ABC123?foo=bar'),
                         'https://m.weibo.cn/status/ABC123?foo=bar')

    def test_weibo_multiple_video_post_is_not_reported_as_one_video(self):
        from fetchers.adapters.weibo import WeiboAdapter
        response = MagicMock(text='fixture', url='https://weibo.com/demo/post')
        payload = {'status': {'mix_media_info': {'items': [
            {'type': 'video', 'media_info': {'stream_url': 'https://cdn.example/1.mp4'}},
            {'type': 'video', 'media_info': {'stream_url': 'https://cdn.example/2.mp4'}},
        ]}}}
        with patch('fetchers.adapters.weibo.scoped_request', return_value=response), \
             patch.object(WeiboAdapter, '_extract_render_data', return_value=payload):
            with self.assertRaises(MediaProbeError) as captured:
                WeiboAdapter().fetch_media('https://weibo.com/demo/post')
        self.assertEqual(captured.exception.code, 'multiple_media_unsupported')

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

    def test_error_page_size_never_drives_smallest_stream_recommendation(self):
        polluted = MediaStream('https://cdn.example/bad.mp4', 'video', 'mp4', 'avc', 1280, 720,
                               1_000_000, 393, '高清')
        valid = MediaStream('https://cdn.example/good.mp4', 'video', 'mp4', 'hevc', 1280, 720,
                            900_000, None, '高清')
        result = MediaFetchResult('kuaishou', 'video', 'fixture', 'https://m.gifshow.com/fw/photo/test', '', None, None,
                                  video_streams=[polluted, valid], preferred_video=polluted)
        def sample(url, **_kwargs):
            return {'resourceStatus': 'invalid'} if 'bad.mp4' in url else {
                'resourceStatus': 'sampled', 'contentLength': 1_000_000, 'contentLengthLabel': '1 MB'}
        with patch('app.probe_stream_http_info', side_effect=sample):
            body = serialize_probe_result(result)
        self.assertIsNone(body['probeSummary']['bestFilesize'])
        self.assertEqual(body['recommendations']['smallest_size']['stream']['url'], valid.url)

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

    def test_auth_verification_is_time_bounded(self):
        store = AuthStore()
        profile = store.put('bilibili', 'SESSDATA=fixture')
        store.set_verification('bilibili', profile.version, 'valid')
        row = next(item for item in store.list_public() if item['platform'] == 'bilibili')
        self.assertEqual(row['verificationStatus'], 'valid')
        store._verification['bilibili']['verificationCheckedAt'] = '2000-01-01T00:00:00+00:00'
        row = next(item for item in store.list_public() if item['platform'] == 'bilibili')
        self.assertEqual(row['verificationStatus'], 'unknown')
        self.assertTrue(row['verificationStale'])

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

    def test_desktop_does_not_read_chrome_cookie_without_opt_in(self):
        from fetchers.adapters.douyin import load_chrome_cookies_for_douyin
        from fetchers.adapters.bilibili import load_bilibili_cookies
        from types import SimpleNamespace
        with use_auth(None), patch.dict(os.environ, {'STREAMDOCK_ALLOW_DESKTOP_BROWSER_COOKIES': '0'}), \
             patch('deployment_security.deployment_security', return_value=SimpleNamespace(server=False)), \
             patch('fetchers.adapters.douyin.browser_cookie3.chrome') as chrome, \
             patch('fetchers.adapters.bilibili.browser_cookie3.edge') as edge:
            self.assertEqual(load_chrome_cookies_for_douyin(), [])
            with patch('fetchers.adapters.bilibili.load_manual_cookies_for_bilibili', return_value=None):
                self.assertEqual(load_bilibili_cookies(), (None, None))
        chrome.assert_not_called()
        edge.assert_not_called()

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
    async def test_diagnostic_api_reuses_task_center_without_persisting_link(self):
        class ImmediateExecutor:
            def submit(self, fn, *args):
                future = Future()
                fn(*args)
                future.set_result(None)
                return future
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.json'
            store = TaskStore(storage_path=path)
            fixture = MediaFetchResult('weibo', 'video', 'fixture', '', '', None, None)
            with patch('app.task_store', store), patch('app._diagnostic_executor', ImmediateExecutor()), \
                 patch('app._diagnostic_runs', {}), patch('app._diagnostic_cancels', {}), \
                 patch('app._diagnostic_futures', {}), \
                 patch('fetchers.probe_worker.probe_with_budget', return_value=fixture):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                    created = await client.post('/api/media/diagnostics', json={
                        'links': ['https://weibo.com/tv/show/1034:12345?secret=private'],
                    })
                    self.assertEqual(created.status_code, 202)
                    run_id = created.json()['diagnostic']['id']
                    fetched = await client.get(f'/api/media/diagnostics/{run_id}')
                    listed = await client.get('/api/tasks?kind=diagnostic')
                self.assertEqual(fetched.json()['diagnostic']['status'], 'completed')
                self.assertEqual(listed.json()['tasks'][0]['kind'], 'diagnostic')
                self.assertNotIn('private', path.read_text())

    async def test_queued_diagnostic_can_be_cancelled(self):
        class HeldExecutor:
            def submit(self, _fn, *_args):
                return Future()
        store = TaskStore()
        with patch('app.task_store', store), patch('app._diagnostic_executor', HeldExecutor()), \
             patch('app._diagnostic_runs', {}), patch('app._diagnostic_cancels', {}), \
             patch('app._diagnostic_futures', {}):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                created = await client.post('/api/media/diagnostics', json={
                    'links': ['https://weibo.com/tv/show/1034:12345'],
                })
                self.assertEqual(created.status_code, 202)
                run_id = created.json()['diagnostic']['id']
                cancelled = await client.delete(f'/api/tasks/{run_id}')
                fetched = await client.get(f'/api/media/diagnostics/{run_id}')
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(store.get(run_id).status, TaskStatus.CANCELLED)
        self.assertEqual(fetched.json()['diagnostic']['status'], 'cancelled')

    async def test_interrupted_diagnostic_is_not_reported_running_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.json'
            store = TaskStore(storage_path=path)
            task = store.create(TaskKind.DIAGNOSTIC, '诊断', {'inputIds': ['hash-only'], 'linkCount': 1})
            store.update(task.id, status=TaskStatus.RUNNING,
                         result={'id': task.id, 'status': 'running', 'results': []})
            recovered = TaskStore(storage_path=path)
            self.assertEqual(recovered.get(task.id).status, TaskStatus.FAILED)
            with patch('app.task_store', recovered), patch('app._diagnostic_runs', {}):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                    response = await client.get(f'/api/media/diagnostics/{task.id}')
            self.assertEqual(response.json()['diagnostic']['status'], 'failed')

    async def test_auth_file_import_api_never_echoes_cookie(self):
        store = AuthStore()
        transport = httpx.ASGITransport(app=app)
        with patch('app.auth_store', store):
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                response = await client.post('/api/media/auth/weibo/import',
                                             files={'file': ('cookie.txt', b'Cookie: SUB=private', 'text/plain')})
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('private', response.text)
                self.assertEqual(store.get('weibo').cookie, 'SUB=private')

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
                    denied_file = await client.post('/api/media/auth/bilibili/import',
                                                    files={'file': ('cookie.txt', b'Cookie: SESSDATA=private', 'text/plain')})
                    result = await client.post('/api/media/probe', json={'link': 'not-a-link'})
                self.assertEqual(denied.status_code, 403)
                self.assertEqual(denied_file.status_code, 403)
                self.assertEqual(result.status_code, 200)
                self.assertFalse(result.json()['success'])
                self.assertIn('traceId', result.json())


if __name__ == '__main__':
    unittest.main()
