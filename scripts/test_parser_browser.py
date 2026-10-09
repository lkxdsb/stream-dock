#!/usr/bin/env python3
"""Real UI checks for failed-item retry and same-label stream identity."""

import os
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def check_failed_download_subtitle_status(browser, origin: str) -> None:
    page = browser.new_page()
    fixture = {'id': 'failed-media', 'kind': 'media', 'title': 'failed-media',
               'status': 'failed', 'payload': {'link': 'https://example.test/video'},
               'logs': [], 'error': '平台要求交互验证',
               'result': {'outputPath': None, 'subtitleJob': {'status': 'unavailable'}}}
    try:
        page.route('**/api/tasks?kind=media', lambda route: route.fulfill(
            content_type='application/json', body=json.dumps({'success': True, 'tasks': [fixture]})))
        page.goto(f'{origin}/use#completed')
        page.get_by_role('button', name='查看详情', exact=True).first.click()
        dialog = page.get_by_role('dialog')
        assert '视频文件已经完成' not in dialog.inner_text()
        assert dialog.locator('.subtitle-job-section').count() == 0
    finally:
        page.close()


def check_portrait_resolution(browser, origin: str) -> None:
    page = browser.new_page()
    try:
        page.goto(f'{origin}/use#parse')
        for width, height, expected in (
            (1080, 1920, '1080P'), (1920, 1080, '1080P'),
            (720, 1280, '720P'), (1440, 2560, '2K'),
            (2160, 3840, '4K'), (3840, 2160, '4K'),
        ):
            assert page.evaluate('(s) => window.StreamDockQuality.friendlyResolution(s)',
                                 {'width': width, 'height': height}) == expected
    finally:
        page.close()


def check_share_text_and_stale_edits(browser, origin: str) -> None:
    """Deterministic UI regression; API metadata is a fixture, not a live probe."""
    page = browser.new_page()
    fixture = {
        'success': True, 'platform': 'douyin', 'title': '分享文案测试',
        'contentType': 'video', 'videoStreams': [
            {'streamId': 'sid:share-text', 'qualityLabel': '高清', 'height': 720, 'codec': 'h264'}
        ], 'audioStreams': [], 'assetSummary': {'subtitleCount': 0},
        'recommendations': {'best_quality': {'stream': {
            'streamId': 'sid:share-text', 'qualityLabel': '高清', 'height': 720, 'codec': 'h264'
        }}}, 'probeSummary': {'qualityCount': 1},
    }
    page.route('**/api/media/probe', lambda route: route.fulfill(json=fixture))
    page.goto(f'{origin}/use#parse')
    page.locator('#link').fill('9.94 分享文案 中文😀 https://v.douyin.com/share-fixture/ 复制此链接，打开Dou音观看！')
    page.locator('#submitButton').click()
    page.wait_for_function("document.querySelector('#submitButton').textContent.includes('确认并开始下载')", timeout=7000)
    assert not page.locator('#mediaProbePreview').is_hidden()
    assert '分享文案测试' in page.locator('#mediaProbeTitle').inner_text()
    page.goto(f'{origin}/use#parse')
    page.evaluate("""fixture => {
      window.fetch = () => new Promise(resolve => {
        window.__releaseProbe = () => resolve(new Response(JSON.stringify(fixture),
          {headers: {'Content-Type':'application/json'}}));
      });
      document.querySelector('#link').value = '文案 https://v.douyin.com/old/';
      window.__completed = false;
      window.StreamDockQuality.probeQualityOptions('https://v.douyin.com/old/', {silent:true})
        .then(result => { window.__probeResult = result; window.__completed = true; });
    }""", fixture)
    page.evaluate("document.querySelector('#link').value = '新文案 https://v.douyin.com/new/'; window.__releaseProbe()")
    page.wait_for_function('window.__completed')
    assert page.evaluate('window.__probeResult === null')
    page.close()


def check_probe_failure_diagnostics(browser, origin: str) -> None:
    page = browser.new_page()
    try:
        page.route('**/api/media/probe', lambda route: route.fulfill(json={
            'success': False, 'error': '媒体解析未取得可用资源', 'traceId': 'fixture-trace',
            'errorInfo': {'code': 'parser_failed', 'stage': 'browser_capture',
                          'causes': ['share-page: structure missing', 'no-login: No media URL captured']},
        }))
        page.goto(f'{origin}/use#parse')
        page.locator('#link').fill('https://v.douyin.com/diagnostic-fixture/')
        page.locator('#submitButton').click()
        page.wait_for_function("document.body.textContent.includes('诊断编号：fixture-trace')")
        text = page.locator('body').inner_text()
        assert '失败阶段：browser_capture' in text
        assert 'no-login: No media URL captured' in text
        assert '请确认浏览器登录态' not in text
        assert not page.locator('#submitButton').is_disabled()
    finally:
        page.close()


def check_stalled_response_body(browser, origin: str) -> None:
    """Use a real HTTP body that stalls after headers, not a mocked promise."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Event, Thread
    release = Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', '9999')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{')
            self.wfile.flush()
            release.wait(5)
        def log_message(self, *_args):
            pass
    http_server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page()
    try:
        page.goto(f'{origin}/use#parse')
        page.evaluate("""url => {
          const originalFetch = window.fetch.bind(window);
          const originalTimeout = window.setTimeout.bind(window);
          window.setTimeout = (callback, delay, ...args) => originalTimeout(callback, delay === 120000 ? 450 : delay, ...args);
          window.fetch = (urlArg, options = {}) => String(urlArg).endsWith('/api/media/probe')
            ? originalFetch(url, {signal: options.signal}) : originalFetch(urlArg, options);
        }""", f'http://127.0.0.1:{http_server.server_port}/stalled-json')
        page.locator('#link').fill('文案 https://v.douyin.com/stalled/')
        page.locator('#submitButton').click()
        page.wait_for_function("document.body.textContent.includes('清晰度识别超时')", timeout=2500)
        assert not page.locator('#submitButton').is_disabled()
        assert page.locator('#submitButton').inner_text() == '开始解析'
    finally:
        page.close()
        release.set()
        http_server.shutdown()
        http_server.server_close()
        thread.join(timeout=2)


def main() -> None:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port)],
                              cwd=ROOT, env={**os.environ, 'STREAMDOCK_TASK_STORAGE_PATH': ''},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health/live', timeout=1).close()
                break
            except Exception:
                time.sleep(.1)
        else:
            raise RuntimeError('test server did not start')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{port}/use#parse')
            page.evaluate('''() => {
              const original = window.fetch.bind(window);
              window.__sent = null; window.__failedOnce = false;
              window.fetch = (url, options = {}) => {
                if (String(url).endsWith('/api/media/probe')) {
                  const link = JSON.parse(options.body).link;
                  if (link === 'https://example.test/broken' && !window.__failedOnce) {
                    window.__failedOnce = true;
                    return Promise.resolve(new Response(JSON.stringify({success:false,error:'fixture failed'}),
                      {status:200,headers:{'Content-Type':'application/json'}}));
                  }
                  const streams = [
                    {streamId:'sid:avc',qualityLabel:'高清',codec:'avc',width:1280,height:720,bitrate:1000000},
                    {streamId:'sid:hevc',qualityLabel:'高清',codec:'hevc',width:1280,height:720,bitrate:900000}
                  ];
                  return Promise.resolve(new Response(JSON.stringify({success:true,platform:'kuaishou',
                    title:'fixture',contentType:'video',videoStreams:streams,audioStreams:[],
                    recommendations:{best_quality:{stream:streams[0]}},probeSummary:{qualityCount:2},assetSummary:{subtitleCount:0}}),
                    {status:200,headers:{'Content-Type':'application/json'}}));
                }
                if (String(url).endsWith('/api/fetch/batch')) {
                  window.__sent = JSON.parse(options.body);
                  return Promise.resolve(new Response(JSON.stringify({success:true,tasks:[{id:'task-1'}]}),
                    {status:200,headers:{'Content-Type':'application/json'}}));
                }
                return original(url, options);
              };
            }''')
            page.locator('#link').fill('https://example.test/good\nhttps://example.test/broken')
            page.locator('#submitButton').click()
            try:
                page.wait_for_function("document.querySelector('#submitButton').textContent.includes('继续处理 1 条')", timeout=7000)
            except Exception:
                print('DEBUG', page.locator('#submitButton').inner_text(), page.locator('#mediaProbePreview').inner_text()[:700])
                raise
            page.locator('#mediaProbeRetryFailed').click()
            page.locator('#submitButton').click()
            try:
                page.wait_for_function("document.querySelector('#submitButton').textContent.includes('确认并开始')", timeout=7000)
            except Exception:
                print('RETRY_DEBUG', page.locator('#submitButton').inner_text(), page.locator('#mediaProbePreview').inner_text()[:500])
                raise
            page.locator('#submitButton').click()
            page.wait_for_function('window.__sent !== null')
            assert page.evaluate('window.__sent.links') == ['https://example.test/good', 'https://example.test/broken']
            page.wait_for_function("location.hash === '#downloading'")
            page.goto(f'http://127.0.0.1:{port}/use#parse')
            page.locator('#link').fill('https://example.test/good')
            # Reinstall the probe fixture after navigation.
            page.evaluate('''() => { const original = window.fetch.bind(window); window.__sent = null;
              window.fetch = (url, options = {}) => {
                if (String(url).endsWith('/api/media/probe')) {
                  const streams = [{streamId:'sid:avc',qualityLabel:'高清',codec:'avc',width:1280,height:720,bitrate:1000000},
                    {streamId:'sid:hevc',qualityLabel:'高清',codec:'hevc',width:1280,height:720,bitrate:900000}];
                  return Promise.resolve(new Response(JSON.stringify({success:true,platform:'kuaishou',title:'fixture',
                    contentType:'video',videoStreams:streams,audioStreams:[],recommendations:{best_quality:{stream:streams[0]}},
                    probeSummary:{qualityCount:2},assetSummary:{subtitleCount:0}}),
                    {status:200,headers:{'Content-Type':'application/json'}}));
                }
                if (String(url).endsWith('/api/fetch/batch')) { window.__sent = JSON.parse(options.body);
                  return Promise.resolve(new Response(JSON.stringify({success:true,tasks:[{id:'task-2'}]}),
                    {status:200,headers:{'Content-Type':'application/json'}})); }
                return original(url, options);
              };
            }''')
            page.locator('#submitButton').click()
            page.wait_for_function("document.querySelector('#submitButton').textContent.includes('确认并开始下载')")
            page.locator('#mediaProbeToggle').click()
            page.locator('[data-select-stream="sid:hevc"]').click()
            page.locator('#submitButton').click()
            page.wait_for_function('window.__sent !== null')
            assert page.evaluate('window.__sent.videoQuality') == 'sid:hevc'
            page.goto(f'http://127.0.0.1:{port}/use#settings')
            page.locator('[data-use-tab="settings"]').click()
            page.evaluate('''() => { const original = window.fetch.bind(window); window.__diagCancelled = false;
              window.fetch = (url, options = {}) => {
                const value = String(url);
                if (value === '/api/media/diagnostics' && options.method === 'POST')
                  return Promise.resolve(new Response(JSON.stringify({success:true,diagnostic:{id:'diag-fixture',status:'queued'}}),
                    {status:202,headers:{'Content-Type':'application/json'}}));
                if (value === '/api/media/diagnostics/diag-fixture')
                  return Promise.resolve(new Response(JSON.stringify({success:true,diagnostic:{id:'diag-fixture',
                    status:window.__diagCancelled?'cancelled':'running',results:[]}}),
                    {status:200,headers:{'Content-Type':'application/json'}}));
                if (value === '/api/tasks/diag-fixture' && options.method === 'DELETE') {
                  window.__diagCancelled = true;
                  return Promise.resolve(new Response(JSON.stringify({success:true}),
                    {status:200,headers:{'Content-Type':'application/json'}}));
                }
                return original(url, options);
              };
            }''')
            page.locator('#mediaDiagnosticLinks').fill('https://weibo.com/tv/show/1034:12345')
            page.locator('#mediaDiagnosticRun').click()
            page.locator('#mediaDiagnosticCancel').click()
            page.wait_for_function("document.querySelector('#mediaDiagnosticStatus').textContent.includes('cancelled')", timeout=5000)
            assert page.evaluate('window.__diagCancelled')
            check_share_text_and_stale_edits(browser, f'http://127.0.0.1:{port}')
            check_stalled_response_body(browser, f'http://127.0.0.1:{port}')
            check_probe_failure_diagnostics(browser, f'http://127.0.0.1:{port}')
            check_portrait_resolution(browser, f'http://127.0.0.1:{port}')
            check_failed_download_subtitle_status(browser, f'http://127.0.0.1:{port}')
            browser.close()
        print('REAL_BROWSER_PARSER=passed batch-retry=preserved stream-id=hevc diagnostic-cancel=passed share-text=accepted stale-edit=discarded real-stalled-body=timeout-visible')
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == '__main__':
    main()
