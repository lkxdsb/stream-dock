#!/usr/bin/env python3
"""Real-browser acceptance for M8 capability contracts and health semantics."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
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
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(.1)
    raise RuntimeError('StreamDock test server did not start')


def main() -> int:
    port = free_port()
    env = {**os.environ, 'STREAMDOCK_TASK_STORAGE_PATH': ''}
    server = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(port)
        with tempfile.TemporaryDirectory(prefix='streamdock-m8-') as tmp:
            root = Path(tmp)
            forbidden = root / 'liveness-must-not-create'
            source = root / '真实合同测试.csv'
            source.write_text('id,name,note\n1,张三,中文😀\n2,Ada,multiline\n', encoding='utf-8')

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 900})
                page.goto(f'http://127.0.0.1:{port}/convert')
                page.wait_for_function('window.StreamDockConvertCapabilities?.length > 150')

                live = page.evaluate(f"fetch('/api/health?outputPath={forbidden}').then(r => r.json())")
                assert live['status'] == 'live' and not forbidden.exists()
                ready = page.evaluate(f"fetch('/api/health/ready?outputPath={root}').then(async r => ({{status:r.status,body:await r.json()}}))")
                assert ready['status'] == 200 and ready['body']['healthy']

                route = page.evaluate("window.StreamDockConvertCapabilities.find(item => item.key === 'csv:json')")
                assert route['verification'] == 'release-gated'
                assert route['contract']['validator'] == 'target-parser-and-cell-readback'
                assert route['contract']['releaseGate'] is True
                page.locator('[data-convert-nav="matrix"]').click()
                page.locator('[data-capability-key="csv:json"]').click()
                page.wait_for_function("document.querySelector('#convertOrbitRoutes').textContent.includes('依赖：')")
                detail = page.locator('#convertOrbitRoutes').inner_text()
                assert '依赖：' in detail and '保留：' in detail and '允许损失：' in detail

                page.locator('[data-convert-nav="workbench"]').click()
                page.locator('#convertFileInput').set_input_files(str(source))
                page.wait_for_function("document.querySelector('#convertInputType').value === 'CSV'")
                page.select_option('#convertOutputType', 'json')
                page.evaluate(f"document.querySelector('#convertOutputPath').value={str(root)!r}")
                page.locator('#convertStartButton').click()
                page.wait_for_function("document.querySelector('#convertResultBox strong').textContent.includes('转换完成')")
                output = Path(page.locator('#convertResultBox span').first.inner_text().split('：', 1)[1])
                converted = json.loads(output.read_text(encoding='utf-8'))
                assert converted[0]['name'] == '张三' and converted[0]['note'] == '中文😀'
                browser.close()

        print('REAL_BROWSER_M8=passed liveness=pure readiness=ready contracts=152 real-csv-json=content-verified')
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == '__main__':
    raise SystemExit(main())
