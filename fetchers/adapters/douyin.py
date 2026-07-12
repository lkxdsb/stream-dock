from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import browser_cookie3
from playwright.sync_api import BrowserContext, sync_playwright

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.common import host_matches
from fetchers.models import MediaFetchResult, MediaStream

URL_PATTERN = re.compile(r"https?://[^\s]+")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


def extract_first_url(raw_text: str) -> str:
    match = URL_PATTERN.search(raw_text)
    if not match:
        raise ValueError("No URL found in input link text")
    return match.group(0)


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
    aweme_detail: dict[str, Any] | None = None,
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
            "aweme_detail": aweme_detail,
        }
    if audio_url:
        return {
            "final_url": final_url,
            "title": title,
            "media_url": audio_url,
            "media_kind": "audio",
            "video_url": None,
            "audio_url": audio_url,
            "aweme_detail": aweme_detail,
        }
    raise RuntimeError("No media URL captured")


def enrich_capture_if_missing_audio(
    capture: dict[str, Any],
    *,
    link: str,
    strategy: str,
    no_login_capturer: Any,
    cookie_capturer: Any,
) -> tuple[dict[str, Any], str]:
    if capture.get("media_kind") != "video" or capture.get("audio_url"):
        return capture, strategy

    retry_candidates: list[tuple[str, Any]] = []
    if strategy == "no-login":
        retry_candidates.append(("no-login", no_login_capturer))
        if cookie_capturer is not None:
            retry_candidates.append(("chrome-cookies", cookie_capturer))
    elif cookie_capturer is not None:
        retry_candidates.append(("chrome-cookies", cookie_capturer))

    for retry_strategy, capturer in retry_candidates:
        try:
            refreshed_capture = capturer(link, wait_ms=15_000)
        except Exception:
            continue
        if refreshed_capture.get("audio_url"):
            return refreshed_capture, retry_strategy
    return capture, strategy


def _capture_media_from_context(context: BrowserContext, link: str, wait_ms: int = 10_000) -> dict[str, Any]:
    candidate_video_url: str | None = None
    candidate_audio_url: str | None = None
    aweme_detail: dict[str, Any] | None = None
    page = context.new_page()

    def on_request(req: Any) -> None:
        nonlocal candidate_video_url, candidate_audio_url
        url = req.url
        media_kind = classify_media_url(url)
        if media_kind == "video":
            candidate_video_url = url
        elif media_kind == "audio":
            candidate_audio_url = url

    def on_response(resp: Any) -> None:
        nonlocal aweme_detail
        if "/aweme/v1/web/aweme/detail/" not in resp.url:
            return
        try:
            payload = resp.json()
        except Exception:
            return
        detail = payload.get("aweme_detail")
        if isinstance(detail, dict):
            aweme_detail = detail

    page.on("request", on_request)
    page.on("response", on_response)
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
        aweme_detail=aweme_detail,
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


class DouyinAdapter(BasePlatformAdapter):
    platform_name = "douyin"
    supported_hosts = ("v.douyin.com", "www.douyin.com", "douyin.com")
    download_user_agent = USER_AGENT
    download_referer = "https://www.douyin.com/"

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        host = urlparse(candidate).netloc.lower().split(":", 1)[0]
        return host_matches(host, self.supported_hosts)

    def normalize_link(self, raw_link: str) -> str:
        return extract_first_url(raw_link)

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
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

        capture, strategy = enrich_capture_if_missing_audio(
            capture,
            link=normalized_link,
            strategy=strategy,
            no_login_capturer=capture_media_no_login,
            cookie_capturer=capture_media_with_chrome_cookies,
        )

        preferred_video = None
        preferred_audio = None
        video_streams = self._build_video_streams(capture.get("aweme_detail"))
        audio_streams: list[MediaStream] = []

        if video_streams:
            preferred_video = max(
                video_streams,
                key=lambda s: ((s.height or 0), (s.width or 0), (s.bitrate or 0)),
            )
        elif capture.get("video_url"):
            preferred_video = MediaStream(url=capture["video_url"], stream_type="video", container="mp4")
            video_streams.append(preferred_video)
        if capture.get("audio_url"):
            preferred_audio = MediaStream(
                url=capture["audio_url"],
                stream_type="audio",
                container="m4a",
            )
            audio_streams.append(preferred_audio)

        title = capture["title"].replace(" - 抖音", "").strip()
        return MediaFetchResult(
            platform=self.platform_name,
            content_type=capture["media_kind"],
            title=title,
            source_url=normalized_link,
            final_url=capture["final_url"],
            cover_url=None,
            author=None,
            video_streams=video_streams,
            audio_streams=audio_streams,
            preferred_video=preferred_video,
            preferred_audio=preferred_audio,
            metadata={
                "capture_strategy": strategy,
                "media_kind": capture["media_kind"],
            },
        )

    def _build_video_streams(self, aweme_detail: dict[str, Any] | None) -> list[MediaStream]:
        if not aweme_detail:
            return []
        video = aweme_detail.get("video") or {}
        raw_streams = video.get("bit_rate") or []
        streams: list[MediaStream] = []
        seen_urls: set[str] = set()
        for item in raw_streams:
            play_addr = item.get("play_addr") or {}
            url_list = play_addr.get("url_list") or []
            stream_url = next((url for url in url_list if url), None)
            if not stream_url or stream_url in seen_urls:
                continue
            codec = "h265" if item.get("is_h265") else ("bytevc1" if item.get("is_bytevc1") else "h264")
            streams.append(
                MediaStream(
                    url=stream_url,
                    stream_type="video",
                    container=item.get("format") or "mp4",
                    codec=codec,
                    width=play_addr.get("width"),
                    height=play_addr.get("height"),
                    bitrate=item.get("bit_rate"),
                    filesize=play_addr.get("data_size"),
                    quality_label=item.get("gear_name"),
                )
            )
            seen_urls.add(stream_url)
        return streams
