from __future__ import annotations

import os
import json
import shutil
import subprocess
from pathlib import Path

from runtime_checks import augmented_path, resolve_tool_path

MEDIA_CONVERT_TIMEOUT_SECONDS = int(os.getenv('STREAMDOCK_MEDIA_CONVERT_TIMEOUT_SECONDS', str(20 * 60)))


def _attached_picture_stream(input_path: Path) -> int | None:
    """Return the absolute stream index of an attached cover, if present."""
    ffprobe = resolve_tool_path('ffprobe')
    if not shutil.which('ffprobe', path=augmented_path()):
        return None
    try:
        completed = subprocess.run(
            [ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(input_path)],
            text=True,
            capture_output=True,
            timeout=30,
            env={**os.environ, 'PATH': augmented_path()},
        )
        if completed.returncode != 0:
            return None
        for stream in json.loads(completed.stdout or '{}').get('streams', []):
            if stream.get('codec_type') == 'video' and stream.get('disposition', {}).get('attached_pic') == 1:
                return int(stream['index'])
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return None
    return None


def convert_media(
    source: str,
    target: str,
    input_path: Path,
    output_path: Path,
    *,
    options: dict | None = None,
) -> list[str]:
    ffmpeg = resolve_tool_path('ffmpeg')
    if not shutil.which('ffmpeg', path=augmented_path()):
        raise RuntimeError('缺少 ffmpeg，无法处理音视频转换')

    options = dict(options or {})
    audio_bitrate = max(32, min(512, int(options.get('audioBitrateKbps') or 192)))
    sample_rate = max(0, min(192000, int(options.get('audioSampleRate') or 0)))
    max_width = max(0, min(7680, int(options.get('videoMaxWidth') or 0)))
    frame_rate = max(0, min(240, int(options.get('videoFrameRate') or 0)))
    video_bitrate = max(0, min(100000, int(options.get('videoBitrateKbps') or 0)))
    video_crf = max(0, min(51, int(options.get('videoCrf') if options.get('videoCrf') is not None else 22)))
    hardware = str(options.get('hardwareAcceleration') or 'software')
    cover_stream = _attached_picture_stream(input_path) if target in {'mp3', 'm4a'} else None

    # Make preservation explicit instead of relying on FFmpeg's container-
    # dependent defaults.  Stream/codec choices below may still make an item
    # unsupported (for example subtitles in an audio-only output), but global
    # tags and chapters are retained whenever the target format supports them.
    cmd = [ffmpeg, '-y']
    if hardware == 'videotoolbox':
        cmd += ['-hwaccel', 'videotoolbox']
    cmd += ['-i', str(input_path), '-map_metadata', '0', '-map_chapters', '0']
    if target in {'mp3', 'm4a', 'aac', 'wav', 'flac', 'ogg', 'opus'}:
        if target == 'mp3':
            cmd += ['-map', '0:a:0', '-codec:a', 'libmp3lame', '-b:a', f'{audio_bitrate}k']
            if cover_stream is not None:
                cmd += ['-map', f'0:{cover_stream}', '-c:v', 'copy', '-disposition:v', 'attached_pic']
        elif target == 'm4a':
            cmd += ['-map', '0:a:0', '-codec:a', 'aac', '-b:a', f'{audio_bitrate}k']
            if cover_stream is not None:
                cmd += ['-map', f'0:{cover_stream}', '-c:v', 'copy', '-disposition:v', 'attached_pic']
        elif target == 'aac':
            cmd += ['-vn', '-codec:a', 'aac', '-b:a', f'{audio_bitrate}k']
        else:
            cmd += ['-vn']
        if sample_rate:
            cmd += ['-ar', str(sample_rate)]
    elif target == 'gif':
        cmd += ['-vf', 'fps=12,scale=640:-1:flags=lanczos']
    elif target == 'mp4':
        cmd += ['-map', '0:V:0', '-map', '0:a?', '-map', '0:s?']
        if hardware == 'videotoolbox':
            cmd += ['-c:v', 'h264_videotoolbox', '-b:v', f'{video_bitrate or 4000}k']
        else:
            cmd += ['-c:v', 'libx264', '-preset', 'medium']
            cmd += ['-b:v', f'{video_bitrate}k'] if video_bitrate else ['-crf', str(video_crf)]
        cmd += ['-c:a', 'aac', '-b:a', f'{audio_bitrate}k', '-c:s', 'mov_text']
    elif target == 'webm':
        cmd += ['-map', '0:V:0', '-map', '0:a?', '-map', '0:s?', '-c:v', 'libvpx-vp9', '-b:v', f'{video_bitrate}k' if video_bitrate else '0', '-crf', str(max(0, min(63, video_crf))), '-c:a', 'libopus', '-b:a', f'{audio_bitrate}k', '-c:s', 'webvtt']
    filters = []
    if max_width:
        filters.append(f'scale={max_width}:-2:force_original_aspect_ratio=decrease')
    if frame_rate:
        filters.append(f'fps={frame_rate}')
    if filters and target in {'mp4', 'webm'}:
        cmd += ['-vf', ','.join(filters)]
    if sample_rate and target in {'mp4', 'webm'}:
        cmd += ['-ar', str(sample_rate)]
    cmd.append(str(output_path))

    try:
        env = {**os.environ, 'PATH': augmented_path()}
        completed = subprocess.run(cmd, text=True, capture_output=True, timeout=MEDIA_CONVERT_TIMEOUT_SECONDS, env=env)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'ffmpeg 转换超时，已停止任务（{MEDIA_CONVERT_TIMEOUT_SECONDS} 秒）') from exc
    if completed.returncode != 0:
        tail = '\n'.join(completed.stderr.splitlines()[-8:])
        raise RuntimeError(f'ffmpeg 转换失败：{tail}')
    return [
        f'执行 ffmpeg：{source.upper()} → {target.upper()}',
        f'参数：音频 {audio_bitrate} kbps' + (f' · {sample_rate} Hz' if sample_rate else '') + (f' · 最大宽度 {max_width}' if max_width else '') + (f' · {frame_rate} fps' if frame_rate else ''),
        f'视频编码：{hardware if hardware != "software" else "software"} · CRF {video_crf}' + (f' · {video_bitrate} kbps' if video_bitrate else ''),
        '音视频转换完成',
    ]
