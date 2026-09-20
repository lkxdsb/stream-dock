#!/usr/bin/env python3
"""Real browser + real file acceptance for the M9 server trust boundary."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'm9-browser-token-with-at-least-24-characters'


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def wait_for_server(port: int) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                payload = json.load(response)
                if response.status == 200 and payload['mode'] == 'server' and payload['configured']:
                    return
        except Exception:
            time.sleep(.1)
    raise RuntimeError('M9 server did not start')


def main() -> int:
    invalid_port = free_port()
    invalid_env = {**os.environ, 'STREAMDOCK_MODE': 'server', 'STREAMDOCK_ALLOW_LAN_API': '0', 'STREAMDOCK_TASK_STORAGE_PATH': ''}
    for key in ('STREAMDOCK_API_TOKEN', 'STREAMDOCK_TRUSTED_HOSTS', 'STREAMDOCK_ALLOWED_ORIGINS', 'STREAMDOCK_SERVER_OUTPUT_ROOT'):
        invalid_env.pop(key, None)
    invalid = subprocess.run(
        [sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(invalid_port)],
        cwd=ROOT, env=invalid_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20,
    )
    assert invalid.returncode != 0 and '服务器模式配置无效' in invalid.stdout

    port = free_port()
    with tempfile.TemporaryDirectory(prefix='streamdock-m9-') as tmp:
        work = Path(tmp)
        output_root = work / 'server-output'
        source = work / '复杂真实表格.csv'
        source.write_text('id,name,note\n1,张三,中文😀\n2,Ada,"multi line ©"\n', encoding='utf-8')
        origin = f'http://127.0.0.1:{port}'
        env = {
            **os.environ,
            'STREAMDOCK_TASK_STORAGE_PATH': '',
            'STREAMDOCK_MODE': 'server',
            'STREAMDOCK_API_TOKEN': TOKEN,
            'STREAMDOCK_TRUSTED_HOSTS': '127.0.0.1',
            'STREAMDOCK_ALLOWED_ORIGINS': origin,
            'STREAMDOCK_SERVER_OUTPUT_ROOT': str(output_root),
        }
        server = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port)],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            wait_for_server(port)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 900})
                observed_post_origins: list[str] = []
                api_responses: list[str] = []
                page.on('request', lambda request: observed_post_origins.append(request.headers.get('origin', '')) if request.method == 'POST' and request.url.endswith('/auth') else None)
                page.on('response', lambda response: api_responses.append(f'{response.status} {response.url}') if '/api/' in response.url else None)
                page.goto(f'{origin}/convert')
                assert page.url.endswith('/auth')
                page.locator('#apiToken').fill(TOKEN)
                with page.expect_navigation():
                    page.locator('button[type="submit"]').click()
                assert page.url == f'{origin}/', f'login ended at {page.url}, origins={observed_post_origins}: {page.locator("body").inner_text()}'
                page.goto(f'{origin}/convert')
                assert page.locator('#convertOutputPath').input_value() == str(output_root.resolve())
                assert page.locator('#convertSelectDirButton').is_hidden()

                page.locator('#convertFileInput').set_input_files(str(source))
                page.wait_for_function("document.querySelector('#convertInputType').value === 'CSV'")
                page.select_option('#convertOutputType', 'json')
                page.locator('#convertStartButton').click()
                page.wait_for_timeout(3000)
                result_text = page.locator('#convertResultBox').inner_text()
                assert '转换完成' in result_text, f'{result_text}; responses={api_responses}'
                output = next(output_root.glob('*.json'))
                converted = json.loads(output.read_text(encoding='utf-8'))
                assert converted[0]['name'] == '张三' and converted[0]['note'] == '中文😀'
                assert converted[1]['note'] == 'multi line ©'

                blocked = page.evaluate("fetch('/api/open-output-path',{method:'POST'}).then(async r=>({status:r.status,body:await r.json()}))")
                assert blocked['status'] == 403 and '禁用' in blocked['body']['error']
                headers = page.evaluate("fetch('/api/health').then(r=>Object.fromEntries(r.headers.entries()))")
                assert headers['x-frame-options'] == 'DENY'
                browser.close()

            print('REAL_BROWSER_M9=passed invalid-startup=blocked auth=cookie host-origin=trusted desktop-api=blocked real-csv-json=format+content-verified')
            return 0
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
            if server.returncode not in {0, -15}:
                print(server.stdout.read() if server.stdout else '', file=sys.stderr)


if __name__ == '__main__':
    raise SystemExit(main())
