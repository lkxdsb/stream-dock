from __future__ import annotations

import json
from typing import Any

import requests

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.common import (
    capture_media_with_browser,
    ensure_supported_host,
    extract_balanced_json_after,
    extract_first_url,
    get_url_host,
    host_matches,
)
from fetchers.models import MediaFetchResult, MediaStream

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


class WeiboAdapter(BasePlatformAdapter):
    platform_name = "weibo"
    supported_hosts = ("weibo.com", "m.weibo.cn")
    download_user_agent = USER_AGENT
    download_referer = "https://weibo.com/"

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        return host_matches(get_url_host(candidate), self.supported_hosts)

    def normalize_link(self, raw_link: str) -> str:
        return ensure_supported_host(extract_first_url(raw_link).strip(), self.supported_hosts, "Weibo")

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        try:
            response = requests.get(
                normalized_link,
                headers={"User-Agent": USER_AGENT, "Referer": self.download_referer},
                timeout=30,
            )
            response.raise_for_status()
            payload = self._extract_render_data(response.text)
            status = payload.get("status") or payload
            page_info = status.get("page_info") or {}
            media_info = page_info.get("media_info") or {}

            video_streams = self._build_video_streams(media_info)
            if not video_streams:
                raise RuntimeError("No Weibo video stream found")

            return MediaFetchResult(
                platform=self.platform_name,
                content_type="video",
                title=status.get("text_raw") or "weibo_video",
                source_url=normalized_link,
                final_url=response.url,
                cover_url=((page_info.get("page_pic") or {}).get("url")),
                author=((status.get("user") or {}).get("screen_name")),
                video_streams=video_streams,
                audio_streams=[],
                preferred_video=video_streams[0],
                preferred_audio=None,
                metadata={
                    "resolve_method": "embedded-json",
                    "raw_platform_id": status.get("id"),
                },
            )
        except Exception:
            capture = capture_media_with_browser(normalized_link, user_agent=USER_AGENT)
            return self._build_fallback_result(normalized_link, capture)

    def _extract_render_data(self, html: str) -> dict[str, Any]:
        payload = json.loads(extract_balanced_json_after(html, "var $render_data =", "["))
        if not payload:
            raise RuntimeError("Weibo render data is empty")
        return payload[0]

    def _build_video_streams(self, media_info: dict[str, Any]) -> list[MediaStream]:
        candidates: list[tuple[str, str | None]] = []
        if media_info.get("stream_url_hd"):
            candidates.append((media_info["stream_url_hd"], "高清"))
        if media_info.get("mp4_hd_url"):
            candidates.append((media_info["mp4_hd_url"], "高清"))
        if media_info.get("stream_url"):
            candidates.append((media_info["stream_url"], "标清"))
        if media_info.get("mp4_sd_url"):
            candidates.append((media_info["mp4_sd_url"], "标清"))

        streams: list[MediaStream] = []
        for url, quality in candidates:
            streams.append(
                MediaStream(
                    url=url,
                    stream_type="video",
                    container="mp4",
                    quality_label=quality,
                )
            )
        return streams

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
            title=capture.get("title") or "weibo_video",
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
                "raw_platform_id": self._extract_status_id(normalized_link),
            },
        )

    def _extract_status_id(self, normalized_link: str) -> str | None:
        parts = [part for part in normalized_link.rstrip("/").split("/") if part]
        return parts[-1] if parts else None
