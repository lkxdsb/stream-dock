from __future__ import annotations

from collections import deque
from threading import Lock, Thread
from typing import Any, Callable

from .models import TaskStatus, utc_now_iso
from .store import TaskStore

SubtitleRunner = Callable[[dict[str, Any]], dict[str, Any]]


class SubtitleQueue:
    """Single-worker queue that enriches an already completed media task."""

    def __init__(self, store: TaskStore, runner: SubtitleRunner) -> None:
        self.store = store
        self.runner = runner
        self._queue: deque[tuple[str, dict[str, Any]]] = deque()
        self._lock = Lock()
        self._worker: Thread | None = None
        self._queued_ids: set[str] = set()
        self._active_task_id: str | None = None

    def submit(self, task_id: str, payload: dict[str, Any]) -> bool:
        task = self.store.get(task_id)
        if task is None or task.status != TaskStatus.COMPLETED:
            return False
        with self._lock:
            if task_id in self._queued_ids or task_id == self._active_task_id:
                return False
            self._queue.append((task_id, dict(payload)))
            self._queued_ids.add(task_id)
            self._ensure_worker_locked()
        return True

    def _ensure_worker_locked(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = Thread(target=self._run, name='streamdock-subtitle-queue', daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._active_task_id = None
                    return
                task_id, payload = self._queue.popleft()
                self._queued_ids.discard(task_id)
                self._active_task_id = task_id
            self._run_one(task_id, payload)
            with self._lock:
                if self._active_task_id == task_id:
                    self._active_task_id = None

    def _run_one(self, task_id: str, payload: dict[str, Any]) -> None:
        task = self.store.get(task_id)
        if task is None or task.status != TaskStatus.COMPLETED:
            return

        existing_result = dict(task.result or {})
        raw_existing_job = existing_result.get('subtitleJob')
        existing_job = dict(raw_existing_job) if isinstance(raw_existing_job, dict) else {}
        running_job = {
            **existing_job,
            'status': 'running',
            'message': '视频已可用，正在后台识别字幕',
            'startedAt': utc_now_iso(),
        }
        self.store.patch_result(
            task_id,
            {'subtitleJob': running_job},
            logs=[*task.logs, '视频下载已完成，可立即打开文件或目录', '后台字幕识别已开始'],
        )

        try:
            generated = dict(self.runner(dict(payload)) or {})
        except Exception as exc:  # pragma: no cover - defensive wrapper
            generated = {
                'status': 'failed',
                'message': '后台字幕识别失败，视频文件不受影响',
                'error': str(exc),
                'subtitles': [],
                'subtitleDetails': [],
            }

        current = self.store.get(task_id)
        if current is None:
            return
        current_result = dict(current.result or {})
        raw_current_assets = current_result.get('assets')
        current_assets = dict(raw_current_assets) if isinstance(raw_current_assets, dict) else {}
        current_subtitles = list(current_assets.get('subtitles') or [])
        current_details = list(current_assets.get('subtitleDetails') or [])
        generated_subtitles = [str(path) for path in generated.get('subtitles') or [] if path]
        generated_details = [dict(item) for item in generated.get('subtitleDetails') or [] if isinstance(item, dict)]
        merged_subtitles = list(dict.fromkeys([*current_subtitles, *generated_subtitles]))
        merged_details = [*current_details, *generated_details]
        final_status = str(generated.get('status') or ('completed' if generated_subtitles else 'unavailable'))
        final_message = str(generated.get('message') or (
            '字幕识别完成' if final_status == 'completed' else '未生成字幕，视频文件仍可正常使用'
        ))
        final_job = {
            **running_job,
            'status': final_status,
            'message': final_message,
            'completedAt': utc_now_iso(),
        }
        if generated.get('error'):
            final_job['error'] = str(generated['error'])
        updated_assets = {
            **current_assets,
            'subtitles': merged_subtitles,
            'subtitleDetails': merged_details,
        }
        completion_log = final_message
        if generated.get('error'):
            completion_log = f'{completion_log}：{generated["error"]}'
        self.store.patch_result(
            task_id,
            {
                'assets': updated_assets,
                'subtitleCount': max(int(current_result.get('subtitleCount') or 0), len(merged_subtitles)),
                'subtitleJob': final_job,
            },
            logs=[*current.logs, completion_log],
        )
