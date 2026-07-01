#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import browser_cookie3
from playwright.sync_api import BrowserContext, sync_playwright

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


def _capture_media_from_context(context: BrowserContext, link: str, wait_ms: int = 10_000) -> dict[str, Any]:
    media_url: str | None = None
    media_kind: str | None = None
    page = context.new_page()

    def on_request(req: Any) -> None:
        nonlocal media_url, media_kind
        url = req.url
        if media_url is None and "media-audio-und-mp4a" in url:
            media_url = url
            media_kind = "audio"

    page.on("request", on_request)
    page.goto(link, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(wait_ms)

    video_sources = page.evaluate(
        """() => [...document.querySelectorAll('video')].map(v => ({
            src: v.currentSrc || v.src,
            paused: v.paused,
            readyState: v.readyState,
            duration: v.duration,
            currentTime: v.currentTime,
        }))"""
    )
    final_url = page.url
    title = page.title()

    if media_url is None:
        for item in video_sources:
            src = item.get("src")
            if src:
                media_url = src
                media_kind = "video"
                break

    if media_url is None or media_kind is None:
        raise RuntimeError("No media URL captured")

    return {
        "final_url": final_url,
        "title": title,
        "media_url": media_url,
        "media_kind": media_kind,
    }


def capture_media_no_login(link: str, wait_ms: int = 10_000) -> dict[str, Any]:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        try:
            return _capture_media_from_context(context, link, wait_ms=wait_ms)
        finally:
            browser.close()


def load_chrome_cookies_for_douyin() -> list[dict[str, Any]]:
    cookie_jar = browser_cookie3.chrome(domain_name="douyin.com")
    cookies: list[dict[str, Any]] = []
    for cookie in cookie_jar:
        if "douyin.com" not in cookie.domain:
            continue
        cookies.append(
            {
                "name": cookie.name,
                "value": str(cookie.value or ""),
                "domain": cookie.domain,
                "path": cookie.path or "/",
                "expires": float(cookie.expires) if cookie.expires else -1,
                "httpOnly": bool(
                    cookie.has_nonstandard_attr("HttpOnly")
                    or cookie._rest.get("HttpOnly") is not None
                ),
                "secure": bool(cookie.secure),
                "sameSite": "Lax",
            }
        )
    return cookies


def capture_media_with_chrome_cookies(link: str, wait_ms: int = 10_000) -> dict[str, Any]:
    cookies = load_chrome_cookies_for_douyin()
    if not cookies:
        raise RuntimeError("No Douyin cookies found in Chrome")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        context.add_cookies(cookies)
        try:
            return _capture_media_from_context(context, link, wait_ms=wait_ms)
        finally:
            browser.close()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    extract_first_url(args.link)
    ensure_output_dir(args.outputPath)
    sanitize_filename("placeholder")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
