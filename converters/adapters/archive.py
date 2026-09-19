from __future__ import annotations

import bz2
from datetime import datetime
import gzip
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

from runtime_checks import augmented_path, resolve_tool_path


MAX_ARCHIVE_MEMBERS = int(os.getenv('STREAMDOCK_MAX_ARCHIVE_MEMBERS', '10000'))
MAX_ARCHIVE_EXTRACTED_BYTES = int(os.getenv('STREAMDOCK_MAX_ARCHIVE_EXTRACTED_BYTES', str(2 * 1024 * 1024 * 1024)))
MAX_ARCHIVE_COMPRESSION_RATIO = int(os.getenv('STREAMDOCK_MAX_ARCHIVE_COMPRESSION_RATIO', '1000'))


def _validate_archive_limits(items: list[tuple[str, int]]) -> None:
    if len(items) > MAX_ARCHIVE_MEMBERS:
        raise RuntimeError(f'压缩包成员过多（{len(items)}），上限为 {MAX_ARCHIVE_MEMBERS}')
    extracted_bytes = sum(max(0, size) for _, size in items)
    if extracted_bytes > MAX_ARCHIVE_EXTRACTED_BYTES:
        raise RuntimeError(f'压缩包解压后大小过大（{extracted_bytes} 字节），上限为 {MAX_ARCHIVE_EXTRACTED_BYTES} 字节')


def _ensure_safe_member(output_path: Path, member_name: str) -> Path:
    root = output_path.resolve()
    target = (output_path / member_name).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f'压缩包包含不安全路径，已拒绝解压：{member_name}') from exc
    return target


def _safe_extract_zip(input_path: Path, output_path: Path, *, password: str | None = None) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(input_path) as zf:
        infos = zf.infolist()
        _validate_archive_limits([(info.filename, info.file_size) for info in infos])
        directory_metadata: list[tuple[Path, int, float]] = []
        for info in infos:
            if info.flag_bits & 0x1:
                if not password:
                    raise RuntimeError(f'ZIP 成员已加密，请输入解压密码：{info.filename}')
            if info.file_size > 1024 * 1024 and info.file_size > max(1, info.compress_size) * MAX_ARCHIVE_COMPRESSION_RATIO:
                raise RuntimeError(f'ZIP 成员压缩比异常，疑似压缩炸弹：{info.filename}')
            target = _ensure_safe_member(output_path, info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RuntimeError(f'ZIP 包含符号链接，已拒绝解压：{info.filename}')
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                directory_metadata.append((target, mode, datetime(*info.date_time).timestamp()))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                source_handle = zf.open(info, pwd=password.encode('utf-8') if password else None)
            except (RuntimeError, NotImplementedError) as exc:
                target.unlink(missing_ok=True)
                detail = str(exc).lower()
                if 'password' in detail or 'encrypted' in detail:
                    raise RuntimeError(f'ZIP 密码错误或加密方式不受支持：{info.filename}') from exc
                raise
            with source_handle as src, target.open('wb') as dst:
                copied = 0
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > info.file_size or copied > MAX_ARCHIVE_EXTRACTED_BYTES:
                        raise RuntimeError(f'ZIP 成员实际解压大小超出安全上限：{info.filename}')
                    dst.write(chunk)
            if mode:
                target.chmod(stat.S_IMODE(mode))
            timestamp = datetime(*info.date_time).timestamp()
            os.utime(target, (timestamp, timestamp))
        for target, mode, timestamp in reversed(directory_metadata):
            if mode:
                target.chmod(stat.S_IMODE(mode))
            os.utime(target, (timestamp, timestamp))


def _safe_extract_tar(input_path: Path, output_path: Path, mode: str) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    with tarfile.open(input_path, mode) as tf:
        members = tf.getmembers()
        _validate_archive_limits([(member.name, member.size) for member in members])
        for member in members:
            _ensure_safe_member(output_path, member.name)
            if member.issym() or member.islnk():
                raise RuntimeError(f'TAR 包含链接文件，已拒绝解压：{member.name}')
            if not (member.isfile() or member.isdir()):
                raise RuntimeError(f'TAR 包含特殊文件，已拒绝解压：{member.name}')
        tf.extractall(output_path, filter='data')


def _zip_to_folder(input_path: Path, output_path: Path, *, password: str | None = None) -> list[str]:
    _safe_extract_zip(input_path, output_path, password=password)
    return [f'ZIP 已解压到 {output_path}']


def _folder_to_zip(input_path: Path, output_path: Path) -> list[str]:
    paths = list(input_path.rglob('*'))
    files = [path for path in paths if path.is_file()]
    if any(path.is_symlink() for path in paths):
        raise RuntimeError('打包目录包含符号链接，已拒绝处理')
    _validate_archive_limits([(str(path.relative_to(input_path)), path.stat().st_size) for path in files])
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            zf.write(path, path.relative_to(input_path))
    return ['文件夹已打包为 ZIP']


def _folder_to_targz(input_path: Path, output_path: Path) -> list[str]:
    paths = list(input_path.rglob('*'))
    files = [path for path in paths if path.is_file()]
    if any(path.is_symlink() for path in paths):
        raise RuntimeError('打包目录包含符号链接，已拒绝处理')
    _validate_archive_limits([(str(path.relative_to(input_path)), path.stat().st_size) for path in files])
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
        copied = 0
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            if copied > MAX_ARCHIVE_EXTRACTED_BYTES:
                raise RuntimeError(f'{suffix.upper().lstrip(".")} 解压后大小超出安全上限')
            dst.write(chunk)
    return [f'{suffix.upper().lstrip(".")} 已解压到 {target}']


def _extract_with_libarchive(input_path: Path, output_path: Path, source: str) -> list[str]:
    bsdtar = shutil.which('bsdtar', path=augmented_path())
    if not bsdtar:
        raise RuntimeError(f'缺少 bsdtar/libarchive，无法解压 {source.upper()}')
    env = {**os.environ, 'PATH': augmented_path()}
    listing = subprocess.run(
        [resolve_tool_path('bsdtar'), '-tf', str(input_path)], text=True, capture_output=True,
        timeout=60, env=env,
    )
    if listing.returncode != 0:
        detail = listing.stderr.strip() or listing.stdout.strip()
        if 'passphrase' in detail.lower() or 'password' in detail.lower():
            raise RuntimeError(f'{source.upper()} 已加密，请先解密后重试')
        raise RuntimeError(f'{source.upper()} 成员列表读取失败：{detail}')
    names = [line for line in listing.stdout.splitlines() if line]
    _validate_archive_limits([(name, 0) for name in names])
    for name in names:
        _ensure_safe_member(output_path, name)

    with tempfile.TemporaryDirectory(prefix=f'streamdock_{source}_') as temp_dir:
        staging = Path(temp_dir)
        process = subprocess.Popen(
            [bsdtar, '-xpf', str(input_path), '-C', str(staging), '--no-same-owner'],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        violation: str | None = None
        deadline = time.monotonic() + 10 * 60
        while process.poll() is None:
            if time.monotonic() > deadline:
                violation = f'{source.upper()} 解压超时，已终止'
                process.kill(); break
            candidates = list(staging.rglob('*'))
            if len(candidates) > MAX_ARCHIVE_MEMBERS:
                violation = f'{source.upper()} 解压成员数超出上限'
                process.kill(); break
            total = sum(path.stat().st_size for path in candidates if path.is_file() and not path.is_symlink())
            if total > MAX_ARCHIVE_EXTRACTED_BYTES:
                violation = f'{source.upper()} 解压后大小超出上限'
                process.kill(); break
            time.sleep(.01)
        stdout, stderr = process.communicate()
        if violation:
            raise RuntimeError(violation)
        if process.returncode != 0:
            detail = stderr.strip() or stdout.strip()
            if 'passphrase' in detail.lower() or 'password' in detail.lower():
                raise RuntimeError(f'{source.upper()} 已加密，请先解密后重试')
            raise RuntimeError(f'{source.upper()} 解压失败：{detail}')
        candidates = list(staging.rglob('*'))
        files = [path for path in candidates if path.is_file() and not path.is_symlink()]
        _validate_archive_limits([(str(path.relative_to(staging)), path.stat().st_size) for path in files])
        for path in candidates:
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise RuntimeError(f'{source.upper()} 包含链接或特殊文件，已拒绝：{path.relative_to(staging)}')
        output_path.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging, output_path, dirs_exist_ok=True, copy_function=shutil.copy2)
    return [f'{source.upper()} 已通过 libarchive 安全解压到 {output_path}']


def _extract_rar(input_path: Path, output_path: Path, *, password: str | None = None) -> list[str]:
    try:
        import rarfile  # type: ignore
    except ImportError:
        return _extract_with_libarchive(input_path, output_path, 'rar')
    try:
        with rarfile.RarFile(str(input_path)) as archive:
            volumes = [Path(path) for path in archive.volumelist()]
            missing = [path.name for path in volumes if not path.is_file()]
            if missing:
                raise RuntimeError('RAR 分卷不完整，缺少：' + '、'.join(missing))
            if archive.needs_password() and not password:
                raise RuntimeError('RAR 已加密，请输入解压密码')
            infos = archive.infolist()
            _validate_archive_limits([(info.filename, int(info.file_size or 0)) for info in infos])
            output_path.mkdir(parents=True, exist_ok=True)
            directory_metadata: list[tuple[Path, int, float | None]] = []
            for info in infos:
                target = _ensure_safe_member(output_path, info.filename)
                if info.is_symlink():
                    raise RuntimeError(f'RAR 包含符号链接，已拒绝：{info.filename}')
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    directory_metadata.append((target, int(info.mode or 0), info.mtime.timestamp() if info.mtime else None))
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                copied = 0
                try:
                    source_handle = archive.open(info, pwd=password)
                except rarfile.PasswordRequired as exc:
                    raise RuntimeError('RAR 已加密，请输入解压密码') from exc
                except rarfile.RarWrongPassword as exc:
                    raise RuntimeError('RAR 密码错误') from exc
                with source_handle as source_stream, target.open('wb') as destination:
                    while True:
                        chunk = source_stream.read(1024 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > int(info.file_size or 0) or copied > MAX_ARCHIVE_EXTRACTED_BYTES:
                            raise RuntimeError(f'RAR 成员实际解压大小超出安全上限：{info.filename}')
                        destination.write(chunk)
                if info.mode:
                    target.chmod(stat.S_IMODE(info.mode))
                if info.mtime:
                    timestamp = info.mtime.timestamp()
                    os.utime(target, (timestamp, timestamp))
            for target, mode, timestamp in reversed(directory_metadata):
                if mode:
                    target.chmod(stat.S_IMODE(mode))
                if timestamp is not None:
                    os.utime(target, (timestamp, timestamp))
    except RuntimeError:
        raise
    except Exception as exc:
        detail = str(exc)
        if 'password' in detail.lower():
            raise RuntimeError('RAR 密码错误或加密方式不受支持') from exc
        raise RuntimeError(f'RAR 解压失败：{detail}') from exc
    label = f'RAR 分卷（{len(volumes)} 卷）' if len(volumes) > 1 else 'RAR'
    return [f'{label} 已安全解压到 {output_path}']


def convert_archive(source: str, target: str, input_path: Path, output_path: Path, *, options: dict | None = None) -> list[str]:
    password = str((options or {}).get('password') or '') or None
    if source == 'zip' and target == 'folder':
        return _zip_to_folder(input_path, output_path, password=password)
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
    if source == '7z' and target == 'folder':
        return _extract_with_libarchive(input_path, output_path, source)
    if source == 'rar' and target == 'folder':
        return _extract_rar(input_path, output_path, password=password)
    if source in {'7z', 'rar'} and target == 'zip':
        with tempfile.TemporaryDirectory(prefix=f'streamdock_{source}_to_zip_') as temp_dir:
            extracted = Path(temp_dir) / 'content'
            logs = _extract_rar(input_path, extracted, password=password) if source == 'rar' else _extract_with_libarchive(input_path, extracted, source)
            return logs + _folder_to_zip(extracted, output_path)
    if source == 'zip' and target == 'tar':
        tmp = output_path.with_suffix('')
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            logs = _zip_to_folder(input_path, tmp, password=password)
            with tarfile.open(output_path, 'w') as tf:
                tf.add(tmp, arcname=tmp.name)
            return logs + ['ZIP 已转换为 TAR']
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if source in {'tar', 'tar.gz'} and target == 'zip':
        mode = 'r:gz' if source == 'tar.gz' else 'r'
        tmp = output_path.with_suffix('')
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            _safe_extract_tar(input_path, tmp, mode)
            return [f'{source.upper()} 已解压'] + _folder_to_zip(tmp, output_path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    raise RuntimeError(f'暂不支持压缩包转换 {source} → {target}')
