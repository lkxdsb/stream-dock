from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tasks.artifacts import publish_artifact, remove_task_workspace, resolve_artifact, seal_artifact, task_output_dir


def test_task_artifact_is_bound_by_manifest_and_rejects_replacement():
    with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'STREAMDOCK_ARTIFACT_ROOT': tmp}):
        task_id = 'a' * 32
        output = task_output_dir(task_id) / 'result.txt'
        output.write_text('原始内容 😀', encoding='utf-8')
        manifest = seal_artifact(task_id, output)

        resolved, loaded = resolve_artifact(task_id)
        assert resolved.read_text(encoding='utf-8') == '原始内容 😀'
        assert loaded['sha256'] == manifest['sha256']

        output.write_text('替换内容', encoding='utf-8')
        with pytest.raises(ValueError, match='替换或损坏'):
            resolve_artifact(task_id)


def test_task_artifact_rejects_symlink_and_cleanup_never_follows_it():
    with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'STREAMDOCK_ARTIFACT_ROOT': tmp}):
        root = Path(tmp)
        task_id = 'b' * 32
        output = task_output_dir(task_id) / 'result.txt'
        output.write_text('owned', encoding='utf-8')
        seal_artifact(task_id, output)
        outside = root / 'outside.txt'
        outside.write_text('keep', encoding='utf-8')
        output.unlink()
        output.symlink_to(outside)

        with pytest.raises(ValueError, match='符号链接'):
            resolve_artifact(task_id)
        remove_task_workspace(task_id)
        assert outside.read_text(encoding='utf-8') == 'keep'


def test_publish_reserves_same_name_without_cross_task_overwrite():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_a = root / 'a.txt'; source_a.write_text('A', encoding='utf-8')
        source_b = root / 'b.txt'; source_b.write_text('B', encoding='utf-8')
        destination = root / 'published'

        first = publish_artifact(source_a, destination, 'same.txt')
        second = publish_artifact(source_b, destination, 'same.txt')

        assert first != second
        assert first.read_text(encoding='utf-8') == 'A'
        assert second.read_text(encoding='utf-8') == 'B'
