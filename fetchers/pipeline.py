from __future__ import annotations

import re
import os
import tempfile
from pathlib import Path
from typing import Callable

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.downloader import download_media
from fetchers.exporters import export_media, is_video_output, validate_output_request
from fetchers.models import ExportRequest, MediaFetchResult, MediaStream, ResolvedMediaSelection
from runtime_checks import cleanup_partial, commit_partial, partial_output_path, prepare_output_directory, validate_media_output

INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')
ProgressCallback = Callable[[float | None, str], None]


def detect_platform_adapter(raw_link: str) -> BasePlatformAdapter:
    from fetchers.registry import get_registered_adapters

    for adapter in get_registered_adapters():
        if adapter.can_handle(raw_link):
            return adapter
    raise ValueError(f"Unsupported platform link: {raw_link}")


def sanitize_filename(name: str, max_length: int = 120) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", name).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "media_output"
    return cleaned[:max_length].strip()


def ensure_output_dir(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    prepare_output_directory(path)
    return path


def available_output_path(output_dir: Path, base_name: str, extension: str) -> Path:
    candidate = output_dir / f'{base_name}.{extension}'
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = output_dir / f'{base_name}_{index}.{extension}'
        if not candidate.exists():
            return candidate
        index += 1


def probe_media(raw_link: str, adapter: BasePlatformAdapter | None = None) -> MediaFetchResult:
    selected_adapter = adapter or detect_platform_adapter(raw_link)
    normalized_link = selected_adapter.normalize_link(raw_link)
    return selected_adapter.fetch_media(normalized_link)


def resolve_media_selection(
    fetch_result: MediaFetchResult,
    *,
    output_type: str,
    video_quality: str | None = None,
) -> ResolvedMediaSelection:
    validate_output_request(
        media_kind=fetch_result.content_type,
        output_type=output_type,
    )

    video_stream = fetch_result.preferred_video
    if is_video_output(output_type) and video_quality:
        exact_url_match = next(
            (stream for stream in fetch_result.video_streams if stream.url == video_quality),
            None,
        )
        quality_matches = [
            stream for stream in fetch_result.video_streams if stream.quality_label == video_quality
        ]
        selected_stream = exact_url_match or (
            max(
                quality_matches,
                key=lambda stream: (
                    stream.height or 0,
                    stream.width or 0,
                    stream.bitrate or 0,
                    stream.filesize or 0,
                ),
            )
            if quality_matches
            else None
        )
        if selected_stream is None:
            raise ValueError(f"Requested video quality not found: {video_quality}")
        video_stream = selected_stream

    return ResolvedMediaSelection(
        video_stream=video_stream,
        audio_stream=fetch_result.preferred_audio,
        title=fetch_result.title,
        output_type=output_type,
    )


def run_pipeline(
    *,
    raw_link: str,
    export_request: ExportRequest,
    adapter: BasePlatformAdapter | None = None,
    dry_run: bool = False,
    video_quality: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    def progress(value: float | None, stage: str) -> None:
        if progress_callback:
            progress_callback(value, stage)

    progress(3, '正在规范化链接')
    selected_adapter = adapter or detect_platform_adapter(raw_link)
    normalized_link = selected_adapter.normalize_link(raw_link)
    progress(8, '正在识别平台资源')
    fetch_result = selected_adapter.fetch_media(normalized_link)
    progress(15, '资源识别完成')
    selection = resolve_media_selection(
        fetch_result,
        output_type=export_request.output_type,
        video_quality=video_quality,
    )
    if dry_run:
        return {
            "platform": fetch_result.platform,
            "normalized_link": normalized_link,
            "title": fetch_result.title,
            "final_url": fetch_result.final_url,
        }

    output_dir = ensure_output_dir(export_request.output_path)
    base_name = sanitize_filename(fetch_result.title)
    download_user_agent = getattr(selected_adapter, "download_user_agent", None)
    download_referer = getattr(selected_adapter, "download_referer", normalized_link)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_video: Path | None = None
        source_audio: Path | None = None

        if selection.video_stream is not None:
            progress(20, '正在下载视频流')
            source_video = download_media(
                selection.video_stream.url,
                temp_path / "source.mp4",
                user_agent=download_user_agent,
                referer=download_referer,
                progress_callback=lambda percent: progress(None if percent is None else 20 + percent * .4, '正在下载视频流'),
            )
        if selection.audio_stream is not None:
            audio_url = selection.audio_stream.url
            if selection.video_stream is None or audio_url != selection.video_stream.url:
                progress(62, '正在下载音频流')
                source_audio = download_media(
                    audio_url,
                    temp_path / "audio.m4a",
                    user_agent=download_user_agent,
                    referer=download_referer,
                    progress_callback=lambda percent: progress(None if percent is None else 62 + percent * .14, '正在下载音频流'),
                )
        from fetchers.exporters import get_output_format_spec
        spec = get_output_format_spec(export_request.output_type)
        final_path = available_output_path(output_dir, base_name, spec.extension)
        partial_path = partial_output_path(final_path, token=os.getenv('STREAMDOCK_TASK_ID'))
        cleanup_partial(partial_path)
        try:
            progress(80, '正在合并并导出媒体')
            generated_path = export_media(
                source_video=source_video,
                source_audio=source_audio,
                output_dir=output_dir,
                base_name=partial_path.name[:-len(f'.{spec.extension}')],
                output_type=export_request.output_type,
            )
            progress(94, '正在校验输出文件')
            validation = validate_media_output(generated_path, expected_kind=spec.kind)
            commit_partial(generated_path, final_path)
            progress(100, '输出文件已通过校验')
        except Exception:
            cleanup_partial(partial_path)
            raise

    return {
        "platform": fetch_result.platform,
        "normalized_link": normalized_link,
        "title": fetch_result.title,
        "capture_strategy": fetch_result.metadata.get("capture_strategy"),
        "media_kind": fetch_result.content_type,
        "final_url": fetch_result.final_url,
        "selected_video_quality": selection.video_stream.quality_label if selection.video_stream else None,
        "output_file": str(final_path),
        "validation": validation,
    }
