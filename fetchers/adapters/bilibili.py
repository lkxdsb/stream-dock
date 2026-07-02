from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import requests

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.common import host_matches
from fetchers.models import MediaFetchResult, MediaStream

URL_PATTERN = re.compile(r"https?://[^\s]+")
INITIAL_STATE_PATTERN = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", re.S)
VIDEO_PATH_PATTERN = re.compile(r"https?://(?:www\.)?bilibili\.com/video/")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
PLAYURL_ENDPOINT = "https://api.bilibili.com/x/player/playurl"


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
        page_response = requests.get(
            normalized_link,
            headers={"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"},
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

        playurl_payload = self._fetch_playurl(bvid=bvid, cid=cid, referer=final_url)
        dash = (playurl_payload.get("dash") or {})
        video_streams = self._build_video_streams(
            dash.get("video") or [],
            playurl_payload.get("accept_quality") or [],
            playurl_payload.get("accept_description") or [],
        )
        audio_streams = self._build_audio_streams(dash.get("audio") or [])
        if not video_streams:
            raise RuntimeError("No Bilibili video streams found in playurl response")
        if not audio_streams:
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
        preferred_audio = max(audio_streams, key=lambda stream: (stream.bitrate or 0, stream.quality_label or ""))

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
            metadata={
                "capture_strategy": "web-playurl",
                "media_kind": "video",
                "bvid": bvid,
                "cid": cid,
            },
        )

    def _extract_initial_state(self, html: str) -> dict[str, Any]:
        match = INITIAL_STATE_PATTERN.search(html)
        if not match:
            raise RuntimeError("Failed to locate Bilibili initial state JSON")
        return json.loads(match.group(1))

    def _fetch_playurl(self, *, bvid: str, cid: int, referer: str) -> dict[str, Any]:
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
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Bilibili playurl API failed: {payload.get('message') or payload.get('code')}")
        return payload.get("data") or {}

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

    def _quality_value(self, stream: MediaStream) -> int:
        if not stream.quality_label:
            return 0
        match = re.search(r"(\d+)", stream.quality_label)
        if match:
            return int(match.group(1))
        return 0
