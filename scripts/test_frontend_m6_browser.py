#!/usr/bin/env python3
"""Real-browser acceptance for M6 user workflows and responsive navigation."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def wait_for_server(port: int) -> None:
    import urllib.request

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/convert', timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError('StreamDock test server did not start')


def main() -> int:
    port = free_port()
    env = {**os.environ, 'STREAMDOCK_TASK_STORAGE_PATH': '', 'STREAMDOCK_MAX_CONVERT_BATCH_FILES': '50'}
    server = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(port)
        with tempfile.TemporaryDirectory(prefix='streamdock-m6-') as tmp:
            root = Path(tmp)
            csv_files = []
            for index in range(32):
                path = root / f'complex-{index + 1:02d}.csv'
                path.write_text(
                    f'id,name,note\n{index + 1},第{index + 1}行中文,表情😀-换行前\\n换行后\n',
                    encoding='utf-8',
                )
                csv_files.append(path)
            subtitle = root / 'keyboard-中文.srt'
            subtitle.write_text('1\n00:00:00,000 --> 00:00:02,000\n键盘导入 😀\n', encoding='utf-8')
            source_folder = root / '复杂文件夹'
            (source_folder / 'docs').mkdir(parents=True)
            (source_folder / 'empty' / 'deep').mkdir(parents=True)
            (source_folder / 'docs' / 'readme.txt').write_text('真实文件夹 😀', encoding='utf-8')

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 900})

                # U02: use real UTF-8 CSV files and the real probe endpoint. Verify
                # the 30th item, arbitrary removal, and incremental append.
                page.goto(f'http://127.0.0.1:{port}/convert')
                file_input = page.locator('#convertFileInput')
                file_input.set_input_files([str(path) for path in csv_files[:30]])
                page.wait_for_function("document.querySelectorAll('[data-remove-file]').length === 30")
                assert 'complex-30.csv' in page.locator('#convertFileList').inner_text()
                page.locator('[data-remove-file="10"]').click()
                page.wait_for_function("document.querySelectorAll('[data-remove-file]').length === 29")
                file_input.set_input_files([str(csv_files[30]), str(csv_files[31])])
                page.wait_for_function("document.querySelectorAll('[data-remove-file]').length === 31")
                names = page.locator('#convertFileList').inner_text()
                assert 'complex-11.csv' not in names
                assert 'complex-31.csv' in names and 'complex-32.csv' in names

                # U05: a real directory selected by the browser reaches the real
                # packing engine and preserves the nested file content.
                page.locator('[data-clear-files]').click()
                page.locator('#convertFolderInput').set_input_files(str(source_folder))
                page.wait_for_function("document.querySelector('#convertInputType').value === 'FOLDER'")
                page.select_option('#convertOutputType', 'zip')
                page.evaluate(f"document.querySelector('#convertOutputPath').value={str(root)!r}")
                page.locator('#convertStartButton').click()
                page.wait_for_function("document.querySelector('#convertResultBox strong').textContent.includes('转换完成')")
                packed_path = Path(page.locator('#convertResultBox span').first.inner_text().split('：', 1)[1])
                with zipfile.ZipFile(packed_path) as archive:
                    assert archive.read('docs/readme.txt').decode('utf-8') == '真实文件夹 😀'

                # U12: panel selection is addressable and browser Back restores it.
                page.locator('[data-convert-nav="settings"]').click()
                assert page.url.endswith('#settings')
                page.go_back()
                page.wait_for_function("document.querySelector('[data-convert-panel=\"workbench\"]').hidden === false")

                # U03: one bad link must not discard the successful item.
                page.goto(f'http://127.0.0.1:{port}/use')
                page.evaluate(
                    """
                    () => {
                      const originalFetch = window.fetch.bind(window);
                      window.__submittedLinks = null;
                      window.fetch = (url, options = {}) => {
                        if (String(url).endsWith('/api/media/probe')) {
                          const link = JSON.parse(options.body).link;
                          if (link.includes('broken')) return Promise.resolve(new Response(
                            JSON.stringify({success:false,error:'fixture probe failed'}),
                            {status:422,headers:{'Content-Type':'application/json'}}
                          ));
                          return Promise.resolve(new Response(JSON.stringify({
                            success:true,platform:'fixture',title:'复杂视频 😀',contentType:'video',
                            videoStreams:[{qualityLabel:'720p',width:1280,height:720,codec:'h264',bitrate:1000000}],
                            audioStreams:[{codec:'aac'}],recommendations:{best_quality:{stream:{qualityLabel:'720p',width:1280,height:720}}},
                            probeSummary:{qualityCount:1,bestResolution:'1280×720'},assetSummary:{subtitleCount:0}
                          }), {status:200,headers:{'Content-Type':'application/json'}}));
                        }
                        if (String(url).endsWith('/api/fetch/batch')) {
                          const body = JSON.parse(options.body);
                          window.__submittedLinks = body.links;
                          return Promise.resolve(new Response(JSON.stringify({
                            success:true,tasks:body.links.map((link, index) => ({id:`task-${index}`,payload:{link}}))
                          }), {status:200,headers:{'Content-Type':'application/json'}}));
                        }
                        return originalFetch(url, options);
                      };
                    }
                    """
                )
                page.locator('#link').fill('https://example.test/good\nhttps://example.test/broken')
                page.locator('#submitButton').click()
                page.wait_for_function("document.querySelector('#submitButton').textContent.includes('继续处理 1 条')")
                assert page.locator('#mediaProbeRetryFailed').is_visible()
                page.locator('#submitButton').click()
                page.wait_for_function('window.__submittedLinks !== null')
                assert page.evaluate('window.__submittedLinks') == ['https://example.test/good']

                # U10/U11: narrow-screen navigation remains visible and real file
                # import can be initiated from a keyboard-focusable button.
                page.set_viewport_size({'width': 390, 'height': 844})
                page.goto(f'http://127.0.0.1:{port}/pdf#tasks')
                assert page.locator('[data-pdf-tab="tasks"]').is_visible()
                page.goto(f'http://127.0.0.1:{port}/web-archive#tasks')
                assert page.locator('[data-archive-nav="tasks"]').is_visible()
                page.goto(f'http://127.0.0.1:{port}/subtitles')
                assert page.locator('#subtitleClearMobile').is_visible()
                import_button = page.locator('#subtitleImportButton')
                import_button.focus()
                assert page.evaluate('document.activeElement.id') == 'subtitleImportButton'
                with page.expect_file_chooser() as chooser_info:
                    import_button.press('Enter')
                chooser_info.value.set_files(str(subtitle))
                page.wait_for_function("document.querySelector('#subtitleCount').textContent === '1'")
                assert '键盘导入' in page.locator('[data-text]').input_value()
                assert page.locator('#toast').get_attribute('aria-live') == 'polite'
                browser.close()

        print('REAL_BROWSER_M6=passed batch-edit=31 folder-pack=real partial-probe=1/2 history=restored narrow-nav=visible keyboard-import=passed')
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == '__main__':
    raise SystemExit(main())
