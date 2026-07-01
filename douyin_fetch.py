#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import browser_cookie3
import requests
from playwright.sync_api import BrowserContext, sync_playwright

SUPPORTED_OUTPUT_TYPES = {"m4a", "mp3", "mp4"}
URL_PATTERN = re.compile(r"https?://[^\s]+")
INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


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


def classify_media_url(url: str | None) -> str | None:
    if not url:
        return None
    normalized = url.strip()
    if not normalized or normalized.startswith("blob:"):
        return None
    lowered = normalized.lower()
    if "media-audio-und-mp4a" in lowered:
        return "audio"
    if "media-video-" in lowered:
        return "video"
    if lowered.endswith(".mp4"):
        return "video"
    return None


def choose_media_capture(
    *,
    candidate_video_url: str | None,
    candidate_audio_url: str | None,
    dom_video_sources: list[str],
    final_url: str,
    title: str,
) -> dict[str, Any]:
    video_url = candidate_video_url
    audio_url = candidate_audio_url

    if video_url is None:
        for src in dom_video_sources:
            if classify_media_url(src) == "video":
                video_url = src
                break

    if video_url:
        return {
            "final_url": final_url,
            "title": title,
            "media_url": video_url,
            "media_kind": "video",
            "video_url": video_url,
            "audio_url": audio_url,
        }
    if audio_url:
        return {
            "final_url": final_url,
            "title": title,
            "media_url": audio_url,
            "media_kind": "audio",
            "video_url": None,
            "audio_url": audio_url,
        }
    raise RuntimeError("No media URL captured")


def validate_output_request(*, media_kind: str, output_type: str) -> None:
    if output_type == "mp4" and media_kind != "video":
        raise ValueError("Only audio stream found; cannot export a real mp4 video")


def _capture_media_from_context(context: BrowserContext, link: str, wait_ms: int = 10_000) -> dict[str, Any]:
    candidate_video_url: str | None = None
    candidate_audio_url: str | None = None
    page = context.new_page()

    def on_request(req: Any) -> None:
        nonlocal candidate_video_url, candidate_audio_url
        url = req.url
        media_kind = classify_media_url(url)
        if media_kind == "video":
            candidate_video_url = url
        elif media_kind == "audio":
            candidate_audio_url = url

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
    dom_video_sources = [item.get("src") for item in video_sources if item.get("src")]
    return choose_media_capture(
        candidate_video_url=candidate_video_url,
        candidate_audio_url=candidate_audio_url,
        dom_video_sources=dom_video_sources,
        final_url=final_url,
        title=title,
    )


def capture_media_no_login(link: str, wait_ms: int = 10_000) -> dict[str, Any]:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            user_agent=USER_AGENT,
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
            user_agent=USER_AGENT,
        )
        context.add_cookies(cookies)
        try:
            return _capture_media_from_context(context, link, wait_ms=wait_ms)
        finally:
            browser.close()


def download_media(url: str, destination: Path) -> Path:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.douyin.com/",
    }
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run(
        args,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def merge_streams_to_mp4(video_file: Path, audio_file: Path, final_path: Path) -> Path:
    run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", str(video_file),
            "-i", str(audio_file),
            "-c:v", "copy",
            "-c:a", "copy",
            str(final_path),
        ]
    )
    return final_path


def materialize_output(
    source_file: Path,
    output_dir: Path,
    base_name: str,
    output_type: str,
    *,
    audio_file: Path | None = None,
) -> Path:
    final_path = output_dir / f"{base_name}.{output_type}"
    if output_type == "mp4":
        if audio_file is not None:
            return merge_streams_to_mp4(source_file, audio_file, final_path)
        shutil.copyfile(source_file, final_path)
        return final_path
    if output_type == "m4a":
        run_ffmpeg(["ffmpeg", "-y", "-i", str(audio_file or source_file), "-vn", "-c:a", "copy", str(final_path)])
        return final_path
    if output_type == "mp3":
        run_ffmpeg(["ffmpeg", "-y", "-i", str(audio_file or source_file), "-vn", "-acodec", "libmp3lame", "-q:a", "2", str(final_path)])
        return final_path
    raise ValueError(f"Unsupported output type: {output_type}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    normalized_link = extract_first_url(args.link)
    output_dir = ensure_output_dir(args.outputPath)
    log(f"normalized link: {normalized_link}")

    try:
        capture = capture_media_no_login(normalized_link)
        strategy = "no-login"
    except Exception as no_login_error:
        try:
            capture = capture_media_with_chrome_cookies(normalized_link)
            strategy = "chrome-cookies"
        except Exception as cookie_error:
            raise RuntimeError(
                "Capture failed in both strategies: "
                f"no-login=({no_login_error}); chrome-cookies=({cookie_error})"
            )

    base_name = sanitize_filename(capture["title"].replace(" - 抖音", "").strip())
    validate_output_request(media_kind=capture["media_kind"], output_type=args.outputType)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_source = Path(temp_dir) / "source.mp4"
        temp_audio: Path | None = None
        download_media(capture["media_url"], temp_source)
        if capture.get("audio_url") and capture.get("audio_url") != capture["media_url"]:
            temp_audio = Path(temp_dir) / "audio.m4a"
            download_media(capture["audio_url"], temp_audio)
        final_path = materialize_output(
            temp_source,
            output_dir,
            base_name,
            args.outputType,
            audio_file=temp_audio,
        )

    log(f"capture strategy: {strategy}")
    log(f"captured media kind: {capture['media_kind']}")
    log(f"final page: {capture['final_url']}")
    log(f"output file: {final_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
