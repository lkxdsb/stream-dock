from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.common import (
    capture_media_with_browser,
    ensure_supported_host,
    extract_first_url,
    extract_script_json_by_id,
    get_url_host,
    host_matches,
)
from fetchers.models import MediaFetchResult, MediaStream

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)


class ChannelsAdapter(BasePlatformAdapter):
    platform_name = "channels"
    supported_hosts = ("channels.weixin.qq.com",)
    download_user_agent = USER_AGENT
    download_referer = "https://channels.weixin.qq.com/"

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        return host_matches(get_url_host(candidate), self.supported_hosts)

    def normalize_link(self, raw_link: str) -> str:
        return ensure_supported_host(extract_first_url(raw_link).strip(), self.supported_hosts, "Channels")

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        try:
            response = requests.get(
                normalized_link,
                headers={"User-Agent": USER_AGENT, "Referer": self.download_referer},
                timeout=30,
            )
            response.raise_for_status()
            payload = self._extract_next_data(response.text)
            feed = (((payload.get("props") or {}).get("pageProps") or {}).get("feed") or {})
            video_info = feed.get("video") or {}
            audio_info = feed.get("audio") or {}

            preferred_video = MediaStream(
                url=video_info.get("playUrl"),
                stream_type="video",
                container="mp4",
                width=video_info.get("width"),
                height=video_info.get("height"),
                bitrate=video_info.get("bitrate"),
            )
            if not preferred_video.url:
                raise RuntimeError("No Channels video stream found")

            preferred_audio = None
            if audio_info.get("playUrl"):
                preferred_audio = MediaStream(
                    url=audio_info.get("playUrl"),
                    stream_type="audio",
                    container="m4a",
                    bitrate=audio_info.get("bitrate"),
                )

            return MediaFetchResult(
                platform=self.platform_name,
                content_type="video",
                title=feed.get("title") or "channels_video",
                source_url=normalized_link,
                final_url=response.url,
                cover_url=feed.get("coverUrl"),
                author=feed.get("nickname"),
                video_streams=[preferred_video],
                audio_streams=[preferred_audio] if preferred_audio else [],
                preferred_video=preferred_video,
                preferred_audio=preferred_audio,
                metadata={
                    "resolve_method": "embedded-json",
                    "raw_platform_id": feed.get("feedId"),
                },
            )
        except Exception:
            capture = capture_media_with_browser(normalized_link, user_agent=USER_AGENT)
            return self._build_fallback_result(normalized_link, capture)

    def _extract_next_data(self, html: str) -> dict[str, Any]:
        return json.loads(extract_script_json_by_id(html, "__NEXT_DATA__"))

    def _build_fallback_result(self, normalized_link: str, capture: dict[str, Any]) -> MediaFetchResult:
        video_streams = [MediaStream(url=capture["video_url"], stream_type="video", container="mp4")]
        audio_streams = (
            [MediaStream(url=capture["audio_url"], stream_type="audio", container="m4a")]
            if capture.get("audio_url")
            else []
        )
        return MediaFetchResult(
            platform=self.platform_name,
            content_type="video",
            title=capture.get("title") or "channels_video",
            source_url=normalized_link,
            final_url=capture.get("final_url") or normalized_link,
            cover_url=capture.get("cover_url"),
            author=capture.get("author"),
            video_streams=video_streams,
            audio_streams=audio_streams,
            preferred_video=video_streams[0],
            preferred_audio=audio_streams[0] if audio_streams else None,
            metadata={
                "resolve_method": "playwright-fallback",
                "raw_platform_id": self._extract_feed_id(normalized_link),
            },
        )

    def _extract_feed_id(self, normalized_link: str) -> str | None:
        query = parse_qs(urlparse(normalized_link).query)
        feed_ids = query.get("feedid") or query.get("feedId")
        return feed_ids[0] if feed_ids else None
