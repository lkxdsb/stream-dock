from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from runtime_checks import resolve_tool_path

FFMPEG_EXPORT_TIMEOUT_SECONDS = int(os.getenv('STREAMDOCK_FFMPEG_EXPORT_TIMEOUT_SECONDS', str(20 * 60)))


@dataclass(frozen=True)
class OutputFormatSpec:
    extension: str
    kind: str
    mode: str
    needs_video_stream: bool
    needs_audio_stream: bool


OUTPUT_FORMATS: dict[str, OutputFormatSpec] = {
    "m4a": OutputFormatSpec("m4a", "audio", "extract", False, True),
    "mp3": OutputFormatSpec("mp3", "audio", "transcode", False, True),
    "mp4": OutputFormatSpec("mp4", "video", "mux", True, False),
    "wav": OutputFormatSpec("wav", "audio", "transcode", False, True),
    "flac": OutputFormatSpec("flac", "audio", "transcode", False, True),
    "aac": OutputFormatSpec("aac", "audio", "transcode", False, True),
    "ogg": OutputFormatSpec("ogg", "audio", "transcode", False, True),
    "opus": OutputFormatSpec("opus", "audio", "transcode", False, True),
    "mkv": OutputFormatSpec("mkv", "video", "mux", True, False),
    "mov": OutputFormatSpec("mov", "video", "mux", True, False),
    "webm": OutputFormatSpec("webm", "video", "transcode", True, True),
}


def get_output_format_spec(output_type: str) -> OutputFormatSpec:
    try:
        return OUTPUT_FORMATS[output_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported output type: {output_type}") from exc


def is_audio_output(output_type: str) -> bool:
    return get_output_format_spec(output_type).kind == "audio"


def is_video_output(output_type: str) -> bool:
    return get_output_format_spec(output_type).kind == "video"


def validate_output_request(*, media_kind: str, output_type: str) -> None:
    spec = get_output_format_spec(output_type)
    if spec.kind == "video" and media_kind != "video":
        raise ValueError(f"Only audio stream found; cannot export a real {output_type} video")


def run_ffmpeg(args: list[str]) -> None:
    command = list(args)
    if command and command[0] == "ffmpeg":
        command[0] = resolve_tool_path("ffmpeg")
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=FFMPEG_EXPORT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'ffmpeg 导出超时，已停止任务（{FFMPEG_EXPORT_TIMEOUT_SECONDS} 秒）') from exc


def resolve_audio_source(source_video: Path | None, source_audio: Path | None) -> Path:
    if source_audio is not None:
        return source_audio
    if source_video is not None:
        return source_video
    raise ValueError("No source available for audio export")


def merge_streams_to_mp4(video_file: Path, audio_file: Path, final_path: Path) -> Path:
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_file),
            "-i",
            str(audio_file),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            str(final_path),
        ]
    )
    return final_path


def mux_streams(video_file: Path, audio_file: Path | None, final_path: Path) -> Path:
    if audio_file is None:
        shutil.copyfile(video_file, final_path)
        return final_path
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_file),
            "-i",
            str(audio_file),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            str(final_path),
        ]
    )
    return final_path


def transcode_audio(source_path: Path, final_path: Path, output_type: str) -> Path:
    command_map = {
        "mp3": ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-acodec", "libmp3lame", "-q:a", "2", str(final_path)],
        "wav": ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-acodec", "pcm_s16le", str(final_path)],
        "flac": ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-acodec", "flac", str(final_path)],
        "aac": ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-c:a", "aac", "-b:a", "192k", str(final_path)],
        "ogg": ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-ac", "2", "-c:a", "vorbis", "-strict", "-2", "-q:a", "5", str(final_path)],
        "opus": ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-c:a", "libopus", "-b:a", "160k", str(final_path)],
    }
    run_ffmpeg(command_map[output_type])
    return final_path


def export_audio(source_video: Path | None, source_audio: Path | None, final_path: Path, output_type: str) -> Path:
    audio_source = resolve_audio_source(source_video, source_audio)
    if output_type == "m4a":
        run_ffmpeg(["ffmpeg", "-y", "-i", str(audio_source), "-vn", "-c:a", "copy", str(final_path)])
        return final_path
    return transcode_audio(audio_source, final_path, output_type)


def transcode_to_webm(video_file: Path, audio_file: Path | None, final_path: Path) -> Path:
    command = ["ffmpeg", "-y", "-i", str(video_file)]
    if audio_file is not None:
        command.extend(["-i", str(audio_file)])
    command.extend(
        [
            "-c:v",
            "libvpx-vp9",
            "-b:v",
            "0",
            "-crf",
            "32",
            "-c:a",
            "libopus",
            "-b:a",
            "160k",
            str(final_path),
        ]
    )
    run_ffmpeg(command)
    return final_path


def export_video(source_video: Path | None, source_audio: Path | None, final_path: Path, output_type: str) -> Path:
    if source_video is None:
        raise ValueError(f"No video stream available for {output_type} export")
    if output_type in {"mp4", "mkv", "mov"}:
        return mux_streams(source_video, source_audio, final_path)
    if output_type == "webm":
        return transcode_to_webm(source_video, source_audio, final_path)
    raise ValueError(f"Unsupported video output type: {output_type}")


def export_media(
    *,
    source_video: Path | None,
    source_audio: Path | None,
    output_dir: Path,
    base_name: str,
    output_type: str,
) -> Path:
    spec = get_output_format_spec(output_type)
    final_path = output_dir / f"{base_name}.{spec.extension}"
    if spec.kind == "audio":
        return export_audio(source_video, source_audio, final_path, output_type)
    return export_video(source_video, source_audio, final_path, output_type)
