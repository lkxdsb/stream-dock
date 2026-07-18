from __future__ import annotations

import re
import os
import tempfile
from urllib.parse import urlparse
from pathlib import Path
from typing import Callable

import requests

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.downloader import download_media
from fetchers.exporters import export_media, is_video_output, validate_output_request
from fetchers.models import ExportRequest, MediaFetchResult, MediaStream, ResolvedMediaSelection, SubtitleTrack
from fetchers.subtitle_asr import asr_available, generate_asr_subtitle_file
from fetchers.subtitle_ocr import OcrSubtitleCue, cues_to_srt, generate_ocr_subtitle_file, ocr_available
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



def infer_asset_extension(url: str, content_type: str | None, fallback: str) -> str:
    content = (content_type or '').split(';', 1)[0].lower().strip()
    content_map = {
        'image/jpeg': 'jpg',
        'image/jpg': 'jpg',
        'image/png': 'png',
        'image/webp': 'webp',
        'image/gif': 'gif',
        'text/vtt': 'vtt',
        'application/json': 'json',
        'text/plain': 'txt',
    }
    if content in content_map:
        return content_map[content]
    suffix = Path(urlparse(url).path).suffix.lower().lstrip('.')
    if suffix in {'jpg', 'jpeg', 'png', 'webp', 'gif', 'vtt', 'srt', 'json', 'ass', 'ssa', 'txt'}:
        return 'jpg' if suffix == 'jpeg' else suffix
    return fallback.lstrip('.')


def safe_asset_label(value: str | None, fallback: str) -> str:
    raw = str(value or '').strip() or fallback
    return sanitize_filename(raw, max_length=48).replace(' ', '_')


def download_sidecar_asset(
    url: str,
    *,
    output_dir: Path,
    base_name: str,
    label: str,
    user_agent: str,
    referer: str,
    fallback_extension: str,
) -> Path:
    headers = {'User-Agent': user_agent, 'Referer': referer}
    response = requests.get(url, headers=headers, timeout=60, stream=True)
    try:
        response.raise_for_status()
        extension = infer_asset_extension(url, response.headers.get('content-type'), fallback_extension)
        final_path = available_output_path(output_dir, f'{base_name}_{safe_asset_label(label, "asset")}', extension)
        with final_path.open('wb') as output:
            for chunk in response.iter_content(chunk_size=512 * 1024):
                if chunk:
                    output.write(chunk)
        return final_path
    finally:
        response.close()




def _subtitle_json_to_srt(payload: object) -> str | None:
    if isinstance(payload, dict):
        entries = payload.get('body') or payload.get('subtitles') or payload.get('segments') or []
    elif isinstance(payload, list):
        entries = payload
    else:
        entries = []
    cues: list[OcrSubtitleCue] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        start = item.get('from', item.get('start'))
        end = item.get('to', item.get('end'))
        text = item.get('content', item.get('text', item.get('line')))
        try:
            start_value = float(start)
            end_value = float(end)
        except (TypeError, ValueError):
            continue
        body = str(text or '').strip()
        if body and end_value > start_value:
            cues.append(OcrSubtitleCue(start=start_value, end=end_value, text=body))
    if not cues:
        return None
    return cues_to_srt(cues)


def download_subtitle_asset(
    track: SubtitleTrack,
    *,
    output_dir: Path,
    base_name: str,
    label: str,
    user_agent: str,
    referer: str,
) -> tuple[Path, str]:
    headers = {'User-Agent': user_agent, 'Referer': referer}
    response = requests.get(track.url, headers=headers, timeout=60)
    try:
        response.raise_for_status()
        content_type = response.headers.get('content-type')
        fmt = subtitle_extension(track)
        if fmt == 'json':
            try:
                srt_text = _subtitle_json_to_srt(response.json())
            except ValueError:
                srt_text = None
            if srt_text:
                final_path = available_output_path(output_dir, f'{base_name}_{safe_asset_label(label, "subtitle")}', 'srt')
                final_path.write_text(srt_text, encoding='utf-8')
                return final_path, 'srt'
        extension = infer_asset_extension(track.url, content_type, fmt)
        final_path = available_output_path(output_dir, f'{base_name}_{safe_asset_label(label, "subtitle")}', extension)
        final_path.write_bytes(response.content)
        return final_path, extension
    finally:
        response.close()

def subtitle_extension(track: SubtitleTrack) -> str:
    fmt = str(track.format or '').lower().strip().lstrip('.')
    if fmt in {'vtt', 'srt', 'json', 'ass', 'ssa', 'txt'}:
        return fmt
    return 'vtt' if 'vtt' in str(track.url).lower() else 'json'



def generate_metadata_subtitle_file(fetch_result: MediaFetchResult, output_path: Path, *, duration_seconds: float | None = None) -> Path | None:
    candidates = [
        str((fetch_result.metadata or {}).get('description') or '').strip(),
        str((fetch_result.metadata or {}).get('caption') or '').strip(),
        str(fetch_result.title or '').strip(),
    ]
    text = next((item for item in candidates if item and not re.fullmatch(r'(?:[^_]+_)?(?:video|\d+)', item, flags=re.I)), '')
    if not text and fetch_result.platform == 'tiktok':
        author_match = re.search(r'/@([^/]+)/video/', fetch_result.source_url or fetch_result.final_url or '')
        video_match = re.search(r'/video/(\d+)', fetch_result.source_url or fetch_result.final_url or '')
        if author_match or video_match:
            text = 'TikTok 视频：' + ' '.join(part for part in [
                f"作者 @{author_match.group(1)}" if author_match else '',
                f"视频 {video_match.group(1)}" if video_match else '',
                '平台未提供字幕轨，且未检测到可识别语音或画面字幕。',
            ] if part)
    if not text:
        return None
    text = re.sub(r'\s+', ' ', text).strip()[:500]
    end = max(2.0, min(float(duration_seconds or 6.0), 12.0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(cues_to_srt([OcrSubtitleCue(start=0.0, end=end, text=text)]), encoding='utf-8')
    return output_path if output_path.exists() and output_path.stat().st_size > 0 else None

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
    save_assets: bool = False,
    subtitle_strategy: str | None = None,
    defer_generated_subtitles: bool = False,
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
    download_user_agent = getattr(selected_adapter, "download_user_agent", None) or "Mozilla/5.0"
    download_referer = getattr(selected_adapter, "download_referer", normalized_link)

    saved_assets: dict[str, object] = {"cover": None, "subtitles": [], "subtitleDetails": []}
    subtitle_pending = False
    selected_subtitle_strategy = (subtitle_strategy or os.getenv("STREAMDOCK_SUBTITLE_STRATEGY") or "native-asr-ocr").strip().lower()
    if selected_subtitle_strategy not in {"native", "native-asr", "native-asr-ocr", "ocr"}:
        selected_subtitle_strategy = "native-asr-ocr"

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
            progress(92, '正在校验输出文件')
            validation = validate_media_output(generated_path, expected_kind=spec.kind)
            commit_partial(generated_path, final_path)
            if save_assets:
                progress(96, '正在保存封面和字幕')
                if fetch_result.cover_url:
                    try:
                        saved_assets["cover"] = str(download_sidecar_asset(
                            fetch_result.cover_url,
                            output_dir=output_dir,
                            base_name=base_name,
                            label="cover",
                            user_agent=download_user_agent,
                            referer=download_referer,
                            fallback_extension="jpg",
                        ))
                    except Exception:
                        saved_assets["cover"] = None
                subtitles: list[str] = []
                subtitle_details: list[dict[str, object]] = []
                if selected_subtitle_strategy in {"native", "native-asr", "native-asr-ocr"}:
                    for index, track in enumerate(fetch_result.subtitle_tracks[:8], start=1):
                        try:
                            lang = safe_asset_label(track.language or track.label, f"{index}")
                            subtitle_path, saved_format = download_subtitle_asset(
                                track,
                                output_dir=output_dir,
                                base_name=base_name,
                                label=f"subtitle_{lang}",
                                user_agent=download_user_agent,
                                referer=download_referer,
                            )
                            subtitles.append(str(subtitle_path))
                            subtitle_details.append({
                                "path": str(subtitle_path),
                                "source": track.source or "native",
                                "quality": "high",
                                "language": track.language,
                                "label": track.label,
                                "format": saved_format,
                            })
                        except Exception:
                            continue
                needs_generated_subtitles = (
                    not subtitles
                    and spec.kind == 'video'
                    and selected_subtitle_strategy in {"native-asr", "native-asr-ocr", "ocr"}
                )
                if needs_generated_subtitles and defer_generated_subtitles:
                    # The media file is already committed and validated at this point.
                    # Queued UI tasks can therefore return the playable file immediately
                    # and let the dedicated subtitle worker perform ASR/OCR afterwards.
                    subtitle_pending = True
                if not subtitle_pending and not subtitles and spec.kind == 'video' and selected_subtitle_strategy in {"native-asr", "native-asr-ocr"} and asr_available():
                    try:
                        progress(97, '视频已保存，正在生成语音字幕（可能需要几分钟）')
                        asr_path = available_output_path(output_dir, f'{base_name}_subtitle_asr', 'srt')
                        generated_subtitle = generate_asr_subtitle_file(final_path, asr_path)
                        if generated_subtitle:
                            subtitles.append(str(generated_subtitle))
                            subtitle_details.append({
                                "path": str(generated_subtitle),
                                "source": "speech-asr",
                                "quality": "medium",
                                "language": os.getenv('STREAMDOCK_SUBTITLE_ASR_LANG', 'zh'),
                                "label": "语音识别字幕",
                            })
                    except Exception:
                        pass
                if not subtitle_pending and not subtitles and spec.kind == 'video' and selected_subtitle_strategy in {"native-asr-ocr", "ocr"} and ocr_available():
                    try:
                        progress(98, '语音字幕未生成，正在尝试识别画面字幕')
                        ocr_path = available_output_path(output_dir, f'{base_name}_subtitle_ocr', 'srt')
                        generated_subtitle = generate_ocr_subtitle_file(final_path, ocr_path)
                        if generated_subtitle:
                            subtitles.append(str(generated_subtitle))
                            subtitle_details.append({
                                "path": str(generated_subtitle),
                                "source": "screen-ocr",
                                "quality": "low",
                                "language": os.getenv('STREAMDOCK_SUBTITLE_OCR_LANG', 'chi_sim+eng'),
                                "label": "画面 OCR 字幕（可能不准确）",
                            })
                    except Exception:
                        pass
                if not subtitle_pending and not subtitles and spec.kind == 'video' and selected_subtitle_strategy == "native-asr-ocr":
                    try:
                        text_path = available_output_path(output_dir, f'{base_name}_subtitle_text', 'srt')
                        duration = float((validation or {}).get('durationSeconds') or 0)
                        generated_subtitle = generate_metadata_subtitle_file(fetch_result, text_path, duration_seconds=duration)
                        if generated_subtitle:
                            subtitles.append(str(generated_subtitle))
                            subtitle_details.append({
                                "path": str(generated_subtitle),
                                "source": "metadata-text",
                                "quality": "low",
                                "language": None,
                                "label": "平台文案兜底（无可识别语音/字幕轨）",
                            })
                    except Exception:
                        pass
                saved_assets["subtitles"] = subtitles
                saved_assets["subtitleDetails"] = subtitle_details
            progress(100, '输出文件已通过校验')
        except Exception:
            cleanup_partial(partial_path)
            raise

    saved_subtitle_count = len(saved_assets.get("subtitles") or [])
    return {
        "platform": fetch_result.platform,
        "normalized_link": normalized_link,
        "title": fetch_result.title,
        "capture_strategy": fetch_result.metadata.get("capture_strategy"),
        "media_kind": fetch_result.content_type,
        "final_url": fetch_result.final_url,
        "cover_url": fetch_result.cover_url,
        "author": fetch_result.author,
        "subtitle_count": max(len(fetch_result.subtitle_tracks), saved_subtitle_count),
        "subtitle_tracks": [track.__dict__ for track in fetch_result.subtitle_tracks],
        "subtitle_strategy": selected_subtitle_strategy,
        "subtitle_pending": subtitle_pending,
        "selected_video_quality": selection.video_stream.quality_label if selection.video_stream else None,
        "output_file": str(final_path),
        "assets": saved_assets,
        "validation": validation,
    }
