# Batch Conversion and Media Task Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified local task center that supports batch file conversion for identical conversion routes and conservative multi-link media parsing queues.

**Architecture:** Keep the first version local and in-memory: introduce a small task domain module, expose task APIs from FastAPI, then connect the existing `/convert` and `/use` pages to the shared task model. Batch file conversion can run sequentially with one consistent route; media parsing should be a queue with default single-worker execution and platform-aware pacing hooks.

**Tech Stack:** FastAPI, Python dataclasses, existing `converters.pipeline.convert_file`, existing `douyin_fetch.py` subprocess flow, existing Jinja templates, vanilla JavaScript modules, focused `unittest` tests.

---

## Scope boundary

This plan intentionally avoids high-concurrency video downloading. File conversion batch mode may process multiple local files in sequence because the conversion route is deterministic. Video parsing supports multi-link import and queue tracking, but defaults to one active media task at a time to reduce platform throttling risk.

---

## File structure

### Backend

- Create: `tasks/__init__.py`
  - Package marker for shared task-center code.
- Create: `tasks/models.py`
  - Defines `TaskKind`, `TaskStatus`, `TaskItem`, and serialization helpers.
- Create: `tasks/store.py`
  - In-memory task store with create, update, list, get, and clear operations.
- Create: `tasks/media_queue.py`
  - Sequential media queue runner using the existing `douyin_fetch.py` subprocess command.
- Create: `converters/batch.py`
  - Batch conversion validation and sequential batch execution on a consistent `source -> target` route.
- Modify: `app.py`
  - Add task APIs, batch conversion APIs, and media queue APIs.

### Frontend

- Modify: `templates/convert.html`
  - Allow multiple file selection and add batch mode copy/status blocks.
- Modify: `static/js/convert-form.js`
  - Detect multi-file selection, probe consistent route, submit batch conversion, and render per-file result rows.
- Modify: `static/js/convert-result.js`
  - Support multiple result rows while preserving current single-file result behavior.
- Modify: `templates/use.html`
  - Add a multi-link textarea or import mode inside the existing online-use workspace.
- Modify: `static/js/use-form.js`
  - Parse multiple links, submit them to the queue API, and stop treating batch media parsing as one synchronous fetch.
- Modify: `static/js/use-result.js`
  - Render queued/running/completed/failed task states.
- Modify: `static/js/use-logs.js`
  - Support task-center logs and per-task summaries.
- Modify: `static/css/convert.css`, `static/css/use.css`, `static/css/components.css`
  - Add light task-list styles consistent with the current card design.

### Tests

- Create: `tests/test_tasks.py`
  - Covers in-memory store lifecycle and serialization.
- Create: `tests/test_batch_conversion.py`
  - Covers consistent-route validation and mixed-route rejection.
- Modify: `tests/test_app.py`
  - Covers new API endpoints at request/response level.

---

## Task 1: Add shared task models and in-memory store

**Files:**
- Create: `tasks/__init__.py`
- Create: `tasks/models.py`
- Create: `tasks/store.py`
- Create: `tests/test_tasks.py`

- [ ] **Step 1: Create failing task store tests**

Add `tests/test_tasks.py`:

```python
from tasks.models import TaskKind, TaskStatus
from tasks.store import TaskStore


def test_task_store_creates_and_lists_tasks():
    store = TaskStore()
    task = store.create(
        kind=TaskKind.CONVERT,
        title='a.csv → XLSX',
        payload={'source': 'csv', 'target': 'xlsx'},
    )

    assert task.id
    assert task.kind == TaskKind.CONVERT
    assert task.status == TaskStatus.PENDING
    assert store.list()[0].id == task.id


def test_task_store_updates_task_status_and_logs():
    store = TaskStore()
    task = store.create(kind=TaskKind.MEDIA, title='抖音链接', payload={'link': 'https://v.douyin.com/example/'})

    updated = store.update(
        task.id,
        status=TaskStatus.RUNNING,
        logs=['开始解析'],
        result={'platform': 'douyin'},
    )

    assert updated is not None
    assert updated.status == TaskStatus.RUNNING
    assert updated.logs == ['开始解析']
    assert updated.result == {'platform': 'douyin'}


def test_task_store_returns_none_for_unknown_task():
    store = TaskStore()
    assert store.get('missing') is None
    assert store.update('missing', status=TaskStatus.FAILED) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m unittest tests.test_tasks -v
```

Expected: FAIL because `tasks.models` and `tasks.store` do not exist.

- [ ] **Step 3: Implement task models**

Create `tasks/__init__.py`:

```python
"""Shared local task center package for StreamDock."""
```

Create `tasks/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskKind(str, Enum):
    CONVERT = 'convert'
    MEDIA = 'media'


class TaskStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    SKIPPED = 'skipped'


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskItem:
    id: str
    kind: TaskKind
    title: str
    payload: dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'kind': self.kind.value,
            'title': self.title,
            'payload': self.payload,
            'status': self.status.value,
            'logs': self.logs,
            'result': self.result,
            'error': self.error,
            'createdAt': self.created_at,
            'updatedAt': self.updated_at,
        }
```

- [ ] **Step 4: Implement in-memory task store**

Create `tasks/store.py`:

```python
from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Any
from uuid import uuid4

from .models import TaskItem, TaskKind, TaskStatus, utc_now_iso


class TaskStore:
    def __init__(self, max_items: int = 300):
        self.max_items = max_items
        self._items: OrderedDict[str, TaskItem] = OrderedDict()
        self._lock = Lock()

    def create(self, *, kind: TaskKind, title: str, payload: dict[str, Any]) -> TaskItem:
        with self._lock:
            task = TaskItem(id=uuid4().hex, kind=kind, title=title, payload=payload)
            self._items[task.id] = task
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
            return task

    def get(self, task_id: str) -> TaskItem | None:
        with self._lock:
            return self._items.get(task_id)

    def list(self, *, kind: TaskKind | None = None) -> list[TaskItem]:
        with self._lock:
            items = list(self._items.values())
        if kind is not None:
            items = [item for item in items if item.kind == kind]
        return list(reversed(items))

    def update(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        logs: list[str] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> TaskItem | None:
        with self._lock:
            task = self._items.get(task_id)
            if task is None:
                return None
            if status is not None:
                task.status = status
            if logs is not None:
                task.logs = logs
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            task.updated_at = utc_now_iso()
            return task

    def clear(self, *, kind: TaskKind | None = None) -> int:
        with self._lock:
            if kind is None:
                count = len(self._items)
                self._items.clear()
                return count
            ids = [task_id for task_id, task in self._items.items() if task.kind == kind]
            for task_id in ids:
                self._items.pop(task_id, None)
            return len(ids)
```

- [ ] **Step 5: Run task tests**

Run:

```bash
python -m unittest tests.test_tasks -v
```

Expected: PASS.

---

## Task 2: Add batch conversion backend with consistent-route validation

**Files:**
- Create: `converters/batch.py`
- Create: `tests/test_batch_conversion.py`
- Modify: `app.py`

- [ ] **Step 1: Create failing batch validation tests**

Add `tests/test_batch_conversion.py`:

```python
from converters.batch import BatchFileSpec, validate_batch_route


def test_validate_batch_route_accepts_same_source_and_target():
    files = [
        BatchFileSpec(filename='a.csv', source='csv'),
        BatchFileSpec(filename='b.csv', source='csv'),
    ]

    result = validate_batch_route(files, target='xlsx')

    assert result.success is True
    assert result.source == 'csv'
    assert result.target == 'xlsx'
    assert result.error is None


def test_validate_batch_route_rejects_mixed_sources():
    files = [
        BatchFileSpec(filename='a.csv', source='csv'),
        BatchFileSpec(filename='b.tsv', source='tsv'),
    ]

    result = validate_batch_route(files, target='xlsx')

    assert result.success is False
    assert result.error == '批量转换要求输入格式一致：当前包含 CSV、TSV'


def test_validate_batch_route_rejects_missing_capability():
    files = [BatchFileSpec(filename='a.csv', source='csv')]

    result = validate_batch_route(files, target='docx')

    assert result.success is False
    assert result.error == '暂不支持 CSV → DOCX 批量转换路径'
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m unittest tests.test_batch_conversion -v
```

Expected: FAIL because `converters.batch` does not exist.

- [ ] **Step 3: Implement batch validation module**

Create `converters/batch.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import ConversionResult
from .pipeline import convert_file
from .registry import find_capability, normalize_format


@dataclass(frozen=True)
class BatchFileSpec:
    filename: str
    source: str


@dataclass(frozen=True)
class BatchRouteValidation:
    success: bool
    source: str | None = None
    target: str | None = None
    error: str | None = None


def validate_batch_route(files: list[BatchFileSpec], target: str) -> BatchRouteValidation:
    if not files:
        return BatchRouteValidation(False, error='请至少选择一个文件')

    normalized_sources = sorted({normalize_format(item.source) for item in files})
    normalized_target = normalize_format(target)
    if len(normalized_sources) != 1:
        label = '、'.join(item.upper() for item in normalized_sources)
        return BatchRouteValidation(False, error=f'批量转换要求输入格式一致：当前包含 {label}')

    source = normalized_sources[0]
    capability = find_capability(source, normalized_target)
    if capability is None:
        return BatchRouteValidation(False, source=source, target=normalized_target, error=f'暂不支持 {source.upper()} → {normalized_target.upper()} 批量转换路径')

    return BatchRouteValidation(True, source=source, target=normalized_target)


def convert_batch_files(files: list[tuple[Path, str, str]], target: str, output_dir: Path) -> list[ConversionResult]:
    specs = [BatchFileSpec(filename=name, source=source) for _, name, source in files]
    validation = validate_batch_route(specs, target)
    if not validation.success or validation.source is None or validation.target is None:
        return [ConversionResult(False, error=validation.error or '批量转换校验失败')]

    results: list[ConversionResult] = []
    for input_path, filename, source in files:
        results.append(convert_file(input_path, filename, source, validation.target, output_dir))
    return results
```

- [ ] **Step 4: Run batch tests**

Run:

```bash
python -m unittest tests.test_batch_conversion -v
```

Expected: PASS.

- [ ] **Step 5: Add `/api/convert/batch/probe` endpoint test**

Modify `tests/test_app.py` with:

```python
def test_convert_batch_probe_requires_consistent_input_format(client):
    files = [
        ('files', ('a.csv', b'a,b\n1,2\n', 'text/csv')),
        ('files', ('b.tsv', b'a\tb\n1\t2\n', 'text/tab-separated-values')),
    ]

    response = client.post('/api/convert/batch/probe', files=files)
    data = response.json()

    assert response.status_code == 200
    assert data['success'] is True
    assert data['consistentSource'] is False
    assert data['sources'] == ['csv', 'tsv']
```

- [ ] **Step 6: Implement `/api/convert/batch/probe`**

Modify `app.py` imports:

```python
from converters.batch import BatchFileSpec, validate_batch_route
```

Add endpoint near existing convert endpoints:

```python
@app.post('/api/convert/batch/probe')
async def convert_batch_probe(files: list[UploadFile] = File(...)):
    specs: list[BatchFileSpec] = []
    for file in files:
        filename = file.filename or 'input'
        specs.append(BatchFileSpec(filename=filename, source=infer_input_format(filename)))
        await file.close()

    sources = sorted({item.source for item in specs})
    options = [cap.to_dict() for cap in targets_for_source(sources[0])] if len(sources) == 1 else []
    return JSONResponse({
        'success': True,
        'count': len(specs),
        'sources': sources,
        'consistentSource': len(sources) == 1,
        'source': sources[0] if len(sources) == 1 else None,
        'options': options,
    })
```

- [ ] **Step 7: Run app test for probe**

Run:

```bash
python -m unittest tests.test_app -v
```

Expected: PASS for existing tests and the new batch probe test.

---

## Task 3: Add batch conversion run endpoint and task records

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Add API test for successful same-route batch conversion**

Modify `tests/test_app.py` with:

```python
def test_convert_batch_run_converts_same_route_files(client, tmp_path):
    files = [
        ('files', ('a.csv', b'a,b\n1,2\n', 'text/csv')),
        ('files', ('b.csv', b'a,b\n3,4\n', 'text/csv')),
    ]
    data = {
        'inputType': 'csv',
        'outputType': 'xlsx',
        'outputPath': str(tmp_path),
    }

    response = client.post('/api/convert/batch/run', data=data, files=files)
    body = response.json()

    assert response.status_code == 200
    assert body['success'] is True
    assert body['count'] == 2
    assert len(body['results']) == 2
    assert all(item['success'] for item in body['results'])
    assert (tmp_path / 'a_converted.xlsx').exists()
    assert (tmp_path / 'b_converted.xlsx').exists()
```

- [ ] **Step 2: Run test to verify endpoint is missing**

Run:

```bash
python -m unittest tests.test_app -v
```

Expected: FAIL with 404 for `/api/convert/batch/run`.

- [ ] **Step 3: Implement `/api/convert/batch/run`**

Modify `app.py` imports:

```python
import tempfile
from tasks.models import TaskKind, TaskStatus
from tasks.store import TaskStore
from converters.batch import BatchFileSpec, convert_batch_files, validate_batch_route
```

Create global store near app initialization:

```python
task_store = TaskStore()
```

Add endpoint:

```python
@app.post('/api/convert/batch/run')
async def convert_batch_run(
    files: list[UploadFile] = File(...),
    outputType: str = Form(...),
    outputPath: str = Form(...),
    inputType: str | None = Form(None),
):
    specs = [BatchFileSpec(filename=file.filename or 'input', source=inputType or infer_input_format(file.filename or 'input')) for file in files]
    validation = validate_batch_route(specs, outputType)
    if not validation.success:
        for file in files:
            await file.close()
        return JSONResponse({'success': False, 'error': validation.error, 'results': []})

    batch_task = task_store.create(
        kind=TaskKind.CONVERT,
        title=f'{len(files)} 个 {validation.source.upper()} 文件 → {validation.target.upper()}',
        payload={'count': len(files), 'source': validation.source, 'target': validation.target, 'outputPath': outputPath},
    )
    task_store.update(batch_task.id, status=TaskStatus.RUNNING, logs=['批量转换开始'])

    with tempfile.TemporaryDirectory(prefix='streamdock_convert_batch_') as tmp_dir:
        prepared: list[tuple[Path, str, str]] = []
        for file in files:
            filename = file.filename or 'input'
            source = inputType or infer_input_format(filename)
            data = await file.read()
            await file.close()
            input_path = Path(tmp_dir) / Path(filename).name
            input_path.write_bytes(data)
            prepared.append((input_path, filename, source))

        results = convert_batch_files(prepared, outputType, Path(outputPath).expanduser())

    serialized = [result.to_dict() for result in results]
    success = all(result.success for result in results)
    logs = ['批量转换完成' if success else '批量转换存在失败项']
    task_store.update(
        batch_task.id,
        status=TaskStatus.COMPLETED if success else TaskStatus.FAILED,
        logs=logs,
        result={'results': serialized},
        error=None if success else '部分文件转换失败',
    )
    return JSONResponse({'success': success, 'taskId': batch_task.id, 'count': len(results), 'results': serialized})
```

- [ ] **Step 4: Run endpoint tests**

Run:

```bash
python -m unittest tests.test_app -v
```

Expected: PASS.

---

## Task 4: Add shared task list APIs

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Add task list API test**

Modify `tests/test_app.py` with:

```python
def test_task_list_endpoint_returns_task_array(client):
    response = client.get('/api/tasks')
    body = response.json()

    assert response.status_code == 200
    assert body['success'] is True
    assert isinstance(body['tasks'], list)
```

- [ ] **Step 2: Implement task list endpoints**

Add to `app.py`:

```python
@app.get('/api/tasks')
def list_tasks(kind: str | None = None):
    selected_kind = None
    if kind in {'convert', 'media'}:
        selected_kind = TaskKind(kind)
    return JSONResponse({'success': True, 'tasks': [task.to_dict() for task in task_store.list(kind=selected_kind)]})


@app.get('/api/tasks/{task_id}')
def get_task(task_id: str):
    task = task_store.get(task_id)
    if task is None:
        return JSONResponse({'success': False, 'error': '任务不存在'}, status_code=404)
    return JSONResponse({'success': True, 'task': task.to_dict()})
```

- [ ] **Step 3: Run app tests**

Run:

```bash
python -m unittest tests.test_app -v
```

Expected: PASS.

---

## Task 5: Add conservative media queue backend

**Files:**
- Create: `tasks/media_queue.py`
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Add media queue submission API test**

Modify `tests/test_app.py` with:

```python
def test_media_queue_submit_creates_pending_tasks(client):
    payload = {
        'links': ['https://v.douyin.com/example1/', 'https://www.bilibili.com/video/BV1xxxxxxx/'],
        'outputPath': '/tmp/streamdock-test',
        'outputType': 'mp4',
    }

    response = client.post('/api/fetch/batch', json=payload)
    body = response.json()

    assert response.status_code == 200
    assert body['success'] is True
    assert body['count'] == 2
    assert len(body['tasks']) == 2
    assert all(item['status'] == 'pending' for item in body['tasks'])
```

- [ ] **Step 2: Implement sequential media queue helper**

Create `tasks/media_queue.py`:

```python
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .models import TaskKind, TaskStatus
from .store import TaskStore

CommandBuilder = Callable[[dict[str, str]], list[str]]
EnvBuilder = Callable[[dict[str, str]], dict[str, str]]
OutputParser = Callable[[str], dict[str, str | None]]


class MediaQueue:
    def __init__(self, *, store: TaskStore, command_builder: CommandBuilder, env_builder: EnvBuilder, output_parser: OutputParser, cwd: Path):
        self.store = store
        self.command_builder = command_builder
        self.env_builder = env_builder
        self.output_parser = output_parser
        self.cwd = cwd
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._pending_ids: list[str] = []

    def submit(self, payloads: list[dict[str, str]]) -> list[dict[str, object]]:
        tasks = []
        with self._lock:
            for payload in payloads:
                title = payload['link'][:64]
                task = self.store.create(kind=TaskKind.MEDIA, title=title, payload=payload)
                self._pending_ids.append(task.id)
                tasks.append(task.to_dict())
            self._ensure_worker_locked()
        return tasks

    def _ensure_worker_locked(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run_loop, name='streamdock-media-queue', daemon=True)
        self._worker.start()

    def _pop_next(self) -> str | None:
        with self._lock:
            if not self._pending_ids:
                return None
            return self._pending_ids.pop(0)

    def _run_loop(self) -> None:
        while True:
            task_id = self._pop_next()
            if task_id is None:
                return
            task = self.store.get(task_id)
            if task is None:
                continue
            self.store.update(task_id, status=TaskStatus.RUNNING, logs=['排队完成，开始解析'])
            payload = {key: str(value) for key, value in task.payload.items()}
            try:
                completed = subprocess.run(
                    self.command_builder(payload),
                    cwd=str(self.cwd),
                    text=True,
                    capture_output=True,
                    env=self.env_builder(payload),
                    timeout=180,
                )
                stdout = completed.stdout.strip()
                stderr = completed.stderr.strip()
                parsed = self.output_parser(stdout)
                logs = [line for line in [stdout, stderr] if line]
                if completed.returncode == 0:
                    self.store.update(task_id, status=TaskStatus.COMPLETED, logs=logs, result=parsed)
                else:
                    self.store.update(task_id, status=TaskStatus.FAILED, logs=logs, error=stderr or stdout or 'Unknown execution error')
            except subprocess.TimeoutExpired:
                self.store.update(task_id, status=TaskStatus.FAILED, logs=['解析超时'], error='Execution timeout while fetching media')
            time.sleep(2.0)
```

- [ ] **Step 3: Wire media queue in `app.py`**

Add imports:

```python
from tasks.media_queue import MediaQueue
```

Add helpers near existing `fetch` function:

```python
def build_fetch_command_from_payload(payload: dict[str, str]) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        '--link', payload['link'],
        '--outputPath', payload['outputPath'],
        '--outputType', payload['outputType'],
    ]
    if payload.get('videoQuality'):
        command.extend(['--videoQuality', payload['videoQuality']])
    return command


def build_fetch_env_from_payload(payload: dict[str, str]) -> dict[str, str]:
    return build_subprocess_env(raw_cookie=payload.get('bilibiliCookie'), cookie_file=payload.get('bilibiliCookieFile'))


def parse_fetch_stdout(stdout: str) -> dict[str, str | None]:
    return {'outputPath': extract_output_file(stdout), 'platform': extract_platform(stdout)}
```

After `task_store = TaskStore()` add:

```python
media_queue = MediaQueue(
    store=task_store,
    command_builder=build_fetch_command_from_payload,
    env_builder=build_fetch_env_from_payload,
    output_parser=parse_fetch_stdout,
    cwd=BASE_DIR,
)
```

If ordering makes `BASE_DIR` unavailable, place this initialization after constants and helper definitions.

Add request model:

```python
class BatchFetchRequest(BaseModel):
    links: list[str] = Field(min_length=1)
    outputPath: str = Field(min_length=1)
    outputType: str = Field(pattern=r'^(m4a|mp3|mp4|wav|flac|aac|ogg|opus|mkv|mov|webm)$')
    videoQuality: str | None = None
    bilibiliCookie: str | None = None
    bilibiliCookieFile: str | None = None
```

Add endpoint:

```python
@app.post('/api/fetch/batch')
def fetch_batch(payload: BatchFetchRequest):
    items = []
    for link in payload.links:
        normalized = link.strip()
        if not normalized:
            continue
        items.append({
            'link': normalized,
            'outputPath': payload.outputPath,
            'outputType': payload.outputType,
            'videoQuality': payload.videoQuality or '',
            'bilibiliCookie': payload.bilibiliCookie or '',
            'bilibiliCookieFile': payload.bilibiliCookieFile or '',
        })
    if not items:
        return JSONResponse({'success': False, 'error': '请至少输入一个有效链接', 'tasks': []})
    tasks = media_queue.submit(items)
    return JSONResponse({'success': True, 'count': len(tasks), 'tasks': tasks})
```

- [ ] **Step 4: Run app tests**

Run:

```bash
python -m unittest tests.test_app -v
```

Expected: PASS.

---

## Task 6: Update file conversion UI for batch mode

**Files:**
- Modify: `templates/convert.html`
- Modify: `static/js/convert-form.js`
- Modify: `static/js/convert-result.js`
- Modify: `static/css/convert.css`

- [ ] **Step 1: Allow multiple files in the upload input**

Modify `templates/convert.html` file input:

```html
<input class="convert-file-input" id="convertFileInput" type="file" multiple />
```

- [ ] **Step 2: Add selected files state in `static/js/convert-form.js`**

Replace single file state:

```javascript
let selectedFile = null;
```

with:

```javascript
let selectedFiles = [];
```

- [ ] **Step 3: Add batch probe function**

Add to `static/js/convert-form.js`:

```javascript
async function probeFiles(files) {
  selectedFiles = Array.from(files || []);
  if (selectedFiles.length === 0) return;

  if (selectedFiles.length === 1) {
    await probeFile(selectedFiles[0]);
    return;
  }

  fileTitle.textContent = `${selectedFiles.length} 个文件已选择`;
  fileMeta.textContent = '正在识别批量转换路径...';
  outputType.innerHTML = '<option value="">识别中...</option>';
  setResultWaiting();
  setLog(['识别批量文件格式...', ...selectedFiles.map((file) => file.name)]);

  const form = new FormData();
  selectedFiles.forEach((file) => form.append('files', file));
  const response = await fetch('/api/convert/batch/probe', { method: 'POST', body: form });
  const data = await response.json();

  if (!data.consistentSource) {
    currentSource = '';
    currentOptions = [];
    inputType.value = '混合格式';
    outputType.innerHTML = '<option value="">批量转换要求输入格式一致</option>';
    fileMeta.textContent = `当前包含：${(data.sources || []).map((item) => item.toUpperCase()).join('、')}`;
    setLog(['批量校验失败', '批量转换要求输入格式一致']);
    return;
  }

  currentSource = data.source || '';
  currentOptions = data.options || [];
  inputType.value = currentSource.toUpperCase();
  fileMeta.textContent = `识别为 ${currentSource.toUpperCase()}，${selectedFiles.length} 个文件，找到 ${currentOptions.length} 条可用路径`;
  renderOutputOptions();
  setLog(['批量格式识别完成', `输入格式：${currentSource.toUpperCase()}`, `文件数量：${selectedFiles.length}`]);
}
```

- [ ] **Step 4: Update file input and drop handlers**

Replace file input handler with:

```javascript
fileInput?.addEventListener('change', () => {
  const files = Array.from(fileInput.files || []);
  if (files.length) probeFiles(files).catch((error) => setError(error.message));
});
```

Replace drop handler file extraction with:

```javascript
const files = Array.from(event.dataTransfer?.files || []);
if (files.length) probeFiles(files).catch((error) => setError(error.message));
```

- [ ] **Step 5: Update start conversion logic**

Inside start click handler, replace `selectedFile` checks and form creation with:

```javascript
if (!selectedFiles.length) {
  setError('请先选择需要转换的文件');
  return;
}
```

Then branch before current `/api/convert/run` call:

```javascript
if (selectedFiles.length > 1) {
  const form = new FormData();
  selectedFiles.forEach((file) => form.append('files', file));
  form.append('inputType', currentSource);
  form.append('outputType', outputType.value);
  form.append('outputPath', outputPath.value || '~/Downloads/StreamDock');
  setLog(['开始批量转换...', `${selectedFiles.length} 个 ${currentSource.toUpperCase()} 文件 → ${outputType.value.toUpperCase()}`]);
  const response = await fetch('/api/convert/batch/run', { method: 'POST', body: form });
  const data = await response.json();
  const resultLines = (data.results || []).map((item) => item.success ? `成功：${item.outputPath}` : `失败：${item.error}`);
  setLog([...(data.logs || []), ...resultLines]);
  if (data.success) window.StreamDockConvertResult?.batchSuccess(data.results || []);
  else setError(data.error || '批量转换存在失败项');
  return;
}

const selectedFile = selectedFiles[0];
```

- [ ] **Step 6: Add batch result renderer**

Modify `static/js/convert-result.js` and expose:

```javascript
function batchSuccess(results) {
  resultBox.innerHTML = `
    <strong>批量转换完成</strong>
    <div class="convert-batch-results">
      ${results.map((item) => `
        <span class="convert-batch-row ${item.success ? 'success' : 'failed'}">
          ${item.success ? '完成' : '失败'} · ${item.outputPath || item.error || ''}
        </span>
      `).join('')}
    </div>
  `;
}

window.StreamDockConvertResult = {
  waiting,
  success,
  error,
  batchSuccess,
};
```

- [ ] **Step 7: Add light batch result styles**

Add to `static/css/convert.css`:

```css
.convert-batch-results {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.convert-batch-row {
  border: 1px solid rgba(70,63,56,.10);
  border-radius: 12px;
  padding: 9px 11px;
  background: rgba(255,255,255,.40);
  color: #665f58;
  font-size: 12px;
  line-height: 1.5;
}

.convert-batch-row.success { color: #328755; }
.convert-batch-row.failed { color: #b4533f; }
```

---

## Task 7: Update media parser UI for multi-link queue

**Files:**
- Modify: `templates/use.html`
- Modify: `static/js/use-form.js`
- Modify: `static/js/use-result.js`
- Modify: `static/css/use.css`

- [ ] **Step 1: Add multi-link hint and textarea mode**

In `templates/use.html`, keep the existing single-link input but update helper copy to say:

```html
<span class="use-field-hint">可粘贴单条链接；多条链接请每行一条，系统会按队列逐条解析。</span>
```

If current input is a single-line `<input id="link">`, replace it with:

```html
<textarea id="link" name="link" rows="4" placeholder="粘贴视频链接；多条链接请每行一条"></textarea>
```

- [ ] **Step 2: Add link parser in `static/js/use-form.js`**

Add:

```javascript
function parseLinks(value) {
  return String(value || '')
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean);
}
```

- [ ] **Step 3: Route multi-link submission to queue API**

Inside submit handler, after building payload, add:

```javascript
const links = parseLinks(payload.link);
if (links.length > 1) {
  submitButton.disabled = true;
  submitButton.textContent = '加入队列...';
  logs?.renderLogs(['正在创建多链接解析队列...', `链接数量：${links.length}`]);
  try {
    const response = await fetch('/api/fetch/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...payload, links }),
    });
    const data = await response.json();
    if (!response.ok || !data.success) {
      result?.setStatus('error', data.error || '队列创建失败');
      result?.showResult({ error: data.error || '队列创建失败' });
      logs?.renderLogs([data.error || '队列创建失败']);
      return;
    }
    result?.setStatus('running', `${data.count} 条链接已加入队列`);
    result?.showTaskQueue?.(data.tasks || []);
    logs?.renderLogs(['队列创建完成', '视频解析将按低并发策略逐条执行']);
    ui?.showToast('多链接任务已加入队列');
    return;
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = '开始解析';
    submitButton.classList.remove('loading');
  }
}
```

- [ ] **Step 4: Add task queue renderer**

Modify `static/js/use-result.js` and expose:

```javascript
function showTaskQueue(tasks) {
  resultBox.innerHTML = `
    <strong>多链接任务队列</strong>
    <div class="use-task-queue">
      ${tasks.map((task) => `
        <span class="use-task-row" data-status="${task.status}">
          <b>${task.status}</b>
          <em>${task.title}</em>
        </span>
      `).join('')}
    </div>
  `;
}

window.StreamDockResult = {
  setStatus,
  showResult,
  showTaskQueue,
};
```

- [ ] **Step 5: Add light queue styles**

Add to `static/css/use.css`:

```css
.use-task-queue {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.use-task-row {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 10px;
  align-items: center;
  border: 1px solid rgba(70,63,56,.10);
  border-radius: 12px;
  padding: 9px 11px;
  background: rgba(255,255,255,.38);
  color: #665f58;
  font-size: 12px;
}

.use-task-row b {
  color: #2d5fa7;
  font-style: normal;
}

.use-task-row em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-style: normal;
}
```

---

## Task 8: Add task-center polling for queued media tasks

**Files:**
- Create: `static/js/task-center.js`
- Modify: `templates/base.html` or page templates that need task polling
- Modify: `static/js/use-result.js`

- [ ] **Step 1: Create task polling module**

Create `static/js/task-center.js`:

```javascript
(function () {
  let timer = null;

  async function fetchTasks(kind) {
    const suffix = kind ? `?kind=${encodeURIComponent(kind)}` : '';
    const response = await fetch(`/api/tasks${suffix}`);
    return response.json();
  }

  function start({ kind = '', interval = 2500, onUpdate } = {}) {
    stop();
    async function tick() {
      try {
        const data = await fetchTasks(kind);
        if (data.success && typeof onUpdate === 'function') onUpdate(data.tasks || []);
      } catch (_) {
        // Keep polling quiet; visible logs are handled by page-specific modules.
      }
      timer = window.setTimeout(tick, interval);
    }
    tick();
  }

  function stop() {
    if (timer) window.clearTimeout(timer);
    timer = null;
  }

  window.StreamDockTaskCenter = { start, stop, fetchTasks };
})();
```

- [ ] **Step 2: Include script on `/use` and `/convert` pages**

Add before page-specific form scripts:

```html
<script src="{{ url_for('static', path='/js/task-center.js') }}?v=20260708-task1"></script>
```

- [ ] **Step 3: Update use page to refresh queue statuses**

In `static/js/use-form.js`, after successful multi-link queue creation:

```javascript
window.StreamDockTaskCenter?.start({
  kind: 'media',
  onUpdate: (tasks) => result?.showTaskQueue?.(tasks.slice(0, 8)),
});
```

- [ ] **Step 4: Update convert page to refresh conversion task statuses**

In `static/js/convert-form.js`, after successful batch conversion:

```javascript
window.StreamDockTaskCenter?.start({
  kind: 'convert',
  onUpdate: (tasks) => window.StreamDockConvertResult?.tasks?.(tasks.slice(0, 8)),
});
```

If `StreamDockConvertResult.tasks` does not exist, add it in `static/js/convert-result.js` using the same row style as `batchSuccess`.

---

## Task 9: Manual validation checklist

**Files:**
- No new files unless issues are found.

- [ ] **Step 1: Validate batch file conversion happy path**

Run service if needed:

```bash
python app.py
```

Open:

```text
http://127.0.0.1:8002/convert
```

Manual steps:

1. Select two CSV files.
2. Confirm UI says the input format is CSV and shows batch count.
3. Choose XLSX.
4. Choose output directory.
5. Click start.
6. Confirm both files appear in conversion result list.

Expected: output directory contains two `_converted.xlsx` files.

- [ ] **Step 2: Validate mixed-file rejection**

Manual steps:

1. Select one CSV and one PNG.
2. Confirm UI says batch conversion requires consistent input format.
3. Confirm start button does not silently run a wrong route.

Expected: no conversion starts.

- [ ] **Step 3: Validate multi-link media queue**

Open:

```text
http://127.0.0.1:8002/use
```

Manual steps:

1. Paste two video links, one per line.
2. Click start.
3. Confirm task queue shows two pending/running rows.
4. Confirm tasks update over time through `/api/tasks?kind=media` polling.

Expected: only one task runs at a time, and logs make clear that queue mode is conservative.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python -m unittest tests.test_tasks tests.test_batch_conversion tests.test_app -v
```

Expected: PASS.

---

## Implementation notes

- Do not make video parsing concurrent in v1. The queue runner intentionally sleeps between jobs and processes one task at a time.
- Keep task storage in memory for now. Persistence can be added later with SQLite after the UI and workflow are stable.
- Batch file conversion only supports one source format and one target format per batch.
- Vendor-recommended conversion paths should still not run locally.
- If frontend changes require cache busting, update the query version on relevant CSS/JS includes.

---

## Self-review

- Spec coverage: The plan covers batch file conversion, conservative multi-link video parsing, and a unified task center.
- Placeholder scan: No incomplete placeholder markers are used.
- Type consistency: `TaskKind`, `TaskStatus`, `TaskStore`, `BatchFileSpec`, and endpoint names are consistent across tasks.
- Scope check: The plan keeps v1 local and avoids persistent task storage or high-concurrency video downloading.
