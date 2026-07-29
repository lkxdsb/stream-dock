from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


MIN_OUTPUT_FREE_BYTES = int(os.getenv('STREAMDOCK_MIN_OUTPUT_FREE_BYTES', str(256 * 1024 * 1024)))
COMMON_TOOL_DIRS = (
    '/opt/homebrew/bin',
    '/opt/homebrew/sbin',
    '/usr/local/bin',
    '/usr/local/sbin',
    '/opt/local/bin',
    '/usr/bin',
    '/bin',
)
MEDIA_EXTENSIONS = {
    'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', 'opus', 'aiff', 'wma', 'amr',
    'mp4', 'mov', 'mkv', 'webm', 'avi', 'flv', 'm4v', '3gp', 'ts',
}
VIDEO_EXTENSIONS = {'mp4', 'mov', 'mkv', 'webm', 'avi', 'flv', 'm4v', '3gp', 'ts'}
AUDIO_EXTENSIONS = MEDIA_EXTENSIONS - VIDEO_EXTENSIONS


def augmented_path(base_path: str | None = None) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for item in str(base_path or os.environ.get('PATH') or '').split(os.pathsep):
        if item and item not in seen:
            parts.append(item)
            seen.add(item)
    for item in COMMON_TOOL_DIRS:
        if item not in seen:
            parts.append(item)
            seen.add(item)
    return os.pathsep.join(parts)


def discover_system_proxies() -> dict[str, str]:
    """Read the OS proxy without letting a lone NO_PROXY hide macOS settings.

    launchd jobs commonly receive ``NO_PROXY`` but not ``HTTP_PROXY``.  On
    macOS, urllib then treats the environment as authoritative and skips the
    active System Settings proxy entirely.  Browser capture still works, while
    requests/ffmpeg time out.  Query the macOS proxy store directly in that
    case; other platforms keep urllib's normal discovery behavior.
    """
    try:
        if sys.platform == 'darwin' and hasattr(urllib.request, 'getproxies_macosx_sysconf'):
            raw = urllib.request.getproxies_macosx_sysconf()
        else:
            raw = urllib.request.getproxies()
    except Exception:
        return {}
    return {
        scheme: str(raw.get(scheme) or '').strip()
        for scheme in ('http', 'https')
        if str(raw.get(scheme) or '').strip()
    }


def network_subprocess_environment(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment where network subprocesses inherit OS proxies."""
    env = dict(os.environ if base_env is None else base_env)
    discovered: dict[str, str] | None = None
    for scheme in ('http', 'https'):
        lower_key = f'{scheme}_proxy'
        upper_key = lower_key.upper()
        value = str(env.get(lower_key) or env.get(upper_key) or '').strip()
        if not value:
            if discovered is None:
                discovered = discover_system_proxies()
            value = str(discovered.get(scheme) or '').strip()
        if value:
            # requests accepts either spelling; ffmpeg relies on lowercase
            # http_proxy for remote HLS inputs, so mirror both explicitly.
            env[lower_key] = value
            env[upper_key] = value
    return env


def ensure_system_proxy_environment() -> dict[str, str]:
    """Hydrate this process once so in-process requests match the browser."""
    hydrated = network_subprocess_environment()
    for key in ('http_proxy', 'HTTP_PROXY', 'https_proxy', 'HTTPS_PROXY'):
        value = hydrated.get(key)
        if value and not os.environ.get(key):
            os.environ[key] = value
    return hydrated


def resolve_tool_path(command: str) -> str:
    found = shutil.which(command, path=augmented_path())
    if found:
        return found
    return command


def format_bytes(value: int) -> str:
    units = ('B', 'KB', 'MB', 'GB', 'TB')
    size = float(max(0, value))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f'{size:.0f}{unit}' if unit == 'B' else f'{size:.1f}{unit}'
        size /= 1024
    return f'{value}B'


def prepare_output_directory(path: Path, *, minimum_free_bytes: int = MIN_OUTPUT_FREE_BYTES) -> dict[str, Any]:
    path = path.expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise RuntimeError('输出路径不是有效目录')
    probe = path / '.streamdock-write-test'
    try:
        probe.write_bytes(b'ok')
    except OSError as exc:
        raise RuntimeError(f'输出目录不可写：{path}') from exc
    finally:
        probe.unlink(missing_ok=True)
    free_bytes = shutil.disk_usage(path).free
    if free_bytes < minimum_free_bytes:
        raise RuntimeError(
            f'磁盘可用空间不足：当前 {format_bytes(free_bytes)}，至少需要保留 {format_bytes(minimum_free_bytes)}'
        )
    return {'path': str(path), 'writable': True, 'freeBytes': free_bytes, 'freeLabel': format_bytes(free_bytes)}


def partial_output_path(final_path: Path, *, token: str | None = None) -> Path:
    safe_token = ''.join(character for character in str(token or '') if character.isalnum())[:48]
    marker = f'streamdock-part-{safe_token}' if safe_token else 'streamdock-part'
    suffix = ''.join(final_path.suffixes)
    if suffix:
        stem = final_path.name[:-len(suffix)]
        return final_path.with_name(f'.{stem}.{marker}{suffix}')
    return final_path.with_name(f'.{final_path.name}.{marker}')


def cleanup_partial(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def cleanup_task_partials(output_dir: Path, task_id: str) -> int:
    safe_token = ''.join(character for character in str(task_id or '') if character.isalnum())[:48]
    if not safe_token:
        return 0
    output_dir = output_dir.expanduser().resolve()
    if not output_dir.is_dir():
        return 0
    deleted = 0
    for candidate in output_dir.glob(f'.*.streamdock-part-{safe_token}*'):
        cleanup_partial(candidate)
        deleted += 1
    return deleted


def commit_partial(partial_path: Path, final_path: Path) -> Path:
    if not partial_path.exists():
        raise RuntimeError('处理完成但未生成临时输出文件')
    partial_path.replace(final_path)
    return final_path


def _ffprobe(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which('ffprobe', path=augmented_path())
    if not ffprobe:
        raise RuntimeError('缺少 ffprobe，无法校验音视频输出')
    completed = subprocess.run(
        [
            ffprobe, '-v', 'error', '-show_entries',
            'format=format_name,duration,size:stream=codec_type,codec_name,width,height,duration',
            '-of', 'json', str(path),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else '无法读取媒体信息'
        raise RuntimeError(f'输出文件校验失败：{detail}')
    try:
        return json.loads(completed.stdout or '{}')
    except json.JSONDecodeError as exc:
        raise RuntimeError('ffprobe 未返回有效媒体信息') from exc


def validate_media_output(path: Path, *, expected_kind: str | None = None) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise RuntimeError('输出文件不存在')
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError('输出文件大小为 0')
    probe = _ffprobe(path)
    streams = list(probe.get('streams') or [])
    videos = [stream for stream in streams if stream.get('codec_type') == 'video']
    audios = [stream for stream in streams if stream.get('codec_type') == 'audio']
    if expected_kind == 'video' and not videos:
        raise RuntimeError('输出异常：文件中未检测到视频流')
    if expected_kind == 'audio' and not audios:
        raise RuntimeError('输出异常：文件中未检测到音频流')
    format_info = probe.get('format') or {}
    duration = float(format_info.get('duration') or 0)
    primary_video = videos[0] if videos else {}
    primary_audio = audios[0] if audios else {}
    video_duration = float(primary_video.get('duration') or duration or 0)
    audio_duration = float(primary_audio.get('duration') or duration or 0)
    duration_delta = abs(video_duration - audio_duration) if videos and audios else 0
    if videos and audios and video_duration > 0 and audio_duration > 0:
        allowed_delta = max(2.0, max(video_duration, audio_duration) * .05)
        if abs(video_duration - audio_duration) > allowed_delta:
            raise RuntimeError(
                f'输出异常：音视频时长差过大（视频 {video_duration:.1f}s，音频 {audio_duration:.1f}s）'
            )
    warnings: list[str] = []
    width = int(primary_video.get('width') or 0)
    height = int(primary_video.get('height') or 0)
    bit_rate = int(float(format_info.get('bit_rate') or primary_video.get('bit_rate') or 0))
    if videos and (width <= 0 or height <= 0):
        warnings.append('无法确认实际画面尺寸')
    if videos and bit_rate and bit_rate < 250_000:
        warnings.append('视频总码率偏低，实际画质可能不及分辨率标识')
    if duration <= 0:
        warnings.append('无法确认媒体时长')
    quality_score = max(0, 100 - len(warnings) * 15 - (10 if duration_delta > 1 else 0))
    return {
        'valid': True,
        'kind': 'video' if videos else 'audio' if audios else 'unknown',
        'sizeBytes': size,
        'sizeLabel': format_bytes(size),
        'durationSeconds': round(duration, 3),
        'videoDurationSeconds': round(video_duration, 3),
        'audioDurationSeconds': round(audio_duration, 3),
        'format': str(format_info.get('format_name') or ''),
        'hasVideo': bool(videos),
        'hasAudio': bool(audios),
        'videoCodec': primary_video.get('codec_name'),
        'audioCodec': primary_audio.get('codec_name'),
        'width': width or None,
        'height': height or None,
        'bitrate': bit_rate or None,
        'audioVideoDeltaSeconds': round(duration_delta, 3),
        'qualityScore': quality_score,
        'qualityLevel': '良好' if quality_score >= 90 else '可用' if quality_score >= 60 else '需要重试',
        'warnings': warnings,
    }


def deep_media_quality(path: Path, *, timeout_seconds: int = 180) -> dict[str, Any]:
    """Run optional full-stream anomaly detection without modifying the media."""
    base = validate_media_output(path, expected_kind='video')
    ffmpeg = shutil.which('ffmpeg', path=augmented_path())
    if not ffmpeg:
        raise RuntimeError('缺少 FFmpeg，无法执行深度质量检测')
    command = [
        ffmpeg, '-hide_banner', '-nostats', '-i', str(path),
        '-vf', 'blackdetect=d=2:pix_th=0.10,freezedetect=n=-50dB:d=3',
        '-af', 'silencedetect=n=-50dB:d=3', '-f', 'null', '-',
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'深度质量检测超时（{timeout_seconds} 秒）') from exc
    log = completed.stderr or ''
    black = [
        {'start': float(start), 'end': float(end), 'duration': float(duration)}
        for start, end, duration in re.findall(r'black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)', log)
    ]
    silence_starts = [float(value) for value in re.findall(r'silence_start:\s*([0-9.]+)', log)]
    silence_ends = [(float(end), float(duration)) for end, duration in re.findall(r'silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)', log)]
    silence = [
        {'start': silence_starts[index] if index < len(silence_starts) else max(0, end - duration), 'end': end, 'duration': duration}
        for index, (end, duration) in enumerate(silence_ends)
    ]
    freeze_starts = [float(value) for value in re.findall(r'freeze_start:\s*([0-9.]+)', log)]
    freeze_ends = [(float(end), float(duration)) for end, duration in re.findall(r'freeze_end:\s*([0-9.]+)\s*\|\s*freeze_duration:\s*([0-9.]+)', log)]
    freezes = [
        {'start': freeze_starts[index] if index < len(freeze_starts) else max(0, end - duration), 'end': end, 'duration': duration}
        for index, (end, duration) in enumerate(freeze_ends)
    ]
    warnings = [
        *(f'检测到 {len(black)} 个连续黑屏区间' for _ in [0] if black),
        *(f'检测到 {len(silence)} 个长静音区间' for _ in [0] if silence),
        *(f'检测到 {len(freezes)} 个画面冻结区间' for _ in [0] if freezes),
    ]
    return {
        'valid': completed.returncode == 0,
        'base': base,
        'blackIntervals': black,
        'silenceIntervals': silence,
        'freezeIntervals': freezes,
        'warnings': warnings,
        'deepQualityScore': max(0, int(base.get('qualityScore') or 100) - len(black) * 8 - len(silence) * 3 - len(freezes) * 8),
    }


def validate_general_output(path: Path, *, target: str) -> dict[str, Any]:
    target = target.lower().lstrip('.')
    if target == 'folder':
        if not path.exists() or not path.is_dir():
            raise RuntimeError('输出目录未生成')
        entries = sum(1 for _ in path.rglob('*'))
        return {'valid': True, 'kind': 'folder', 'entryCount': entries, 'sizeBytes': 0, 'sizeLabel': '-'}
    if not path.exists() or not path.is_file():
        raise RuntimeError('输出文件不存在')
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError('输出文件大小为 0')
    if target in MEDIA_EXTENSIONS:
        expected_kind = 'video' if target in VIDEO_EXTENSIONS else 'audio'
        return validate_media_output(path, expected_kind=expected_kind)

    from converters.sniff import validate_declared_format

    valid, detected = validate_declared_format(path, target)
    if not valid:
        raise RuntimeError(f'输出格式校验失败：期望 {target.upper()}，实际识别为 {(detected or "未知").upper()}')
    return {
        'valid': True,
        'kind': 'file',
        'sizeBytes': size,
        'sizeLabel': format_bytes(size),
        'detectedFormat': detected or target,
    }


def environment_health(output_path: str | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    python_ok = sys.version_info >= (3, 11)
    checks.append({
        'key': 'python',
        'name': 'Python 运行时',
        'status': 'ok' if python_ok else 'error',
        'detail': f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}' + ('' if python_ok else ' · 需要 Python 3.11+'),
        'required': True,
    })
    for name, command, required in (
        ('FFmpeg', 'ffmpeg', True),
        ('FFprobe', 'ffprobe', True),
    ):
        found = shutil.which(command, path=augmented_path())
        checks.append({
            'key': command,
            'name': name,
            'status': 'ok' if found else 'missing',
            'detail': found or f'未找到 {command}',
            'required': required,
        })
    try:
        import PIL  # noqa: F401
        checks.append({'key': 'pillow', 'name': '图片转换', 'status': 'ok', 'detail': 'Pillow 可用', 'required': False})
    except ImportError:
        checks.append({'key': 'pillow', 'name': '图片转换', 'status': 'missing', 'detail': '未安装 Pillow', 'required': False})
    try:
        import openpyxl  # noqa: F401
        checks.append({'key': 'openpyxl', 'name': '表格转换', 'status': 'ok', 'detail': 'openpyxl 可用', 'required': False})
    except ImportError:
        checks.append({'key': 'openpyxl', 'name': '表格转换', 'status': 'missing', 'detail': '未安装 openpyxl', 'required': False})

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser_path = Path(playwright.chromium.executable_path)
        checks.append({
            'key': 'playwright',
            'name': '浏览器解析',
            'status': 'ok' if browser_path.exists() else 'missing',
            'detail': str(browser_path) if browser_path.exists() else 'Playwright 已安装，但 Chromium 浏览器尚未安装',
            'required': False,
        })
    except Exception as exc:
        checks.append({'key': 'playwright', 'name': '浏览器解析', 'status': 'missing', 'detail': f'Playwright 不可用：{exc}', 'required': False})

    try:
        from fetchers.subtitle_asr import asr_engine_status
        asr_status = asr_engine_status()
        checks.append({
            'key': 'subtitle_asr',
            'name': '语音字幕',
            'status': 'ok' if asr_status.available else 'missing',
            'detail': asr_status.detail or ('可用' if asr_status.available else '未安装 Whisper'),
            'required': False,
        })
    except Exception as exc:
        checks.append({'key': 'subtitle_asr', 'name': '语音字幕', 'status': 'error', 'detail': str(exc), 'required': False})

    try:
        from fetchers.subtitle_ocr import ocr_available

        ocr_ready = ocr_available()
        checks.append({
            'key': 'subtitle_ocr',
            'name': '画面字幕 OCR',
            'status': 'ok' if ocr_ready else 'missing',
            'detail': 'Tesseract 与 FFmpeg 可用' if ocr_ready else '需要 Tesseract 与 FFmpeg',
            'required': False,
        })
    except Exception as exc:
        checks.append({'key': 'subtitle_ocr', 'name': '画面字幕 OCR', 'status': 'error', 'detail': str(exc), 'required': False})

    try:
        from pdf_engine.providers.mineru import MinerUProvider

        pdf_status = MinerUProvider().health()
        checks.append({
            'key': 'pdf_engine',
            'name': 'PDF 深度解析',
            'status': 'ok' if pdf_status.get('available') else 'missing',
            'detail': str(pdf_status.get('detail') or '未安装独立 PDF 解析环境'),
            'required': False,
        })
    except Exception as exc:
        checks.append({'key': 'pdf_engine', 'name': 'PDF 深度解析', 'status': 'error', 'detail': str(exc), 'required': False})

    output = Path(output_path or '~/Downloads/StreamDock').expanduser()
    try:
        output_info = prepare_output_directory(output)
        checks.append({
            'key': 'output', 'name': '输出目录', 'status': 'ok',
            'detail': f'可写 · 可用 {output_info["freeLabel"]}', 'required': True,
        })
    except RuntimeError as exc:
        checks.append({'key': 'output', 'name': '输出目录', 'status': 'error', 'detail': str(exc), 'required': True})
    healthy = all(item['status'] == 'ok' for item in checks if item['required'])
    available_count = sum(item['status'] == 'ok' for item in checks)
    return {
        'healthy': healthy,
        'summary': {
            'available': available_count,
            'total': len(checks),
            'requiredReady': sum(item['required'] and item['status'] == 'ok' for item in checks),
            'requiredTotal': sum(bool(item['required']) for item in checks),
        },
        'checks': checks,
    }
