from __future__ import annotations

from collections import deque
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable

from .models import TaskKind, TaskStatus
from .store import TaskStore

PdfRunner = Callable[[dict[str, Any]], dict[str, Any]]


class PdfQueue:
    """Single-worker queue because local document inference is memory intensive."""

    def __init__(self, store: TaskStore, runner: PdfRunner) -> None:
        self.store = store
        self.runner = runner
        self._queue: deque[tuple[str, dict[str, Any]]] = deque()
        self._lock = Lock()
        self._worker: Thread | None = None
        self._cancelled: set[str] = set()

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = f"{payload.get('filename') or 'PDF'} · {str(payload.get('mode') or 'auto').upper()}"
        task = self.store.create(TaskKind.PDF, title, dict(payload))
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
            self.store.update(task_id, status=TaskStatus.CANCELLED, logs=['PDF 任务已取消'], error='任务已取消', stage='已取消', progress=None)
            self._cleanup_input(task.payload)
        else:
            self.store.update(task_id, logs=[*task.logs, '正在终止本地解析进程'], stage='正在取消')
        return True

    def _ensure_worker_locked(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = Thread(target=self._run, name='streamdock-pdf-queue', daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                task_id, payload = self._queue.popleft()
                cancelled = task_id in self._cancelled
            if cancelled:
                self._cleanup_input(payload)
                continue
            self._run_one(task_id, payload)

    def _run_one(self, task_id: str, payload: dict[str, Any]) -> None:
        self.store.update(task_id, status=TaskStatus.RUNNING, logs=['正在启动本地 PDF 解析引擎'], stage='正在解析文档', progress=10)
        try:
            result = self.runner({**payload, '_taskId': task_id})
            with self._lock:
                cancelled = task_id in self._cancelled
            if cancelled:
                self.store.update(task_id, status=TaskStatus.CANCELLED, logs=['PDF 任务已取消'], result=None, error='任务已取消', stage='已取消', progress=None)
            else:
                self.store.update(task_id, status=TaskStatus.COMPLETED, logs=['PDF 解析完成', *list(result.get('logs') or [])], result=result, error=None, stage='已完成', progress=100)
        except Exception as exc:
            with self._lock:
                cancelled = task_id in self._cancelled
            self.store.update(task_id, status=TaskStatus.CANCELLED if cancelled else TaskStatus.FAILED, logs=['PDF 解析未完成', str(exc)], error='任务已取消' if cancelled else str(exc), stage='已取消' if cancelled else '失败', progress=None)
        finally:
            self._cleanup_input(payload)

    @staticmethod
    def _cleanup_input(payload: dict[str, Any]) -> None:
        path = Path(str(payload.get('inputPath') or ''))
        try:
            if path.is_file():
                path.unlink()
            if path.parent.name == 'pdf-inputs' and not any(path.parent.iterdir()):
                path.parent.rmdir()
        except OSError:
            pass
