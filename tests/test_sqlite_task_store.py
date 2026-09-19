from __future__ import annotations

import tempfile
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from tasks.models import TaskKind, TaskStatus
from tasks.sqlite_store import SQLiteTaskStore
from tasks.sqlite_store import migrate_legacy_json
from tasks.store import TaskStore
from tasks.artifacts import artifact_summary, resolve_artifact, seal_artifact, task_output_dir
from converters.pipeline import convert_file


def test_sqlite_store_persists_real_task_and_unicode_payload():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'tasks.sqlite3'
        store = SQLiteTaskStore(path, recover_interrupted=False)
        task = store.create(TaskKind.CONVERT, '真实文件转换 😀', {'filename': '中文.csv'})
        store.update(task.id, status=TaskStatus.COMPLETED, result={'outputPath': '/tmp/结果.json'})

        loaded = SQLiteTaskStore(path, recover_interrupted=False).get(task.id)

        assert loaded is not None
        assert loaded.title == '真实文件转换 😀'
        assert loaded.payload['filename'] == '中文.csv'
        assert loaded.result == {'outputPath': '/tmp/结果.json'}


def test_sqlite_store_never_persists_sensitive_payload_values():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'tasks.sqlite3'
        store = SQLiteTaskStore(path, recover_interrupted=False)
        task = store.create(TaskKind.MEDIA, 'cookie', {'link': 'https://example.com', 'accessToken': 'secret-token'})

        loaded = store.get(task.id)
        assert loaded is not None and loaded.payload['accessToken'] == '[REDACTED]'
        assert b'secret-token' not in path.read_bytes()


def test_sqlite_store_concurrent_patch_result_keeps_database_readable():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'tasks.sqlite3'
        store = SQLiteTaskStore(path, recover_interrupted=False)
        tasks = [store.create(TaskKind.MEDIA, f'task-{index}', {}) for index in range(24)]

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda pair: store.patch_result(pair[1].id, {'index': pair[0]}), enumerate(tasks)))

        restored = SQLiteTaskStore(path, recover_interrupted=False)
        assert len(restored.list()) == 24
        assert {restored.get(task.id).result['index'] for task in tasks} == set(range(24))


def test_sqlite_restart_recovery_is_transactional_and_only_applied_once():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'tasks.sqlite3'
        store = SQLiteTaskStore(path, recover_interrupted=False)
        task = store.create(TaskKind.MEDIA, 'running', {})
        store.update(task.id, status=TaskStatus.RUNNING, logs=['started'])

        first = SQLiteTaskStore(path).get(task.id)
        second = SQLiteTaskStore(path).get(task.id)

        assert first is not None and second is not None
        assert second.status == TaskStatus.FAILED
        assert second.logs.count('本地服务重启，上次未完成任务已中断') == 1


def test_sqlite_capacity_never_evicts_active_tasks_and_cleans_terminal_rows():
    removed = []
    with tempfile.TemporaryDirectory() as tmp:
        store = SQLiteTaskStore(Path(tmp) / 'tasks.sqlite3', max_items=2, on_remove=removed.append, recover_interrupted=False)
        first = store.create(TaskKind.CONVERT, 'active-1', {})
        second = store.create(TaskKind.CONVERT, 'active-2', {})
        third = store.create(TaskKind.CONVERT, 'active-3', {})
        assert {item.id for item in store.list()} == {first.id, second.id, third.id}

        store.update(first.id, status=TaskStatus.COMPLETED)
        fourth = store.create(TaskKind.CONVERT, 'active-4', {})

        assert store.get(first.id) is None
        assert removed and removed[0].id == first.id
        assert {item.id for item in store.list()} == {second.id, third.id, fourth.id}


def test_sqlite_store_migrates_legacy_json_and_preserves_backup():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        legacy_path = root / 'tasks.json'
        legacy = TaskStore(storage_path=legacy_path)
        task = legacy.create(TaskKind.CONVERT, '旧任务中文', {'filename': '旧文件.csv'})
        legacy.update(task.id, status=TaskStatus.COMPLETED, result={'outputPath': '/tmp/旧结果.json'})
        sqlite = SQLiteTaskStore(root / 'tasks.sqlite3', recover_interrupted=False)

        assert migrate_legacy_json(legacy_path, sqlite) == 1
        restored = sqlite.get(task.id)
        assert restored is not None and restored.result['outputPath'] == '/tmp/旧结果.json'
        assert not legacy_path.exists()
        assert len(list(root.glob('tasks.json.migrated*.bak'))) == 1


def test_sqlite_real_file_conversion_artifact_survives_store_reopen():
    with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'STREAMDOCK_ARTIFACT_ROOT': str(Path(tmp) / 'artifacts')}):
        root = Path(tmp)
        store = SQLiteTaskStore(root / 'tasks.sqlite3', recover_interrupted=False)
        task = store.create(TaskKind.CONVERT, '复杂中文 CSV → JSON', {'filename': '复杂.csv'})
        source = root / '复杂.csv'
        source.write_text('姓名,备注\n张三,中文😀与多行内容\n', encoding='utf-8')

        converted = convert_file(source, source.name, 'csv', 'json', task_output_dir(task.id))
        assert converted.success and converted.output_path is not None
        manifest = seal_artifact(task.id, converted.output_path)
        store.update(task.id, status=TaskStatus.COMPLETED, result={
            'outputPath': str(converted.output_path),
            'artifact': artifact_summary(manifest),
        })

        reopened = SQLiteTaskStore(root / 'tasks.sqlite3', recover_interrupted=False)
        persisted = reopened.get(task.id)
        artifact, verified_manifest = resolve_artifact(task.id)
        rows = json.loads(artifact.read_text(encoding='utf-8'))
        assert persisted is not None and persisted.status == TaskStatus.COMPLETED
        assert persisted.result['artifact']['sha256'] == verified_manifest['sha256']
        assert rows == [{'姓名': '张三', '备注': '中文😀与多行内容'}]
