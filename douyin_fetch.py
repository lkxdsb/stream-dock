#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    print(f"[douyin-fetch] {message}")

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
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    result = run_pipeline(
        raw_link=args.link,
        export_request=ExportRequest(output_path=args.outputPath, output_type=args.outputType),
    )
    log(f"platform: {result['platform']}")
    log(f"normalized link: {result['normalized_link']}")
    log(f"capture strategy: {result['capture_strategy']}")
    log(f"captured media kind: {result['media_kind']}")
    log(f"final page: {result['final_url']}")
    log(f"output file: {result['output_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
