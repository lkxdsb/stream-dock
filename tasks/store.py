from __future__ import annotations

from collections import OrderedDict
import json
import logging
from pathlib import Path
import shutil
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from tasks.models import TaskItem, TaskKind, TaskStatus, utc_now_iso


_UNSET = object()
logger = logging.getLogger(__name__)


class TaskStore:
    def __init__(self, max_items: int = 300, storage_path: Path | None = None, on_remove: Callable[[TaskItem], None] | None = None) -> None:
        self.max_items = max_items
        self.storage_path = storage_path
        self.on_remove = on_remove
        self._items: OrderedDict[str, TaskItem] = OrderedDict()
        self._lock = Lock()
        self._load()

    def _load(self) -> None:
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            rows = json.loads(self.storage_path.read_text(encoding='utf-8'))
        except OSError as exc:
            logger.warning('无法读取任务历史文件 %s：%s', self.storage_path, exc)
            return
        except json.JSONDecodeError as exc:
            backup_path = self._backup_corrupt_storage()
            logger.warning('任务历史文件 JSON 已损坏，已保留备份 %s：%s', backup_path or '（备份失败）', exc)
            return

        if not isinstance(rows, list):
            backup_path = self._backup_corrupt_storage()
            logger.warning('任务历史文件根节点不是列表，已保留备份 %s', backup_path or '（备份失败）')
            return

        recovered_state_changed = False
        malformed_rows = 0
        for index, row in enumerate(rows[-self.max_items:]):
            try:
                if not isinstance(row, dict):
                    raise TypeError('任务记录不是对象')
                loaded_status = TaskStatus(str(row.get('status') or 'pending'))
                default_stage = {
                    TaskStatus.PENDING: '等待中',
                    TaskStatus.RUNNING: '处理中',
                    TaskStatus.COMPLETED: '已完成',
                    TaskStatus.FAILED: '失败',
                    TaskStatus.SKIPPED: '已跳过',
                    TaskStatus.CANCELLED: '已取消',
                }[loaded_status]
                loaded_stage = str(row.get('stage') or default_stage)
                if loaded_status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED} and loaded_stage in {'等待中', '处理中'}:
                    loaded_stage = default_stage
                task = TaskItem(
                    id=str(row['id']),
                    kind=TaskKind(str(row['kind'])),
                    title=str(row.get('title') or '本地任务'),
                    payload=dict(row.get('payload') or {}),
                    status=loaded_status,
                    logs=list(row.get('logs') or []),
                    result=dict(row['result']) if row.get('result') is not None else None,
                    error=row.get('error'),
                    stage=loaded_stage,
                    progress=float(row['progress']) if row.get('progress') is not None else None,
                    created_at=str(row.get('createdAt') or utc_now_iso()),
                    updated_at=str(row.get('updatedAt') or utc_now_iso()),
                )
                raw_subtitle_job = (task.result or {}).get('subtitleJob')
                subtitle_job = dict(raw_subtitle_job) if isinstance(raw_subtitle_job, dict) else {}
                if task.status == TaskStatus.COMPLETED and subtitle_job.get('status') in {'pending', 'running'}:
                    subtitle_job.update({
                        'status': 'interrupted',
                        'message': '本地服务重启，后台字幕识别已中断；视频文件不受影响',
                    })
                    task.result = {**(task.result or {}), 'subtitleJob': subtitle_job}
                    task.logs = [*task.logs, '后台字幕识别因本地服务重启而中断，视频文件仍可正常使用']
                    task.updated_at = utc_now_iso()
                    recovered_state_changed = True
                if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                    task.status = TaskStatus.FAILED
                    task.error = '本地服务重启，上次未完成任务已中断'
                    task.logs = [*task.logs, task.error]
                    task.updated_at = utc_now_iso()
                    task.stage = '已中断'
                    recovered_state_changed = True
                self._items[task.id] = task
            except (ValueError, TypeError, KeyError) as exc:
                malformed_rows += 1
                logger.warning('跳过无法恢复的任务记录（索引 %s）：%s', index, exc)

        if malformed_rows:
            backup_path = self._backup_corrupt_storage()
            logger.warning('任务历史中有 %s 条无效记录，原文件已备份到 %s', malformed_rows, backup_path or '（备份失败）')

        if recovered_state_changed or malformed_rows:
            try:
                self._persist_locked()
            except OSError as exc:
                logger.warning('无法保存恢复后的任务历史：%s', exc)

    def _backup_corrupt_storage(self) -> Path | None:
        if not self.storage_path or not self.storage_path.exists():
            return None
        candidate = self.storage_path.with_name(f'{self.storage_path.name}.corrupt.bak')
        suffix = 1
        while candidate.exists():
            candidate = self.storage_path.with_name(f'{self.storage_path.name}.corrupt.{suffix}.bak')
            suffix += 1
        try:
            shutil.copy2(self.storage_path, candidate)
        except OSError as exc:
            logger.warning('无法备份损坏的任务历史文件 %s：%s', self.storage_path, exc)
            return None
        return candidate

    def _persist_locked(self) -> None:
        if not self.storage_path:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.storage_path.with_suffix('.tmp')
        try:
            temp_path.write_text(
                json.dumps([task.to_dict() for task in self._items.values()], ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            temp_path.replace(self.storage_path)
        except OSError:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def create(self, kind: TaskKind, title: str, payload: dict[str, Any]) -> TaskItem:
        task = TaskItem(
            id=uuid4().hex,
            kind=kind,
            title=title,
            payload=payload,
        )
        with self._lock:
            self._items[task.id] = task
            while len(self._items) > self.max_items:
                removable_id = next((
                    item_id for item_id, item in self._items.items()
                    if item.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}
                ), None)
                if removable_id is None:
                    break
                removed = self._items.pop(removable_id)
                self._notify_removed(removed)
            self._persist_locked()
        return task

    def get(self, task_id: str) -> TaskItem | None:
        with self._lock:
            return self._items.get(task_id)

    def list(self, kind: TaskKind | None = None) -> list[TaskItem]:
        with self._lock:
            items = list(reversed(self._items.values()))
        if kind is not None:
            items = [task for task in items if task.kind == kind]
        return items

    def update(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        logs: list[str] | None = None,
        result: dict[str, Any] | None | object = _UNSET,
        error: str | None | object = _UNSET,
        stage: str | None = None,
        progress: float | None | object = _UNSET,
    ) -> TaskItem | None:
        with self._lock:
            task = self._items.get(task_id)
            if task is None:
                return None
            if status is not None:
                task.status = status
            if logs is not None:
                task.logs = logs
            if result is not _UNSET:
                task.result = result
            if error is not _UNSET:
                task.error = error
            if stage is not None:
                task.stage = stage
            if progress is not _UNSET:
                task.progress = None if progress is None else max(0.0, min(100.0, float(progress)))
            task.updated_at = utc_now_iso()
            self._persist_locked()
            return task

    def patch_result(
        self,
        task_id: str,
        values: dict[str, Any],
        *,
        logs: list[str] | None = None,
    ) -> TaskItem | None:
        """Atomically merge background-stage fields into an existing task result."""
        with self._lock:
            task = self._items.get(task_id)
            if task is None:
                return None
            task.result = {**(task.result or {}), **values}
            if logs is not None:
                task.logs = list(logs)
            task.updated_at = utc_now_iso()
            self._persist_locked()
            return task

    def clear(self, kind: TaskKind | None = None) -> int:
        with self._lock:
            if kind is None:
                deleted_count = len(self._items)
                removed = list(self._items.values())
                self._items.clear()
                for task in removed:
                    self._notify_removed(task)
                self._persist_locked()
                return deleted_count

            task_ids = [task_id for task_id, task in self._items.items() if task.kind == kind]
            for task_id in task_ids:
                self._notify_removed(self._items.pop(task_id))
            self._persist_locked()
            return len(task_ids)

    def clear_finished(self, kind: TaskKind | None = None) -> int:
        finished = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}
        with self._lock:
            task_ids = [
                task_id for task_id, task in self._items.items()
                if (
                    task.status in finished
                    and (kind is None or task.kind == kind)
                    and not (
                        isinstance((task.result or {}).get('subtitleJob'), dict)
                        and str((task.result or {})['subtitleJob'].get('status') or '') in {'pending', 'running'}
                    )
                )
            ]
            for task_id in task_ids:
                self._notify_removed(self._items.pop(task_id))
            self._persist_locked()
            return len(task_ids)

    def delete(self, task_id: str) -> TaskItem | None:
        with self._lock:
            task = self._items.pop(task_id, None)
            if task is not None:
                self._notify_removed(task)
                self._persist_locked()
            return task

    def _notify_removed(self, task: TaskItem) -> None:
        if self.on_remove is None:
            return
        try:
            self.on_remove(task)
        except Exception as exc:
            logger.warning('清理任务关联资源失败 %s：%s', task.id, exc)
