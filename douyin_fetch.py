#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from fetchers.adapters.douyin import (
    USER_AGENT,
    capture_media_no_login,
    capture_media_with_chrome_cookies,
    choose_media_capture,
    classify_media_url,
    enrich_capture_if_missing_audio,
    extract_first_url,
)
from fetchers.exporters import (
    OUTPUT_FORMATS,
    export_media,
    get_output_format_spec,
    is_audio_output,
    is_video_output,
    merge_streams_to_mp4,
    validate_output_request,
)
from fetchers.models import ExportRequest
from fetchers.pipeline import run_pipeline
from runtime_checks import ensure_system_proxy_environment

SUPPORTED_OUTPUT_TYPES = set(OUTPUT_FORMATS)


def log(message: str) -> None:
    print(f"[douyin-fetch] {message}", flush=True)


def progress(value: float | None, stage: str) -> None:
    value_text = '' if value is None else str(round(value, 1))
    log(f"progress: {value_text}|{stage}")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract Douyin media from a link using no-login-first strategy."
    )
    parser.add_argument("--link", required=True, help="Douyin share text or direct link")
    parser.add_argument("--outputPath", required=True, help="Output directory path")
    parser.add_argument(
        "--outputType",
        required=True,
        choices=sorted(SUPPORTED_OUTPUT_TYPES),
        help="Output file type: m4a, mp3, or mp4",
    )
    parser.add_argument(
        "--videoQuality",
        required=False,
        help="Preferred video quality label returned by the platform adapter",
    )
    parser.add_argument(
        "--bilibiliCookie",
        required=False,
        help="Optional raw Bilibili cookie header for unlocking higher quality",
    )
    parser.add_argument(
        "--bilibiliCookieFile",
        required=False,
        help="Optional file path containing raw Bilibili cookie header",
    )
    parser.add_argument(
        "--saveAssets",
        action="store_true",
        help="Also save cover image and subtitle sidecar files when available",
    )
    parser.add_argument(
        "--subtitleStrategy",
        choices=["native", "native-asr", "native-asr-ocr", "ocr"],
        default=None,
        help="Subtitle saving strategy: native tracks, ASR fallback, or OCR fallback",
    )
    parser.add_argument(
        "--deferGeneratedSubtitles",
        action="store_true",
        help="Return after the media file is ready and let the app run ASR/OCR in its background subtitle queue",
    )
    return parser


def main() -> int:
    ensure_system_proxy_environment()
    parser = build_parser()
    args = parser.parse_args()
    if args.bilibiliCookie:
        os.environ["BILIBILI_COOKIE"] = args.bilibiliCookie
    if args.bilibiliCookieFile:
        os.environ["BILIBILI_COOKIE_FILE"] = args.bilibiliCookieFile

    result = run_pipeline(
        raw_link=args.link,
        export_request=ExportRequest(output_path=args.outputPath, output_type=args.outputType),
        video_quality=args.videoQuality,
        save_assets=args.saveAssets,
        subtitle_strategy=args.subtitleStrategy,
        defer_generated_subtitles=args.deferGeneratedSubtitles,
        progress_callback=progress,
    )
    log(f"platform: {result['platform']}")
    if result.get('title'):
        log(f"title: {result['title']}")
    log(f"normalized link: {result['normalized_link']}")
    log(f"capture strategy: {result['capture_strategy']}")
    log(f"captured media kind: {result['media_kind']}")
    log(f"final page: {result['final_url']}")
    if result.get('cover_url'):
        log(f"cover url: {result['cover_url']}")
    log(f"subtitle count: {result.get('subtitle_count', 0)}")
    log(f"subtitle pending: {'true' if result.get('subtitle_pending') else 'false'}")
    if result.get("selected_video_quality"):
        log(f"selected video quality: {result['selected_video_quality']}")
    log(f"output file: {result['output_file']}")
    assets = result.get('assets') or {}
    if isinstance(assets, dict):
        if assets.get('cover'):
            log(f"cover file: {assets['cover']}")
        for subtitle in assets.get('subtitles') or []:
            log(f"subtitle file: {subtitle}")
        for detail in assets.get('subtitleDetails') or []:
            if isinstance(detail, dict) and detail.get('path'):
                log(f"subtitle detail: {detail.get('source') or '-'}|{detail.get('quality') or '-'}|{detail.get('path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
