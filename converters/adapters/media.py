from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from runtime_checks import augmented_path, resolve_tool_path

MEDIA_CONVERT_TIMEOUT_SECONDS = int(os.getenv('STREAMDOCK_MEDIA_CONVERT_TIMEOUT_SECONDS', str(20 * 60)))


def convert_media(source: str, target: str, input_path: Path, output_path: Path) -> list[str]:
    ffmpeg = resolve_tool_path('ffmpeg')
    if not shutil.which('ffmpeg', path=augmented_path()):
        raise RuntimeError('缺少 ffmpeg，无法处理音视频转换')

    cmd = [ffmpeg, '-y', '-i', str(input_path)]
    if target in {'mp3', 'm4a', 'aac', 'wav', 'flac', 'ogg', 'opus'}:
        cmd += ['-vn']
        if target == 'mp3':
            cmd += ['-codec:a', 'libmp3lame', '-b:a', '192k']
        elif target == 'm4a':
            cmd += ['-codec:a', 'aac', '-b:a', '192k']
        elif target == 'aac':
            cmd += ['-codec:a', 'aac', '-b:a', '192k']
    elif target == 'gif':
        cmd += ['-vf', 'fps=12,scale=640:-1:flags=lanczos']
    elif target == 'mp4':
        cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '22', '-c:a', 'aac']
    elif target == 'webm':
        cmd += ['-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '32', '-c:a', 'libopus']
    cmd.append(str(output_path))

    try:
        env = {**os.environ, 'PATH': augmented_path()}
        completed = subprocess.run(cmd, text=True, capture_output=True, timeout=MEDIA_CONVERT_TIMEOUT_SECONDS, env=env)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'ffmpeg 转换超时，已停止任务（{MEDIA_CONVERT_TIMEOUT_SECONDS} 秒）') from exc
    if completed.returncode != 0:
        tail = '\n'.join(completed.stderr.splitlines()[-8:])
        raise RuntimeError(f'ffmpeg 转换失败：{tail}')
    return [f'执行 ffmpeg：{source.upper()} → {target.upper()}', '音视频转换完成']
