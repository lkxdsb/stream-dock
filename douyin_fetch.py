#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

SUPPORTED_OUTPUT_TYPES = {"m4a", "mp3", "mp4"}
URL_PATTERN = re.compile(r"https?://[^\s]+")
INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


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


def extract_first_url(raw_text: str) -> str:
    match = URL_PATTERN.search(raw_text)
    if not match:
        raise ValueError("No URL found in input link text")
    return match.group(0)


def ensure_output_dir(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_filename(name: str, max_length: int = 120) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", name).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "douyin_output"
    return cleaned[:max_length].strip()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    extract_first_url(args.link)
    ensure_output_dir(args.outputPath)
    sanitize_filename("placeholder")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
