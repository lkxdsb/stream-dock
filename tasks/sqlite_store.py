from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from tasks.models import TaskItem, TaskKind, TaskStatus, redact_payload, utc_now_iso
from tasks.store import _UNSET


logger = logging.getLogger(__name__)
_FINISHED = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}


def migrate_legacy_json(legacy_path: Path, store: 'SQLiteTaskStore') -> int:
    if not legacy_path.exists():
        return 0
    from tasks.store import TaskStore
    legacy = TaskStore(storage_path=legacy_path)
    imported = store.import_tasks(list(reversed(legacy.list())))
    if imported:
        backup = legacy_path.with_name(f'{legacy_path.name}.migrated.bak')
        suffix = 1
        while backup.exists():
            backup = legacy_path.with_name(f'{legacy_path.name}.migrated.{suffix}.bak')
            suffix += 1
        legacy_path.replace(backup)
    return imported


class SQLiteTaskStore:
    """Transaction-backed task store safe for concurrent threads/processes."""

    def __init__(
        self,
        storage_path: Path,
        max_items: int = 300,
        on_remove: Callable[[TaskItem], None] | None = None,
        *,
        recover_interrupted: bool = True,
    ) -> None:
        self.storage_path = storage_path
        self.max_items = max_items
        self.on_remove = on_remove
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if recover_interrupted:
            self._recover_interrupted()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.storage_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA busy_timeout = 10000')
        connection.execute('PRAGMA foreign_keys = ON')
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute('PRAGMA journal_mode = WAL')
            connection.execute('PRAGMA synchronous = NORMAL')
            connection.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    logs_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    stage TEXT NOT NULL,
                    progress REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            connection.execute('CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)')
            connection.execute('CREATE INDEX IF NOT EXISTS idx_tasks_kind_status ON tasks(kind, status)')

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> TaskItem | None:
        if row is None:
            return None
        return TaskItem(
            id=str(row['id']), kind=TaskKind(str(row['kind'])), title=str(row['title']),
            payload=dict(json.loads(row['payload_json'])), status=TaskStatus(str(row['status'])),
            logs=list(json.loads(row['logs_json'])),
            result=dict(json.loads(row['result_json'])) if row['result_json'] is not None else None,
            error=row['error'], stage=str(row['stage']),
            progress=float(row['progress']) if row['progress'] is not None else None,
            created_at=str(row['created_at']), updated_at=str(row['updated_at']),
        )

    @staticmethod
    def _values(task: TaskItem) -> tuple[Any, ...]:
        return (
            task.id, task.kind.value, task.title,
            json.dumps(redact_payload(task.payload), ensure_ascii=False), task.status.value,
            json.dumps(task.logs, ensure_ascii=False),
            json.dumps(task.result, ensure_ascii=False) if task.result is not None else None,
            task.error, task.stage, task.progress, task.created_at, task.updated_at,
        )

    def _insert(self, connection: sqlite3.Connection, task: TaskItem) -> None:
        connection.execute(
            'INSERT OR REPLACE INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            self._values(task),
        )

    def _recover_interrupted(self) -> None:
        message = '本地服务重启，上次未完成任务已中断'
        now = utc_now_iso()
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status IN ('pending', 'running') OR (status = 'completed' AND result_json LIKE '%\"subtitleJob\"%')"
            ).fetchall()
            for row in rows:
                task = self._decode(row)
                assert task is not None
                subtitle = (task.result or {}).get('subtitleJob')
                if task.status == TaskStatus.COMPLETED and isinstance(subtitle, dict) and subtitle.get('status') in {'pending', 'running'}:
                    task.result = {**(task.result or {}), 'subtitleJob': {**subtitle, 'status': 'interrupted', 'message': '本地服务重启，后台字幕识别已中断；视频文件不受影响'}}
                    if not task.logs or task.logs[-1] != '后台字幕识别因本地服务重启而中断，视频文件仍可正常使用':
                        task.logs.append('后台字幕识别因本地服务重启而中断，视频文件仍可正常使用')
                elif task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                    task.status = TaskStatus.FAILED
                    task.error = message
                    task.stage = '已中断'
                    if not task.logs or task.logs[-1] != message:
                        task.logs.append(message)
                else:
                    continue
                task.updated_at = now
                self._insert(connection, task)

    def create(self, kind: TaskKind, title: str, payload: dict[str, Any]) -> TaskItem:
        task = TaskItem(id=uuid4().hex, kind=kind, title=title, payload=payload)
        removed: list[TaskItem] = []
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            self._insert(connection, task)
            overflow = int(connection.execute('SELECT MAX(COUNT(*) - ?, 0) FROM tasks', (self.max_items,)).fetchone()[0])
            if overflow:
                placeholders = ','.join('?' for _ in _FINISHED)
                rows = connection.execute(
                    f'SELECT * FROM tasks WHERE status IN ({placeholders}) ORDER BY created_at ASC LIMIT ?',
                    (*[status.value for status in _FINISHED], overflow),
                ).fetchall()
                removed = [item for row in rows if (item := self._decode(row)) is not None]
                connection.executemany('DELETE FROM tasks WHERE id = ?', [(item.id,) for item in removed])
        for item in removed:
            self._notify_removed(item)
        return task

    def get(self, task_id: str) -> TaskItem | None:
        with self._connect() as connection:
            return self._decode(connection.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone())

    def list(self, kind: TaskKind | None = None) -> list[TaskItem]:
        with self._connect() as connection:
            if kind is None:
                rows = connection.execute('SELECT * FROM tasks ORDER BY created_at DESC').fetchall()
            else:
                rows = connection.execute('SELECT * FROM tasks WHERE kind = ? ORDER BY created_at DESC', (kind.value,)).fetchall()
        return [item for row in rows if (item := self._decode(row)) is not None]

    def update(self, task_id: str, status: TaskStatus | None = None, logs: list[str] | None = None,
               result: dict[str, Any] | None | object = _UNSET, error: str | None | object = _UNSET,
               stage: str | None = None, progress: float | None | object = _UNSET) -> TaskItem | None:
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            task = self._decode(connection.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone())
            if task is None:
                return None
            if status is not None: task.status = status
            if logs is not None: task.logs = list(logs)
            if result is not _UNSET: task.result = result
            if error is not _UNSET: task.error = error
            if stage is not None: task.stage = stage
            if progress is not _UNSET: task.progress = None if progress is None else max(0.0, min(100.0, float(progress)))
            task.updated_at = utc_now_iso()
            self._insert(connection, task)
            return task

    def patch_result(self, task_id: str, values: dict[str, Any], *, logs: list[str] | None = None) -> TaskItem | None:
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            task = self._decode(connection.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone())
            if task is None:
                return None
            task.result = {**(task.result or {}), **values}
            if logs is not None: task.logs = list(logs)
            task.updated_at = utc_now_iso()
            self._insert(connection, task)
            return task

    def clear(self, kind: TaskKind | None = None) -> int:
        return self._delete_where('kind = ?', (kind.value,)) if kind is not None else self._delete_where('1 = 1', ())

    def clear_finished(self, kind: TaskKind | None = None) -> int:
        conditions = ["status IN ('completed', 'failed', 'skipped', 'cancelled')"]
        values: list[Any] = []
        if kind is not None:
            conditions.append('kind = ?'); values.append(kind.value)
        removed = []
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute(f"SELECT * FROM tasks WHERE {' AND '.join(conditions)}", values).fetchall()
            for row in rows:
                task = self._decode(row)
                subtitle = (task.result or {}).get('subtitleJob') if task else None
                if task and not (isinstance(subtitle, dict) and subtitle.get('status') in {'pending', 'running'}):
                    removed.append(task)
            connection.executemany('DELETE FROM tasks WHERE id = ?', [(task.id,) for task in removed])
        for task in removed: self._notify_removed(task)
        return len(removed)

    def delete(self, task_id: str) -> TaskItem | None:
        removed = self._delete_where('id = ?', (task_id,))
        return removed[0] if removed else None

    def _delete_where(self, where: str, values: tuple[Any, ...]) -> list[TaskItem]:
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute(f'SELECT * FROM tasks WHERE {where}', values).fetchall()
            removed = [item for row in rows if (item := self._decode(row)) is not None]
            connection.execute(f'DELETE FROM tasks WHERE {where}', values)
        for task in removed: self._notify_removed(task)
        return removed

    def import_tasks(self, tasks: list[TaskItem]) -> int:
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            for task in tasks:
                self._insert(connection, task)
        return len(tasks)

    def _notify_removed(self, task: TaskItem) -> None:
        if self.on_remove is None:
            return
        try:
            self.on_remove(task)
        except Exception as exc:
            logger.warning('清理任务关联资源失败 %s：%s', task.id, exc)
