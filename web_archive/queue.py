from __future__ import annotations

from collections import deque
from threading import Lock, Thread
from typing import Any, Callable
from urllib.parse import urlparse

from tasks.models import TaskKind, TaskStatus
from tasks.store import TaskStore

WebArchiveRunner = Callable[[dict[str, Any]], dict[str, Any]]


class WebArchiveQueue:
    """Single-worker queue for web page archival tasks."""

    def __init__(self, store: TaskStore, runner: WebArchiveRunner) -> None:
        self.store = store
        self.runner = runner
        self._queue: deque[tuple[str, dict[str, Any]]] = deque()
        self._lock = Lock()
        self._worker: Thread | None = None
        self._cancelled: set[str] = set()

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get('url') or '')
        host = urlparse(url).netloc or '未知来源'
        title = f'网页存档 · {host}'
        task = self.store.create(TaskKind.WEB_ARCHIVE, title, dict(payload))
        with self._lock:
            self._queue.append((task.id, dict(payload)))
            self._ensure_worker_locked()
        return task.to_dict()

    def cancel(self, task_id: str) -> bool:
        task = self.store.get(task_id)
        if task is None or task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            return False
        with self._lock:
            self._cancelled.add(task_id)
        if task.status == TaskStatus.PENDING:
            self.store.update(task_id, status=TaskStatus.CANCELLED, logs=['网页存档任务已取消'], error='任务已取消', stage='已取消', progress=None)
        else:
            self.store.update(task_id, logs=[*task.logs, '正在取消网页存档任务'], stage='正在取消')
        return True

    def _ensure_worker_locked(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = Thread(target=self._run, name='streamdock-web-archive-queue', daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                task_id, payload = self._queue.popleft()
                cancelled = task_id in self._cancelled
            if cancelled:
                continue
            self._run_one(task_id, payload)

    def _run_one(self, task_id: str, payload: dict[str, Any]) -> None:
        self.store.update(task_id, status=TaskStatus.RUNNING, logs=['正在启动网页存档任务'], stage='正在获取页面', progress=10)
        try:
            result = self.runner({**payload, '_taskId': task_id})
            if not bool(result.get('success')):
                raise RuntimeError(str(result.get('error') or '网页存档失败'))
            with self._lock:
                cancelled = task_id in self._cancelled
            if cancelled:
                self.store.update(task_id, status=TaskStatus.CANCELLED, logs=['网页存档任务已取消'], result=None, error='任务已取消', stage='已取消', progress=None)
            else:
                self.store.update(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    logs=['网页存档完成', *list(result.get('logs') or [])],
                    result=result,
                    error=None,
                    stage='已完成',
                    progress=100,
                )
        except Exception as exc:
            with self._lock:
                cancelled = task_id in self._cancelled
            self.store.update(
                task_id,
                status=TaskStatus.CANCELLED if cancelled else TaskStatus.FAILED,
                logs=['网页存档未完成', str(exc)],
                error='任务已取消' if cancelled else str(exc),
                stage='已取消' if cancelled else '失败',
                progress=None,
            )
