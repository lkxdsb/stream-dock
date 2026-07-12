from __future__ import annotations

import bz2
import gzip
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path


def _ensure_safe_member(output_path: Path, member_name: str) -> Path:
    root = output_path.resolve()
    target = (output_path / member_name).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f'压缩包包含不安全路径，已拒绝解压：{member_name}') from exc
    return target


def _safe_extract_zip(input_path: Path, output_path: Path) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(input_path) as zf:
        for info in zf.infolist():
            target = _ensure_safe_member(output_path, info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RuntimeError(f'ZIP 包含符号链接，已拒绝解压：{info.filename}')
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open('wb') as dst:
                shutil.copyfileobj(src, dst)


def _safe_extract_tar(input_path: Path, output_path: Path, mode: str) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    with tarfile.open(input_path, mode) as tf:
        for member in tf.getmembers():
            _ensure_safe_member(output_path, member.name)
            if member.issym() or member.islnk():
                raise RuntimeError(f'TAR 包含链接文件，已拒绝解压：{member.name}')
        tf.extractall(output_path)


def _zip_to_folder(input_path: Path, output_path: Path) -> list[str]:
    _safe_extract_zip(input_path, output_path)
    return [f'ZIP 已解压到 {output_path}']


def _folder_to_zip(input_path: Path, output_path: Path) -> list[str]:
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in input_path.rglob('*'):
            if path.is_file():
                zf.write(path, path.relative_to(input_path))
    return ['文件夹已打包为 ZIP']


def _folder_to_targz(input_path: Path, output_path: Path) -> list[str]:
    with tarfile.open(output_path, 'w:gz') as tf:
        tf.add(input_path, arcname=input_path.name)
    return ['文件夹已打包为 TAR.GZ']


def _single_compressed_to_folder(input_path: Path, output_path: Path, opener, suffix: str) -> list[str]:
    output_path.mkdir(parents=True, exist_ok=True)
    name = input_path.name
    if name.endswith(suffix):
        name = name[:-len(suffix)]
    if not name:
        name = input_path.stem or 'extracted'
    target = output_path / name
    with opener(input_path, 'rb') as src, target.open('wb') as dst:
        dst.write(src.read())
    return [f'{suffix.upper().lstrip(".")} 已解压到 {target}']


def convert_archive(source: str, target: str, input_path: Path, output_path: Path) -> list[str]:
    if source == 'zip' and target == 'folder':
        return _zip_to_folder(input_path, output_path)
    if source == 'folder' and target == 'zip':
        return _folder_to_zip(input_path, output_path)
    if source == 'folder' and target == 'tar.gz':
        return _folder_to_targz(input_path, output_path)
    if source == 'tar' and target == 'folder':
        _safe_extract_tar(input_path, output_path, 'r')
        return [f'TAR 已解压到 {output_path}']
    if source == 'tar.gz' and target == 'folder':
        _safe_extract_tar(input_path, output_path, 'r:gz')
        return [f'TAR.GZ 已解压到 {output_path}']
    if source == 'gz' and target == 'folder':
        return _single_compressed_to_folder(input_path, output_path, gzip.open, '.gz')
    if source == 'bz2' and target == 'folder':
        return _single_compressed_to_folder(input_path, output_path, bz2.open, '.bz2')
    if source == 'zip' and target == 'tar':
        tmp = output_path.with_suffix('')
        logs = _zip_to_folder(input_path, tmp)
        with tarfile.open(output_path, 'w') as tf:
            tf.add(tmp, arcname=tmp.name)
        return logs + ['ZIP 已转换为 TAR']
    if source in {'tar', 'tar.gz'} and target == 'zip':
        mode = 'r:gz' if source == 'tar.gz' else 'r'
        tmp = output_path.with_suffix('')
        tmp.mkdir(parents=True, exist_ok=True)
        _safe_extract_tar(input_path, tmp, mode)
        return [f'{source.upper()} 已解压'] + _folder_to_zip(tmp, output_path)
    raise RuntimeError(f'暂不支持压缩包转换 {source} → {target}')
