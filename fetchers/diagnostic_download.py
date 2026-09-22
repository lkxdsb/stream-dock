"""Explicit, bounded server-side media download and full-decode diagnostic."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from PIL import Image
from fetchers.auth_context import scoped_request

from fetchers.downloader import is_hls_url
from fetchers.models import MediaFetchResult, MediaStream
from runtime_checks import network_subprocess_environment, resolve_tool_path, validate_media_output


MAX_BYTES = min(256 * 1024 * 1024, max(1024 * 1024, int(os.getenv('STREAMDOCK_DIAGNOSTIC_MAX_BYTES', str(64 * 1024 * 1024)))))
MAX_SECONDS = 180


def _hls_source(url: str, headers: dict[str, str]) -> tuple[str, float]:
    """Resolve at most one master layer and require a finite VOD media playlist."""
    for _ in range(2):
        with scoped_request('get', url, headers=headers, timeout=(5, 15), stream=True) as response:
            response.raise_for_status()
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=16 * 1024):
                total += len(chunk)
                if total > 512 * 1024:
                    raise RuntimeError('HLS 清单超过诊断上限')
                chunks.append(chunk)
            manifest = b''.join(chunks).decode('utf-8-sig', errors='replace')
        if not manifest.startswith('#EXTM3U'):
            raise RuntimeError('HLS 地址未返回有效清单')
        lines = [line.strip() for line in manifest.splitlines() if line.strip()]
        variants = []
        for index, line in enumerate(lines[:-1]):
            if line.startswith('#EXT-X-STREAM-INF:') and not lines[index + 1].startswith('#'):
                bandwidth = re.search(r'BANDWIDTH=(\d+)', line)
                variants.append((int(bandwidth.group(1)) if bandwidth else 0, urljoin(url, lines[index + 1])))
        if variants:
            url = max(variants)[1]
            continue
        if '#EXT-X-ENDLIST' not in lines:
            raise RuntimeError('HLS 清单非完整点播内容，不能判定整片通过')
        durations = [float(match.group(1)) for line in lines
                     if (match := re.match(r'#EXTINF:([0-9.]+)', line))]
        if not durations:
            raise RuntimeError('HLS 清单没有可核对的分段时长')
        return url, sum(durations)
    raise RuntimeError('HLS 主清单嵌套过深')


def _download(stream: MediaStream, path: Path, headers: dict[str, str], deadline: float) -> float | None:
    if is_hls_url(stream.url) or stream.container == 'm3u8':
        media_url, expected_duration = _hls_source(stream.url, headers)
        remaining = max(1, int(deadline - time.monotonic()))
        command = [resolve_tool_path('ffmpeg'), '-nostdin', '-v', 'error', '-y',
                   '-headers', f"User-Agent: {headers['User-Agent']}\r\nReferer: {headers['Referer']}\r\n",
                   '-i', media_url, '-c', 'copy', '-fs', str(MAX_BYTES), str(path)]
        subprocess.run(command, check=True, timeout=remaining, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, env=network_subprocess_environment())
        if not path.is_file() or path.stat().st_size >= MAX_BYTES:
            raise RuntimeError('HLS 完整资源超过诊断字节上限，不能标记为完整通过')
        return expected_duration
    if stream.url.startswith(('ytdlp:', 'ytdlp+chrome:')):
        raise ValueError('诊断完整下载暂不支持 yt-dlp 虚拟地址')
    with scoped_request('get', stream.url, headers=headers, timeout=(5, 15), stream=True) as response:
        response.raise_for_status()
        content_type = str(response.headers.get('content-type') or '').lower()
        if content_type.startswith(('text/', 'application/xml', 'application/json')):
            raise RuntimeError('上游返回非媒体响应')
        declared_length = str(response.headers.get('content-length') or '')
        if declared_length.isdigit() and int(declared_length) > MAX_BYTES:
            raise RuntimeError('完整资源超过诊断字节上限')
        size = 0
        with path.open('wb') as output:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if time.monotonic() >= deadline:
                    raise TimeoutError('完整下载超过诊断时间上限')
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_BYTES:
                    raise RuntimeError('完整资源超过诊断字节上限')
                output.write(chunk)
    if size <= 0:
        raise RuntimeError('下载资源为空')
    if declared_length.isdigit() and size != int(declared_length):
        raise RuntimeError('实际下载字节数与资源声明长度不符')
    return None


def _decode(path: Path, deadline: float) -> None:
    remaining = max(1, int(deadline - time.monotonic()))
    command = [resolve_tool_path('ffmpeg'), '-nostdin', '-v', 'error', '-i', str(path), '-f', 'null', '-']
    subprocess.run(command, check=True, timeout=remaining, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def validate_full_download(result: MediaFetchResult, *, user_agent: str, referer: str) -> dict[str, object]:
    if result.content_type == 'images':
        if not result.image_assets or len(result.image_assets) > 20:
            raise ValueError('图文诊断需要 1–20 张图片')
        headers = {'User-Agent': user_agent, 'Referer': referer}
        deadline = time.monotonic() + MAX_SECONDS
        details = []
        total = 0
        with tempfile.TemporaryDirectory(prefix='streamdock-image-diagnostic-') as directory:
            for index, asset in enumerate(result.image_assets, start=1):
                path = Path(directory) / f'{index:02d}.image'
                with scoped_request('get', asset.url, headers=headers, timeout=(5, 15), stream=True) as response:
                    response.raise_for_status()
                    with path.open('wb') as output:
                        for chunk in response.iter_content(chunk_size=256 * 1024):
                            if time.monotonic() >= deadline:
                                raise TimeoutError('图文下载超过诊断时间上限')
                            total += len(chunk)
                            if total > MAX_BYTES:
                                raise RuntimeError('图文集合超过诊断字节上限')
                            output.write(chunk)
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    details.append({'index': index, 'format': image.format, 'width': image.width,
                                    'height': image.height, 'sizeBytes': path.stat().st_size})
        return {'valid': True, 'kind': 'images', 'imageCount': len(details), 'images': details,
                'scope': 'all-extracted-images'}
    if result.preferred_video is None:
        raise ValueError('完整视频诊断需要视频候选流')
    deadline = time.monotonic() + MAX_SECONDS
    headers = {'User-Agent': user_agent, 'Referer': referer}
    with tempfile.TemporaryDirectory(prefix='streamdock-media-diagnostic-') as directory:
        root = Path(directory)
        video = root / 'video.mp4'
        expected_video_duration = _download(result.preferred_video, video, headers, deadline)
        video_info = validate_media_output(video, expected_kind='video')
        if expected_video_duration and abs(float(video_info['durationSeconds']) - expected_video_duration) > max(.5, expected_video_duration * .03):
            raise RuntimeError('HLS 下载时长与完整清单不符，不能标记为整片通过')
        _decode(video, deadline)
        audio_info = None
        if result.preferred_audio:
            audio = root / 'audio.m4a'
            expected_audio_duration = _download(result.preferred_audio, audio, headers, deadline)
            audio_info = validate_media_output(audio, expected_kind='audio')
            if expected_audio_duration and abs(float(audio_info['durationSeconds']) - expected_audio_duration) > max(.5, expected_audio_duration * .03):
                raise RuntimeError('HLS 音轨下载时长与完整清单不符')
            _decode(audio, deadline)
        frame = root / 'frame.jpg'
        subprocess.run([resolve_tool_path('ffmpeg'), '-nostdin', '-v', 'error', '-y', '-ss', '1', '-i', str(video),
                        '-frames:v', '1', str(frame)], check=True,
                       timeout=max(1, int(deadline - time.monotonic())),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not frame.exists() or frame.stat().st_size < 100:
            raise RuntimeError('视频抽帧结果为空')
        digest = hashlib.sha256()
        with video.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        return {'valid': True, 'video': video_info, 'audio': audio_info,
                'videoSha256': digest.hexdigest(),
                'frameBytes': frame.stat().st_size,
                'scope': 'selected-stream-only'}
