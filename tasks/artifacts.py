from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def artifact_root() -> Path:
    configured = os.getenv('STREAMDOCK_ARTIFACT_ROOT', '').strip()
    if configured:
        return Path(configured).expanduser()
    if os.getenv('STREAMDOCK_TASK_STORAGE_PATH') == '':
        return Path(tempfile.gettempdir()) / 'streamdock-artifacts-disposable'
    return Path.home() / '.streamdock' / 'artifacts'


def task_workspace(task_id: str) -> Path:
    if not task_id or any(char not in '0123456789abcdef' for char in task_id.lower()):
        raise ValueError('无效的任务 ID')
    return artifact_root() / task_id


def task_input_dir(task_id: str) -> Path:
    path = task_workspace(task_id) / 'input'
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_output_dir(task_id: str) -> Path:
    path = task_workspace(task_id) / 'output'
    path.mkdir(parents=True, exist_ok=True)
    return path


def retain_input(task_id: str, filename: str, source: Path, *, index: int = 0) -> Path:
    safe_name = Path(filename).name or 'input'
    destination = task_input_dir(task_id) / f'{index:04d}_{safe_name}'
    shutil.copyfile(source, destination)
    return destination


def _file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _artifact_identity(path: Path) -> tuple[int, str, list[dict[str, Any]]]:
    if path.is_symlink():
        raise ValueError('任务产物不能是符号链接')
    if path.is_file():
        size, digest = _file_digest(path)
        return size, digest, []
    if not path.is_dir():
        raise ValueError('任务产物不存在')
    digest = hashlib.sha256()
    total = 0
    members: list[dict[str, Any]] = []
    for candidate in sorted(path.rglob('*'), key=lambda item: item.as_posix()):
        if candidate.is_symlink():
            raise ValueError('任务产物目录不能包含符号链接')
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(path).as_posix()
        size, file_hash = _file_digest(candidate)
        total += size
        members.append({'path': relative, 'size': size, 'sha256': file_hash})
        digest.update(relative.encode('utf-8'))
        digest.update(b'\0')
        digest.update(file_hash.encode('ascii'))
        digest.update(b'\0')
    return total, digest.hexdigest(), members


def seal_artifact(task_id: str, output: Path) -> dict[str, Any]:
    workspace = task_workspace(task_id).resolve()
    resolved = output.resolve()
    try:
        relative = resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError('任务产物不在任务工作区内') from exc
    size, digest, members = _artifact_identity(resolved)
    manifest = {
        'version': 1,
        'taskId': task_id,
        'path': relative.as_posix(),
        'name': resolved.name,
        'kind': 'file' if resolved.is_file() else 'directory',
        'size': size,
        'sha256': digest,
        'members': members,
    }
    manifest_path = task_workspace(task_id) / 'manifest.json'
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(manifest_path)
    return manifest


def artifact_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in manifest.items()
        if key != 'members'
    } | {'memberCount': len(manifest.get('members') or [])}


def resolve_artifact(task_id: str, *, verify: bool = True) -> tuple[Path, dict[str, Any]]:
    workspace = task_workspace(task_id)
    if workspace.is_symlink() or not workspace.is_dir():
        raise FileNotFoundError('任务产物工作区不存在')
    manifest_path = workspace / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise FileNotFoundError('任务产物清单不存在')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('taskId') != task_id:
        raise ValueError('任务产物清单与任务不匹配')
    relative = Path(str(manifest.get('path') or ''))
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('任务产物清单路径非法')
    output = workspace / relative
    current = workspace
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('任务产物路径包含符号链接')
    if not output.exists():
        raise FileNotFoundError('任务产物已不存在')
    if verify:
        size, digest, _ = _artifact_identity(output)
        if size != manifest.get('size') or digest != manifest.get('sha256'):
            raise ValueError('任务产物内容已被替换或损坏')
    return output, manifest


def remove_task_workspace(task_id: str) -> None:
    workspace = task_workspace(task_id)
    if workspace.is_symlink():
        workspace.unlink(missing_ok=True)
        return
    if workspace.is_dir():
        shutil.rmtree(workspace)


def publish_artifact(source: Path, output_dir: Path, filename: str, *, collision_strategy: str = 'append') -> Path:
    """Publish a task artifact while atomically reserving non-overwrite names."""
    from deployment_security import enforce_server_output_root

    output_dir = enforce_server_output_root(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / filename
    candidate = base
    index = 2
    overwrite = collision_strategy == 'overwrite'
    if collision_strategy == 'skip' and candidate.exists():
        raise FileExistsError(f'输出文件已存在，已按设置跳过：{candidate.name}')
    if not overwrite:
        while True:
            try:
                if source.is_dir():
                    candidate.mkdir()
                else:
                    descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.close(descriptor)
                break
            except FileExistsError:
                candidate = output_dir / f'{base.stem}_{index}{base.suffix}'
                index += 1
    if source.is_dir():
        if overwrite and candidate.exists():
            if candidate.is_symlink():
                raise ValueError('拒绝覆盖符号链接输出')
            shutil.rmtree(candidate) if candidate.is_dir() else candidate.unlink()
            candidate.mkdir()
        shutil.copytree(source, candidate, dirs_exist_ok=True)
        return candidate
    if overwrite and candidate.is_symlink():
        raise ValueError('拒绝覆盖符号链接输出')
    temporary = Path(tempfile.mkstemp(prefix=f'.{candidate.name}.', suffix='.partial', dir=output_dir)[1])
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, candidate)
    finally:
        temporary.unlink(missing_ok=True)
    return candidate
