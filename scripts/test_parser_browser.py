#!/usr/bin/env python3
"""Real UI checks for failed-item retry and same-label stream identity."""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


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
            page.goto(f'http://127.0.0.1:{port}/use')
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
            page.goto(f'http://127.0.0.1:{port}/use')
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
            browser.close()
        print('REAL_BROWSER_PARSER=passed batch-retry=preserved stream-id=hevc')
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == '__main__':
    main()
