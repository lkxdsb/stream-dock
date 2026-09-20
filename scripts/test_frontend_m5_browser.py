#!/usr/bin/env python3
"""Real-browser regression for M5 frontend state boundaries.

This starts the actual FastAPI app, selects real CSV/XLSX files through the
browser file input, and checks both stale probe suppression and settings/workbench
isolation. It requires Playwright Chromium to be installed locally.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from openpyxl import Workbook
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
    env = {**os.environ, 'STREAMDOCK_TASK_STORAGE_PATH': ''}
    server = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(port)
        with tempfile.TemporaryDirectory(prefix='streamdock-m5-') as tmp:
            tmp_path = Path(tmp)
            csv_file = tmp_path / 'first.csv'
            csv_file.write_text('name,value\n第一行中文,😀\n', encoding='utf-8')
            xlsx_file = tmp_path / 'second.xlsx'
            workbook = Workbook()
            workbook.active.append(['name', 'value'])
            workbook.active.append(['第二行中文', '🚀'])
            workbook.save(xlsx_file)
            third_xlsx_file = tmp_path / 'third.xlsx'
            workbook = Workbook()
            workbook.active.append(['name', 'value'])
            workbook.active.append(['第三行中文', '🌟'])
            workbook.save(third_xlsx_file)
            subtitle_file = tmp_path / 'lesson.srt'
            subtitle_file.write_text(
                '1\n00:00:01,000 --> 00:00:03,000\n第一行中文 😀\n',
                encoding='utf-8',
            )

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{port}/convert')
                page.evaluate(
                    """
                    () => {
                      const originalFetch = window.fetch.bind(window);
                      window.fetch = (url, options = {}) => {
                        if (String(url).endsWith('/api/convert/probe')) {
                          const file = options.body.get('file');
                          const first = file.name === 'first.csv';
                          const payload = first
                            ? {success:true,source:'csv',supported:true,options:[{target:'txt',level:'stable',verification:'verified'}]}
                            : {success:true,source:'xlsx',supported:true,options:[
                                {target:'csv',level:'stable',verification:'verified'},
                                {target:'json',level:'stable',verification:'verified'}
                              ]};
                          return new Promise((resolve) => setTimeout(() => resolve(new Response(
                            JSON.stringify(payload), {status:200,headers:{'Content-Type':'application/json'}}
                          )), first ? 500 : 20));
                        }
                        if (String(url).endsWith('/api/convert/batch-probe')) {
                          return Promise.resolve(new Response(JSON.stringify({
                            success:true,source:'xlsx',supported:true,fileCount:2,
                            options:[{target:'csv',level:'stable',verification:'verified'}]
                          }), {status:200,headers:{'Content-Type':'application/json'}}));
                        }
                        if (String(url).endsWith('/api/convert/batch-run')) {
                          return Promise.resolve(new Response(JSON.stringify({
                            success:false,total:2,successCount:1,failedCount:1,logs:['partial'],
                            tasks:[{id:'convert-ok'}],
                            results:[
                              {success:true,filename:'second.xlsx',source:'xlsx',target:'csv',outputPath:'/tmp/second.csv',taskId:'convert-ok',validation:{valid:true,sizeLabel:'1 KB'}},
                              {success:false,filename:'third.xlsx',source:'xlsx',target:'csv',error:'fixture conversion failure'}
                            ]
                          }), {status:207,headers:{'Content-Type':'application/json'}}));
                        }
                        return originalFetch(url, options);
                      };
                    }
                    """
                )
                file_input = page.locator('#convertFileInput')
                file_input.set_input_files(str(csv_file))
                page.locator('[data-clear-files]').click()
                file_input.set_input_files(str(xlsx_file))
                page.wait_for_timeout(700)
                assert page.locator('#convertInputType').input_value() == 'XLSX'
                assert page.locator('#convertFileTitle').inner_text() == 'second.xlsx'

                page.select_option('#convertOutputType', 'json')
                page.evaluate("document.querySelector('#convertOutputPath').value='/tmp/current-job-output'")
                page.evaluate(
                    """
                    () => {
                      document.querySelector('#convertImageQuality').value = '75';
                      document.querySelector('#convertSaveSettingsButton').click();
                    }
                    """
                )
                assert page.locator('#convertOutputType').input_value() == 'json'
                assert page.locator('#convertOutputPath').input_value() == '/tmp/current-job-output'

                file_input.set_input_files([str(xlsx_file), str(third_xlsx_file)])
                page.wait_for_timeout(100)
                page.evaluate("document.querySelector('#convertStartButton').click()")
                page.wait_for_function("document.querySelector('#convertResultBox strong').textContent === '批量转换完成'")
                assert page.locator('#convertResultBox .convert-result-row.success').count() == 1
                assert page.locator('#convertResultBox .convert-result-row.error').count() == 1

                page.goto(f'http://127.0.0.1:{port}/subtitles')
                page.evaluate(
                    """
                    () => {
                      window.__subtitleImportDelay = 300;
                      window.__subtitleExportDelay = 300;
                      const originalFetch = window.fetch.bind(window);
                      window.fetch = (url, options = {}) => {
                        if (String(url).endsWith('/api/subtitles/import')) {
                          const body = {success:true,document:{
                            filename:'lesson.srt',format:'srt',cueCount:1,
                            cues:[{id:'cue-1',start:1,end:3,text:'第一行中文 😀'}]
                          }};
                          return new Promise((resolve) => setTimeout(() => resolve(new Response(
                            JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}}
                          )), window.__subtitleImportDelay));
                        }
                        if (String(url).endsWith('/api/subtitles/export')) {
                          return new Promise((resolve) => setTimeout(() => resolve(new Response(
                            new Blob(['exported subtitle'], {type:'text/plain'}), {status:200}
                          )), window.__subtitleExportDelay));
                        }
                        return originalFetch(url, options);
                      };
                    }
                    """
                )
                subtitle_input = page.locator('#subtitleFile')
                subtitle_input.set_input_files(str(subtitle_file))
                page.evaluate("document.querySelector('#subtitleClear').click()")
                page.wait_for_timeout(450)
                assert page.locator('#subtitleCount').inner_text() == '0'

                page.evaluate("window.__subtitleImportDelay = 0")
                subtitle_input.set_input_files(str(subtitle_file))
                page.wait_for_timeout(100)
                page.locator('[data-start]').fill('10')
                page.locator('[data-end]').fill('12')
                page.evaluate("document.querySelector('.subtitle-cue').click()")
                assert page.evaluate("document.querySelector('#subtitlePlayer').currentTime") == 10

                page.evaluate("document.querySelector('#subtitleExport').click()")
                page.wait_for_timeout(50)
                page.locator('[data-text]').fill('导出期间继续编辑 🚀')
                page.wait_for_timeout(400)
                export_status = page.locator('#subtitleDocumentStatus').inner_text()
                assert export_status == '导出完成，仍有未导出修改', export_status

                archive_state = {'cancelled': False, 'detail_reads': 0}

                def handle_archive_tasks(route):
                    request = route.request
                    task = {
                        'id': 'archive-task-1',
                        'kind': 'web_archive',
                        'title': '复杂网页归档样例',
                        'status': 'cancelled' if archive_state['cancelled'] else 'running',
                        'stage': '正在提取正文与图片',
                        'result': {},
                    }
                    if request.method == 'DELETE':
                        archive_state['cancelled'] = True
                        route.fulfill(status=200, json={'success': True, 'task': task})
                    elif request.url.endswith('?kind=web_archive'):
                        route.fulfill(status=200, json={'success': True, 'tasks': [task]})
                    else:
                        archive_state['detail_reads'] += 1
                        route.fulfill(status=200, json={'success': True, 'task': task})

                page.route('**/api/tasks*', handle_archive_tasks)
                page.route('**/api/tasks/**', handle_archive_tasks)
                page.goto(f'http://127.0.0.1:{port}/web-archive')
                page.wait_for_function("document.querySelector('#webArchiveCancelBtn').hidden === false")
                page.wait_for_function("document.querySelector('#webArchiveStatus').textContent.includes('正在提取')")
                page.locator('#webArchiveCancelBtn').click()
                page.wait_for_timeout(3000)
                archive_status = page.locator('#webArchiveStatus').inner_text()
                assert archive_status == '任务已取消', (archive_status, archive_state)
                assert archive_state['detail_reads'] >= 1
                browser.close()

        print('REAL_BROWSER_M5=passed stale_probe=discarded batch=partial-visible settings=isolated subtitles=versioned archive=recovered')
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == '__main__':
    raise SystemExit(main())
