from __future__ import annotations

import contextvars
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import browser_cookie3
import requests

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.common import host_matches
from fetchers.models import MediaFetchResult, MediaStream, SubtitleTrack

URL_PATTERN = re.compile(r"https?://[^\s]+")
INITIAL_STATE_PATTERN = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", re.S)
VIDEO_PATH_PATTERN = re.compile(r"https?://(?:www\.)?bilibili\.com/video/")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
PLAYURL_ENDPOINT = "https://api.bilibili.com/x/player/playurl"
PLAYER_V2_ENDPOINT = "https://api.bilibili.com/x/player/v2"

MANUAL_COOKIE_ENV = "BILIBILI_COOKIE"
MANUAL_COOKIE_FILE_ENV = "BILIBILI_COOKIE_FILE"
MANUAL_COOKIE_OVERRIDE = contextvars.ContextVar("bilibili_manual_cookie_override", default=None)
MANUAL_COOKIE_FILE_OVERRIDE = contextvars.ContextVar("bilibili_manual_cookie_file_override", default=None)


def parse_cookie_header(raw_cookie: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in raw_cookie.split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            cookies[key] = value
    return cookies


def load_manual_cookies_for_bilibili() -> dict[str, str] | None:
    override_cookie = MANUAL_COOKIE_OVERRIDE.get()
    if isinstance(override_cookie, str) and override_cookie.strip():
        parsed = parse_cookie_header(override_cookie.strip())
        if parsed:
            return parsed

    override_cookie_file = MANUAL_COOKIE_FILE_OVERRIDE.get()
    if isinstance(override_cookie_file, str) and override_cookie_file.strip():
        try:
            content = open(override_cookie_file.strip(), "r", encoding="utf-8").read().strip()
        except OSError:
            return None
        parsed = parse_cookie_header(content)
        if parsed:
            return parsed

    raw_cookie = os.environ.get(MANUAL_COOKIE_ENV, "").strip()
    if raw_cookie:
        parsed = parse_cookie_header(raw_cookie)
        if parsed:
            return parsed

    cookie_file = os.environ.get(MANUAL_COOKIE_FILE_ENV, "").strip()
    if cookie_file:
        try:
            content = open(cookie_file, "r", encoding="utf-8").read().strip()
        except OSError:
            return None
        parsed = parse_cookie_header(content)
        if parsed:
            return parsed
    return None


def set_manual_cookie_overrides(raw_cookie: str | None = None, cookie_file: str | None = None) -> tuple[contextvars.Token, contextvars.Token]:
    return (
        MANUAL_COOKIE_OVERRIDE.set(raw_cookie),
        MANUAL_COOKIE_FILE_OVERRIDE.set(cookie_file),
    )


def reset_manual_cookie_overrides(tokens: tuple[contextvars.Token, contextvars.Token]) -> None:
    cookie_token, cookie_file_token = tokens
    MANUAL_COOKIE_OVERRIDE.reset(cookie_token)
    MANUAL_COOKIE_FILE_OVERRIDE.reset(cookie_file_token)


def try_load_browser_cookie(loader) -> Any | None:
    try:
        cookies = loader(domain_name="bilibili.com")
    except Exception:
        return None
    if cookies is None:
        return None
    try:
        if len(list(cookies)) == 0:
            return None
    except Exception:
        pass
    return cookies


def load_bilibili_cookies() -> tuple[Any | None, str | None]:
    manual_cookies = load_manual_cookies_for_bilibili()
    if manual_cookies:
        return manual_cookies, "manual"

    browser_loaders = [
        ("chrome", browser_cookie3.chrome),
        ("edge", browser_cookie3.edge),
        ("brave", browser_cookie3.brave),
    ]
    for source, loader in browser_loaders:
        cookies = try_load_browser_cookie(loader)
        if cookies:
            return cookies, source
    return None, None


def extract_first_url(raw_text: str) -> str:
    match = URL_PATTERN.search(raw_text)
    if not match:
        raise ValueError("No URL found in input link text")
    return match.group(0)


def codec_rank(codec: str | None) -> int:
    if not codec:
        return 0
    lowered = codec.lower()
    if lowered.startswith("avc1"):
        return 3
    if lowered.startswith("hev1") or lowered.startswith("hvc1"):
        return 2
    if lowered.startswith("av01"):
        return 1
    return 0


class BilibiliAdapter(BasePlatformAdapter):
    platform_name = "bilibili"
    supported_hosts = ("bilibili.com", "b23.tv")
    download_user_agent = USER_AGENT

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        parsed = urlparse(candidate)
        host = parsed.netloc.lower().split(":", 1)[0]
        if host_matches(host, ("b23.tv",)):
            return True
        if not host_matches(host, ("bilibili.com",)):
            return False
        return parsed.path.startswith("/video/")

    def normalize_link(self, raw_link: str) -> str:
        candidate = extract_first_url(raw_link).strip()
        parsed = urlparse(candidate)
        host = parsed.netloc.lower().split(":", 1)[0]
        if host_matches(host, ("b23.tv",)):
            response = requests.get(
                candidate,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            response.raise_for_status()
            resolved = response.url
            if not VIDEO_PATH_PATTERN.search(resolved):
                raise ValueError(f"Unsupported Bilibili short link target: {resolved}")
            return resolved
        if not (host_matches(host, ("bilibili.com",)) and parsed.path.startswith("/video/")):
            raise ValueError(f"Unsupported Bilibili page: {candidate}")
        return candidate

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        cookies, cookie_source = load_bilibili_cookies()
        page_response = requests.get(
            normalized_link,
            headers={"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"},
            cookies=cookies,
            timeout=30,
        )
        page_response.raise_for_status()
        final_url = page_response.url
        initial_state = self._extract_initial_state(page_response.text)
        video_data = initial_state.get("videoData") or {}

        bvid = video_data.get("bvid")
        cid = video_data.get("cid")
        if cid is None:
            pages = video_data.get("pages") or []
            if pages:
                cid = pages[0].get("cid")
        if not bvid or cid is None:
            raise RuntimeError("Failed to extract Bilibili bvid/cid from page state")

        playurl_payload = self._fetch_playurl(bvid=bvid, cid=cid, referer=final_url, cookies=cookies)
        dash = (playurl_payload.get("dash") or {})
        video_streams = self._build_video_streams(
            dash.get("video") or [],
            playurl_payload.get("accept_quality") or [],
            playurl_payload.get("accept_description") or [],
        )
        audio_streams = self._build_audio_streams(dash.get("audio") or [])
        stream_layout = "dash"
        if not video_streams:
            durl_items = playurl_payload.get("durl") or []
            self._reject_truncated_preview(
                durl_items=durl_items,
                expected_duration_ms=playurl_payload.get("timelength"),
                is_upower_exclusive=bool(video_data.get("is_upower_exclusive")),
            )
            video_streams = self._build_progressive_streams(
                durl_items,
                quality=playurl_payload.get("quality"),
                support_formats=playurl_payload.get("support_formats") or [],
                container=playurl_payload.get("format"),
            )
            stream_layout = "progressive"
        subtitle_tracks = self._fetch_subtitle_tracks(bvid=bvid, cid=cid, referer=final_url, cookies=cookies)
        if not video_streams:
            raise RuntimeError("No Bilibili video streams found in playurl response")
        if stream_layout == "dash" and not audio_streams:
            raise RuntimeError("No Bilibili audio streams found in playurl response")

        preferred_video = max(
            video_streams,
            key=lambda stream: (
                self._quality_value(stream),
                stream.width or 0,
                stream.height or 0,
                codec_rank(stream.codec),
                stream.bitrate or 0,
            ),
        )
        preferred_audio = (
            max(audio_streams, key=lambda stream: (stream.bitrate or 0, stream.quality_label or ""))
            if audio_streams
            else None
        )

        return MediaFetchResult(
            platform=self.platform_name,
            content_type="video",
            title=video_data.get("title") or "bilibili_video",
            source_url=normalized_link,
            final_url=final_url,
            cover_url=video_data.get("pic"),
            author=(video_data.get("owner") or {}).get("name"),
            video_streams=video_streams,
            audio_streams=audio_streams,
            preferred_video=preferred_video,
            preferred_audio=preferred_audio,
            subtitle_tracks=subtitle_tracks,
            metadata={
                "capture_strategy": "web-playurl-cookie" if cookies else "web-playurl",
                "cookie_source": cookie_source,
                "media_kind": "video",
                "stream_layout": stream_layout,
                "bvid": bvid,
                "cid": cid,
            },
        )

    def _extract_initial_state(self, html: str) -> dict[str, Any]:
        match = INITIAL_STATE_PATTERN.search(html)
        if not match:
            raise RuntimeError("Failed to locate Bilibili initial state JSON")
        return json.loads(match.group(1))

    def _fetch_playurl(self, *, bvid: str, cid: int, referer: str, cookies=None) -> dict[str, Any]:
        response = requests.get(
            PLAYURL_ENDPOINT,
            params={
                "bvid": bvid,
                "cid": str(cid),
                "qn": "127",
                "fnval": "4048",
                "fourk": "1",
            },
            headers={
                "User-Agent": USER_AGENT,
                "Referer": referer,
            },
            cookies=cookies,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Bilibili playurl API failed: {payload.get('message') or payload.get('code')}")
        return payload.get("data") or {}

    def _fetch_subtitle_tracks(self, *, bvid: str, cid: int, referer: str, cookies=None) -> list[SubtitleTrack]:
        try:
            response = requests.get(
                PLAYER_V2_ENDPOINT,
                params={"bvid": bvid, "cid": str(cid)},
                headers={"User-Agent": USER_AGENT, "Referer": referer},
                cookies=cookies,
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        if payload.get("code") != 0:
            return []
        raw_tracks = (((payload.get("data") or {}).get("subtitle") or {}).get("subtitles") or [])
        tracks: list[SubtitleTrack] = []
        for item in raw_tracks:
            url = item.get("subtitle_url") or item.get("subtitleUrl")
            if not url:
                continue
            if str(url).startswith("//"):
                url = f"https:{url}"
            tracks.append(
                SubtitleTrack(
                    url=str(url),
                    language=item.get("lan") or item.get("language"),
                    label=item.get("lan_doc") or item.get("lanDoc") or item.get("title"),
                    format="json",
                    source="bilibili-player-v2",
                )
            )
        return tracks

    def _build_video_streams(
        self,
        raw_streams: list[dict[str, Any]],
        accept_quality: list[int],
        accept_description: list[str],
    ) -> list[MediaStream]:
        quality_map = dict(zip(accept_quality, accept_description))
        streams: list[MediaStream] = []
        for item in raw_streams:
            stream_url = item.get("base_url") or item.get("baseUrl")
            if not stream_url:
                continue
            quality_id = item.get("id")
            streams.append(
                MediaStream(
                    url=stream_url,
                    stream_type="video",
                    container="mp4",
                    codec=item.get("codecs"),
                    width=item.get("width"),
                    height=item.get("height"),
                    bitrate=item.get("bandwidth"),
                    filesize=item.get("size"),
                    quality_label=quality_map.get(quality_id, str(quality_id) if quality_id is not None else None),
                )
            )
        return streams

    def _build_audio_streams(self, raw_streams: list[dict[str, Any]]) -> list[MediaStream]:
        streams: list[MediaStream] = []
        for item in raw_streams:
            stream_url = item.get("base_url") or item.get("baseUrl")
            if not stream_url:
                continue
            streams.append(
                MediaStream(
                    url=stream_url,
                    stream_type="audio",
                    container="m4a",
                    codec=item.get("codecs"),
                    bitrate=item.get("bandwidth"),
                    filesize=item.get("size"),
                    quality_label=str(item.get("id")) if item.get("id") is not None else None,
                )
            )
        return streams

    def _build_progressive_streams(
        self,
        raw_streams: list[dict[str, Any]],
        *,
        quality: int | None,
        support_formats: list[dict[str, Any]],
        container: str | None,
    ) -> list[MediaStream]:
        # A durl entry is a muxed file (video + audio), unlike separate DASH tracks.
        # Multiple entries represent byte-independent media segments and need a concat
        # pipeline, so do not expose only the first segment as if it were complete.
        if len(raw_streams) != 1:
            return []
        item = raw_streams[0]
        stream_url = item.get("url")
        if not stream_url:
            return []
        format_info = next(
            (entry for entry in support_formats if entry.get("quality") == quality),
            {},
        )
        quality_label = (
            format_info.get("new_description")
            or format_info.get("display_desc")
            or (str(quality) if quality is not None else None)
        )
        return [
            MediaStream(
                url=str(stream_url),
                stream_type="video",
                container=str(container or "mp4").split(",", 1)[0],
                filesize=item.get("size"),
                quality_label=quality_label,
            )
        ]

    def _reject_truncated_preview(
        self,
        *,
        durl_items: list[dict[str, Any]],
        expected_duration_ms: int | None,
        is_upower_exclusive: bool,
    ) -> None:
        try:
            expected = int(expected_duration_ms or 0)
            available = sum(int(item.get("length") or 0) for item in durl_items)
        except (TypeError, ValueError):
            return
        if expected <= 0 or available <= 0 or available >= expected * 0.9:
            return
        available_seconds = max(1, round(available / 1000))
        expected_seconds = max(1, round(expected / 1000))
        if is_upower_exclusive:
            raise RuntimeError(
                "Bilibili UP 主专属内容未解锁："
                f"当前登录态仅返回 {available_seconds} 秒试看流，完整视频约 {expected_seconds} 秒，无权访问完整资源"
            )
        raise RuntimeError(
            "Bilibili 仅返回了截断的试看流："
            f"可用 {available_seconds} 秒，完整视频约 {expected_seconds} 秒，需要登录态或内容权限"
        )

    def _quality_value(self, stream: MediaStream) -> int:
        if not stream.quality_label:
            return 0
        match = re.search(r"(\d+)", stream.quality_label)
        if match:
            return int(match.group(1))
        return 0
