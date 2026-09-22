"""Shared, optional Playwright runtime for media capture and capability checks."""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from fetchers.errors import MediaProbeError


class BrowserUnavailableError(MediaProbeError):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__('browser_unavailable', 'browser_launch', 'Browser unavailable: ' + '; '.join(reasons),
                         causes=reasons)


class BrowserBusyError(MediaProbeError):
    def __init__(self, message: str):
        super().__init__('browser_busy', 'browser_queue', message, retryable=True)


_slots = threading.BoundedSemaphore(max(1, int(os.getenv('STREAMDOCK_BROWSER_CONCURRENCY', '2'))))
_check_lock = threading.Lock()
_cached_check: dict[str, Any] | None = None
_checked_at = 0.0
_check_mode: tuple[str, str] | None = None
CHECK_TTL_SECONDS = 300


def browser_mode() -> str:
    mode = os.getenv('STREAMDOCK_BROWSER_MODE', 'auto').strip().lower()
    if mode not in {'auto', 'chromium', 'chrome', 'disabled'}:
        raise ValueError('Invalid STREAMDOCK_BROWSER_MODE (auto/chromium/chrome/disabled)')
    return mode


@contextmanager
def browser_context(*, user_agent: str | None = None, queue_timeout_seconds: float = 10) -> Iterator[tuple[Any, str, str]]:
    """Yield an isolated context, runtime name and browser version; always release it."""
    mode = browser_mode()
    if mode == 'disabled':
        raise BrowserUnavailableError(['browser mode disabled'])
    if not _slots.acquire(timeout=queue_timeout_seconds):
        raise BrowserBusyError('Browser concurrency limit reached')
    try:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserUnavailableError(['Playwright package is not installed']) from exc
        reasons: list[str] = []
        with sync_playwright() as playwright:
            choices = ('chromium', 'chrome') if mode == 'auto' else (mode,)
            browser = None
            selected = ''
            for choice in choices:
                try:
                    kwargs: dict[str, Any] = {'headless': True, 'timeout': int(os.getenv('STREAMDOCK_BROWSER_LAUNCH_TIMEOUT_MS', '10000'))}
                    if choice == 'chrome':
                        kwargs['channel'] = 'chrome'
                    browser = playwright.chromium.launch(**kwargs)
                    selected = choice
                    break
                except Exception as exc:
                    reason = str(exc).splitlines()[0][:240]
                    reasons.append(f'{choice}: {type(exc).__name__}: {reason}')
                    # Another launch cannot repair host resource exhaustion.
                    if any(marker in str(exc).lower() for marker in (
                        'enomem', 'out of memory', 'cannot allocate memory',
                        'resource temporarily unavailable', 'too many open files',
                    )):
                        raise BrowserBusyError('Browser host resources are exhausted') from exc
            if browser is None:
                raise BrowserUnavailableError(reasons)
            try:
                kwargs = {'viewport': {'width': 1440, 'height': 900}, 'locale': 'zh-CN'}
                if user_agent:
                    kwargs['user_agent'] = user_agent
                context = browser.new_context(**kwargs)
                try:
                    from fetchers.auth_context import browser_cookies, current_auth
                    profile = current_auth()
                    if profile:
                        context.add_cookies(browser_cookies(profile))
                    yield context, selected, browser.version
                finally:
                    context.close()
            finally:
                browser.close()
    finally:
        _slots.release()


def browser_capability(*, refresh: bool = False) -> dict[str, Any]:
    """Cache a real local JS/DOM smoke test; never contact a media provider."""
    global _cached_check, _checked_at, _check_mode
    try:
        mode = browser_mode()
    except ValueError as exc:
        return {'status': 'error', 'runtime': None, 'version': None, 'detail': str(exc),
                'checkedAt': datetime.now(timezone.utc).isoformat(), 'durationMs': 0}
    config_key = (mode, os.getenv('STREAMDOCK_BROWSER_LAUNCH_TIMEOUT_MS', '10000'))
    if not refresh:
        cached = dict(_cached_check) if _cached_check and _check_mode == config_key else None
        if cached is None:
            return {'status': 'unchecked', 'runtime': None, 'version': None,
                    'detail': '尚未执行浏览器启动检查', 'checkedAt': None, 'stale': False,
                    'checking': _check_lock.locked()}
        cached['stale'] = time.monotonic() - _checked_at >= CHECK_TTL_SECONDS
        cached['checking'] = _check_lock.locked()
        return cached
    seen_at = _checked_at
    with _check_lock:
        if _checked_at != seen_at and _cached_check and _check_mode == config_key:
            return dict(_cached_check)
        started = time.monotonic()
        result: dict[str, Any] = {'status': 'missing', 'runtime': None, 'version': None}
        try:
            with browser_context(queue_timeout_seconds=2) as (context, runtime, version):
                page = context.new_page()
                page.goto('about:blank')
                page.set_content('<main id="streamdock-check">ready</main>')
                if page.evaluate('document.querySelector("#streamdock-check").textContent') != 'ready':
                    raise RuntimeError('Browser DOM/JavaScript check failed')
                result.update(status='ok', runtime=runtime, version=version)
        except BrowserUnavailableError as exc:
            result['detail'] = '; '.join(exc.reasons)
            if mode == 'disabled':
                result['status'] = 'disabled'
        except BrowserBusyError as exc:
            result.update(status='warning', detail=str(exc))
        except Exception as exc:
            result.update(status='error', detail=f'{type(exc).__name__}: {str(exc).splitlines()[0][:240]}')
        result['checkedAt'] = datetime.now(timezone.utc).isoformat()
        result['durationMs'] = round((time.monotonic() - started) * 1000)
        result['stale'] = False
        result['checking'] = False
        result.setdefault('detail', f"{result['runtime']} {result['version']} · JavaScript/DOM 可执行")
        # Capacity contention is transient; do not cache it as a missing dependency.
        if result['status'] != 'warning':
            _cached_check, _checked_at, _check_mode = result, time.monotonic(), config_key
        return dict(result)
