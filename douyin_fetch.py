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
    return parser


def main() -> int:
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
        progress_callback=progress,
    )
    log(f"platform: {result['platform']}")
    log(f"normalized link: {result['normalized_link']}")
    log(f"capture strategy: {result['capture_strategy']}")
    log(f"captured media kind: {result['media_kind']}")
    log(f"final page: {result['final_url']}")
    if result.get("selected_video_quality"):
        log(f"selected video quality: {result['selected_video_quality']}")
    log(f"output file: {result['output_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
