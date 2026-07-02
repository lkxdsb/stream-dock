from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, sync_playwright

URL_PATTERN = re.compile(r"https?://[^\s]+")
AUDIO_EXTENSIONS = (".m4a", ".mp3", ".aac", ".wav", ".flac", ".ogg", ".opus")
VIDEO_EXTENSIONS = (".mp4", ".m3u8", ".webm", ".mov", ".mkv")


def extract_first_url(raw_text: str) -> str:
    match = URL_PATTERN.search(raw_text)
    if not match:
        raise ValueError("No URL found in input link text")
    return match.group(0)


def get_url_host(url: str) -> str:
    return urlparse(url).netloc.lower().split(":", 1)[0]


def host_matches(host: str, supported_hosts: tuple[str, ...]) -> bool:
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in supported_hosts)


def url_matches_supported_host(url: str, supported_hosts: tuple[str, ...]) -> bool:
    return host_matches(get_url_host(url), supported_hosts)


def ensure_supported_host(url: str, supported_hosts: tuple[str, ...], label: str) -> str:
    if not url_matches_supported_host(url, supported_hosts):
        raise ValueError(f"Unsupported {label} host: {url}")
    return url


def extract_balanced_json_after(text: str, anchor: str, opening_char: str) -> str:
    anchor_index = text.find(anchor)
    if anchor_index == -1:
        raise RuntimeError(f"Failed to locate anchor: {anchor}")
    start = text.find(opening_char, anchor_index)
    if start == -1:
        raise RuntimeError(f"Failed to locate JSON start after anchor: {anchor}")

    closing_char = "}" if opening_char == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == opening_char:
            depth += 1
        elif ch == closing_char:
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    raise RuntimeError(f"Failed to locate JSON end after anchor: {anchor}")


def extract_script_json_by_id(html: str, script_id: str) -> str:
    marker = f'id="{script_id}"'
    marker_index = html.find(marker)
    if marker_index == -1:
        raise RuntimeError(f"Failed to locate script id: {script_id}")
    tag_end = html.find(">", marker_index)
    if tag_end == -1:
        raise RuntimeError(f"Failed to locate script tag end for: {script_id}")
    close_tag = html.find("</script>", tag_end)
    if close_tag == -1:
        raise RuntimeError(f"Failed to locate closing script tag for: {script_id}")
    return html[tag_end + 1:close_tag].strip()


def classify_generic_media_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    path = parsed.path.lower()
    lowered = url.lower()
    if any(path.endswith(ext) for ext in AUDIO_EXTENSIONS):
        return "audio"
    if any(path.endswith(ext) for ext in VIDEO_EXTENSIONS):
        return "video"
    if "audio" in lowered and "video" not in lowered:
        return "audio"
    if "video" in lowered or "playurl" in lowered:
        return "video"
    return None


def choose_generic_capture(
    *,
    candidate_video_url: str | None,
    candidate_audio_url: str | None,
    dom_video_sources: list[str],
    final_url: str,
    title: str,
    author: str | None,
    cover_url: str | None,
) -> dict[str, Any]:
    video_url = candidate_video_url
    audio_url = candidate_audio_url
    if video_url is None:
        for source in dom_video_sources:
            if classify_generic_media_url(source) == "video":
                video_url = source
                break

    if not video_url and not audio_url:
        raise RuntimeError("No media URL captured")

    return {
        "final_url": final_url,
        "title": title,
        "author": author,
        "cover_url": cover_url,
        "video_url": video_url,
        "audio_url": audio_url,
    }


def _capture_media_from_context(context: BrowserContext, link: str, wait_ms: int = 10_000) -> dict[str, Any]:
    candidate_video_url: str | None = None
    candidate_audio_url: str | None = None
    page = context.new_page()

    def on_request(req: Any) -> None:
        nonlocal candidate_video_url, candidate_audio_url
        media_kind = classify_generic_media_url(req.url)
        if media_kind == "video":
            candidate_video_url = req.url
        elif media_kind == "audio":
            candidate_audio_url = req.url

    page.on("request", on_request)
    page.goto(link, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(wait_ms)

    page_state = page.evaluate(
        """() => ({
            title: document.title,
            author: document.querySelector('meta[name="author"]')?.content || null,
            cover: document.querySelector('meta[property="og:image"]')?.content || document.querySelector('video')?.poster || null,
            videoSources: [...document.querySelectorAll('video')].map(v => v.currentSrc || v.src).filter(Boolean),
        })"""
    )

    return choose_generic_capture(
        candidate_video_url=candidate_video_url,
        candidate_audio_url=candidate_audio_url,
        dom_video_sources=page_state.get("videoSources") or [],
        final_url=page.url,
        title=page_state.get("title") or page.title(),
        author=page_state.get("author"),
        cover_url=page_state.get("cover"),
    )


def capture_media_with_browser(link: str, *, user_agent: str, wait_ms: int = 10_000) -> dict[str, Any]:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            user_agent=user_agent,
        )
        try:
            return _capture_media_from_context(context, link, wait_ms=wait_ms)
        finally:
            browser.close()
