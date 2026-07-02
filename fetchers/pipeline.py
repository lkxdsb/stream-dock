from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.downloader import download_media
from fetchers.exporters import export_media, validate_output_request
from fetchers.models import ExportRequest

INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


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
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_pipeline(
    *,
    raw_link: str,
    export_request: ExportRequest,
    adapter: BasePlatformAdapter | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    selected_adapter = adapter or detect_platform_adapter(raw_link)
    normalized_link = selected_adapter.normalize_link(raw_link)
    fetch_result = selected_adapter.fetch_media(normalized_link)
    validate_output_request(
        media_kind=fetch_result.content_type,
        output_type=export_request.output_type,
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

        if fetch_result.preferred_video is not None:
            source_video = download_media(
                fetch_result.preferred_video.url,
                temp_path / "source.mp4",
                user_agent=download_user_agent,
                referer=download_referer,
            )
        if fetch_result.preferred_audio is not None:
            audio_url = fetch_result.preferred_audio.url
            if fetch_result.preferred_video is None or audio_url != fetch_result.preferred_video.url:
                source_audio = download_media(
                    audio_url,
                    temp_path / "audio.m4a",
                    user_agent=download_user_agent,
                    referer=download_referer,
                )
        final_path = export_media(
            source_video=source_video,
            source_audio=source_audio,
            output_dir=output_dir,
            base_name=base_name,
            output_type=export_request.output_type,
        )

    return {
        "platform": fetch_result.platform,
        "normalized_link": normalized_link,
        "title": fetch_result.title,
        "capture_strategy": fetch_result.metadata.get("capture_strategy"),
        "media_kind": fetch_result.content_type,
        "final_url": fetch_result.final_url,
        "output_file": str(final_path),
    }
