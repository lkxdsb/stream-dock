from __future__ import annotations

import os
from contextlib import contextmanager
from threading import BoundedSemaphore, Lock

from .registry import find_capability


_DEFAULT_LIMITS = {
    'ffmpeg': 2,
    'pillow': 4,
    'python-archive': 2,
    'python/openpyxl': 4,
    'python-docx/libreoffice': 1,
    'python-docx/markdown/reportlab': 2,
    'ebooklib': 2,
    'cairosvg': 2,
    'local': 4,
}
_semaphores: dict[str, BoundedSemaphore] = {}
_semaphore_limits: dict[str, int] = {}
_states: dict[str, dict[str, int]] = {}
_lock = Lock()


def engine_limit(engine: str) -> int:
    key = ''.join(character if character.isalnum() else '_' for character in engine.upper()).strip('_')
    return max(1, int(os.getenv(f'STREAMDOCK_ENGINE_{key}_CONCURRENCY', str(_DEFAULT_LIMITS.get(engine, 2)))))


def engine_for_route(source: str, target: str) -> str:
    capability = find_capability(source, target)
    return capability.engine if capability else 'local'


@contextmanager
def conversion_engine_slot(source: str, target: str):
    engine = engine_for_route(source, target)
    limit = engine_limit(engine)
    with _lock:
        semaphore = _semaphores.get(engine)
        if semaphore is None or _semaphore_limits.get(engine) != limit:
            semaphore = BoundedSemaphore(limit)
            _semaphores[engine] = semaphore
            _semaphore_limits[engine] = limit
        state = _states.setdefault(engine, {'active': 0, 'waiting': 0, 'maxActive': 0})
        state['waiting'] += 1
    wait_seconds = max(1, int(os.getenv('STREAMDOCK_ENGINE_QUEUE_WAIT_SECONDS', '300')))
    if not semaphore.acquire(timeout=wait_seconds):
        with _lock:
            _states[engine]['waiting'] -= 1
        raise RuntimeError(f'{engine} 转换队列等待超时（{wait_seconds} 秒）')
    with _lock:
        state = _states[engine]
        state['waiting'] -= 1
        state['active'] += 1
        state['maxActive'] = max(state['maxActive'], state['active'])
    try:
        yield engine, limit
    finally:
        with _lock:
            _states[engine]['active'] -= 1
        semaphore.release()


def configured_engine_limits() -> list[dict[str, object]]:
    with _lock:
        states = {engine: dict(state) for engine, state in _states.items()}
    return [{
        'engine': engine,
        'concurrency': engine_limit(engine),
        **states.get(engine, {'active': 0, 'waiting': 0, 'maxActive': 0}),
    } for engine in sorted(_DEFAULT_LIMITS)]
