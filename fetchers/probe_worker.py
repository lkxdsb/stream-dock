"""Bound server probes in a process so disconnects cannot leave infinite work."""

from __future__ import annotations

import multiprocessing
import os
import signal
import threading
import time

from fetchers.auth_context import AuthProfile, use_auth
from fetchers.errors import MediaProbeError


_probe_slots = threading.BoundedSemaphore(2)


def _probe_child(conn, link: str, profile: AuthProfile | None, cookie: str | None, cookie_file: str | None) -> None:
    try:
        if hasattr(os, 'setsid'):
            os.setsid()
        from fetchers.adapters.bilibili import reset_manual_cookie_overrides, set_manual_cookie_overrides
        from fetchers.pipeline import probe_media
        tokens = set_manual_cookie_overrides(cookie, cookie_file)
        try:
            with use_auth(profile):
                result = probe_media(link)
            conn.send(('ok', result))
        finally:
            reset_manual_cookie_overrides(tokens)
    except MediaProbeError as exc:
        conn.send(('error', (exc.code, exc.stage, exc.retryable, str(exc), exc.retry_after,
                             exc.action, exc.causes)))
    except Exception as exc:
        from error_catalog import classify_probe_exception
        info = classify_probe_exception(exc)
        conn.send(('error', (info['code'], info['stage'], info['retryable'], info['message'],
                             info.get('retryAfter'), info.get('action'), info.get('causes', []))))
    finally:
        conn.close()


def probe_with_budget(link: str, profile: AuthProfile | None = None, *, cookie: str | None = None,
                      cookie_file: str | None = None, timeout_ms: int | None = None,
                      cancel_event: threading.Event | None = None):
    raw_budget = timeout_ms if timeout_ms is not None else int(os.getenv('STREAMDOCK_MEDIA_PROBE_TIMEOUT_MS', '90000'))
    minimum_ms = 250 if timeout_ms is not None else 5_000
    budget_seconds = max(minimum_ms, min(raw_budget, 180_000)) / 1000
    started = time.monotonic()
    if not _probe_slots.acquire(timeout=min(10, budget_seconds)):
        raise MediaProbeError('browser_busy', 'probe_queue', '媒体解析并发已满，请稍后重试', retryable=True)
    ctx = multiprocessing.get_context('spawn')
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_probe_child, args=(send, link, profile, cookie, cookie_file))
    try:
        if time.monotonic() - started >= budget_seconds:
            raise MediaProbeError('network_timeout', 'probe_budget', '媒体解析超过总时间预算', retryable=True)
        process.start()
        send.close()
        remaining = max(0, budget_seconds - (time.monotonic() - started))
        while not receive.poll(min(.25, remaining)):
            if cancel_event is not None and cancel_event.is_set():
                raise MediaProbeError('task_cancelled', 'probe_budget', '媒体诊断已取消')
            remaining -= min(.25, remaining)
            if remaining <= 0:
                raise MediaProbeError('network_timeout', 'probe_budget', '媒体解析超过总时间预算', retryable=True)
        try:
            state, payload = receive.recv()
        except EOFError as exc:
            raise MediaProbeError('parser_failed', 'probe_worker', '解析子进程意外退出') from exc
        process.join(timeout=1)
        if state == 'ok':
            return payload
        code, stage, retryable, message, retry_after, action, causes = payload
        raise MediaProbeError(code, stage, message, retryable=retryable,
                              retry_after=retry_after, action=action, causes=causes)
    finally:
        receive.close()
        send.close()
        if process.is_alive():
            try:
                if hasattr(os, 'getpgid') and os.getpgid(process.pid) == process.pid:
                    os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        process.close()
        _probe_slots.release()
