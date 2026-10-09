#!/usr/bin/env python3
"""Opt-in live UI acceptance: actual share text, actual API, no mocked fetches.

Requires an already running desktop StreamDock. Does not submit a download task.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8002')
    parser.add_argument('--share-text', required=True)
    parser.add_argument('--expected-title', required=True)
    parser.add_argument('--report', type=Path, default=Path('report_figures/share-text-live.json'))
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error('--base-url must be an HTTP(S) origin without credentials/query/fragment')
    report = {
        'checkedAt': datetime.now(timezone.utc).isoformat(),
        'baseUrl': args.base_url.rstrip('/'),
        'inputSha256': hashlib.sha256(args.share_text.encode()).hexdigest(),
        'scope': 'live-browser-and-live-probe; full-download-not-tested',
        'status': 'fail',
        'probes': [],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                def on_response(response):
                    if response.url.split('?')[0].endswith('/api/media/probe'):
                        body = response.json()
                        report['probes'].append({
                            'httpStatus': response.status, 'success': body.get('success'),
                            'title': body.get('title'), 'platform': body.get('platform'),
                            'videoStreamCount': len(body.get('videoStreams', [])),
                            'errorCode': body.get('errorCode'),
                        })
                page.on('response', on_response)
                page.goto(f"{report['baseUrl']}/use")
                page.locator('#link').fill(args.share_text)
                started = time.monotonic()
                page.locator('#submitButton').click()
                page.wait_for_function("document.querySelector('#submitButton').textContent.includes('确认并开始下载')", timeout=110000)
                report['durationSeconds'] = round(time.monotonic() - started, 3)
                title = page.locator('#mediaProbeTitle').inner_text()
                if args.expected_title not in title or page.locator('#mediaProbePreview').is_hidden():
                    raise AssertionError('live title/preview verification failed')
                if not any(item['success'] and item['videoStreamCount'] > 0 and args.expected_title in (item['title'] or '') for item in report['probes']):
                    raise AssertionError('live API metadata verification failed')
                report['button'] = page.locator('#submitButton').inner_text()
                report['title'] = title
                report['status'] = 'pass'
                page.screenshot(path=str(args.report.with_suffix('.png')), full_page=True)
            finally:
                browser.close()
    finally:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"LIVE_SHARE_TEXT=passed seconds={report['durationSeconds']} report={args.report.resolve()}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
