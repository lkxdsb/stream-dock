from __future__ import annotations

from collections import deque
from threading import Lock, Thread
from time import sleep
from typing import Any, Callable

from .models import TaskKind, TaskStatus
from .store import TaskStore

MediaRunner = Callable[[dict[str, Any]], dict[str, Any]]
MediaSuccessHook = Callable[[str, dict[str, Any], dict[str, Any]], None]


class MediaQueue:
    """Conservative single-worker media parsing queue."""

    def __init__(
        self,
        store: TaskStore,
        runner: MediaRunner,
        interval_seconds: float = 2.0,
        success_hook: MediaSuccessHook | None = None,
    ) -> None:
        self.store = store
        self.runner = runner
        self.interval_seconds = interval_seconds
        self.success_hook = success_hook
        self._queue: deque[tuple[str, dict[str, Any]]] = deque()
        self._lock = Lock()
        self._worker: Thread | None = None
        self._cancelled: set[str] = set()
        self._paused = False

    def submit(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tasks = []
        with self._lock:
            for payload in payloads:
                link = str(payload.get('link') or '').strip()
                title = link if len(link) <= 42 else f'{link[:42]}...'
                task = self.store.create(TaskKind.MEDIA, title or '媒体解析任务', dict(payload))
                self._queue.append((task.id, dict(payload)))
                tasks.append(task.to_dict())
            self._ensure_worker_locked()
        return tasks

    def cancel(self, task_id: str) -> bool:
        """Cancel a queued task. Running subprocesses cannot be killed safely here."""
        task = self.store.get(task_id)
        if task is None or task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            return False
        with self._lock:
            self._cancelled.add(task_id)
        if task.status == TaskStatus.PENDING:
            self.store.update(task_id, status=TaskStatus.CANCELLED, logs=['已取消'], error='任务已取消', stage='已取消', progress=None)
        else:
            self.store.update(task_id, logs=[*task.logs, '已请求取消，正在终止当前处理'], stage='正在取消')
        return True

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._ensure_worker_locked()

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def _ensure_worker_locked(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = Thread(target=self._run, name='streamdock-media-queue', daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                paused = self._paused
                if paused:
                    task_id = ''
                    payload = {}
                    cancelled = False
                else:
                    task_id, payload = self._queue.popleft()
                    cancelled = task_id in self._cancelled
            if paused:
                sleep(0.25)
                continue
            if cancelled:
                self.store.update(task_id, status=TaskStatus.CANCELLED, logs=['已取消'], error='任务已取消', stage='已取消', progress=None)
                continue
            self._run_one(task_id, payload)
            if self.interval_seconds > 0:
                sleep(self.interval_seconds)

    def _run_one(self, task_id: str, payload: dict[str, Any]) -> None:
        link = str(payload.get('link') or '')
        self.store.update(task_id, status=TaskStatus.RUNNING, logs=['正在识别并处理媒体资源', link], stage='识别中', progress=3)
        try:
            result = self.runner({**payload, '_taskId': task_id})
        except Exception as exc:  # pragma: no cover - defensive wrapper
            self.store.update(task_id, status=TaskStatus.FAILED, logs=['媒体资源处理失败', str(exc)], error=str(exc), stage='失败', progress=None)
            return

        with self._lock:
            cancelled = task_id in self._cancelled
        if cancelled:
            self.store.update(task_id, status=TaskStatus.CANCELLED, logs=['当前阶段已结束', '任务已取消'], result=None, error='任务已取消', stage='已取消', progress=None)
            return

        stdout = str(result.get('stdout') or '').strip()
        stderr = str(result.get('stderr') or '').strip()
        logs = [line for line in ['输出文件已生成' if result.get('success') else '媒体资源处理失败', stdout, stderr] if line]
        if result.get('success'):
            result_copy = dict(result)
            stage = (
                '图片已下载'
                if result_copy.get('mediaKind') == 'images'
                else '视频已下载'
                if result_copy.get('outputPath')
                else '已完成'
            )
            self.store.update(task_id, status=TaskStatus.COMPLETED, logs=logs, result=result_copy, error=None, stage=stage, progress=100)
            if self.success_hook is not None:
                try:
                    self.success_hook(task_id, dict(payload), result_copy)
                except Exception as exc:  # The media file must remain successful even if enrichment cannot start.
                    current = self.store.get(task_id)
                    current_logs = list(current.logs if current else logs)
                    self.store.patch_result(
                        task_id,
                        {
                            'subtitleJob': {
                                'status': 'failed',
                                'message': '字幕后台任务启动失败，视频文件不受影响',
                                'error': str(exc),
                            }
                        },
                        logs=[*current_logs, f'字幕后台任务启动失败：{exc}'],
                    )
        else:
            error = str(result.get('error') or stderr or stdout or '解析失败')
            self.store.update(task_id, status=TaskStatus.FAILED, logs=logs, result=dict(result), error=error, stage='失败', progress=None)
