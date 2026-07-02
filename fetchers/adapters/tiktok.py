from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

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
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


class TiktokAdapter(BasePlatformAdapter):
    platform_name = "tiktok"
    supported_hosts = ("tiktok.com",)
    download_user_agent = USER_AGENT
    download_referer = "https://www.tiktok.com/"

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        host = get_url_host(candidate)
        parsed = urlparse(candidate)
        return host_matches(host, self.supported_hosts) and "/video/" in parsed.path

    def normalize_link(self, raw_link: str) -> str:
        candidate = extract_first_url(raw_link).strip()
        ensure_supported_host(candidate, self.supported_hosts, "TikTok")
        if "/video/" not in urlparse(candidate).path:
            raise ValueError(f"Unsupported TikTok video URL: {candidate}")
        return candidate

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        try:
            response = requests.get(
                normalized_link,
                headers={"User-Agent": USER_AGENT, "Referer": self.download_referer},
                timeout=30,
            )
            response.raise_for_status()
            payload = json.loads(extract_script_json_by_id(response.text, "__NEXT_DATA__"))
            return self._build_structured_result(normalized_link, response.url, payload)
        except Exception:
            capture = capture_media_with_browser(normalized_link, user_agent=USER_AGENT)
            return self._build_fallback_result(normalized_link, capture)

    def _build_structured_result(
        self,
        normalized_link: str,
        final_url: str,
        payload: dict[str, Any],
    ) -> MediaFetchResult:
        item = ((((payload.get("props") or {}).get("pageProps") or {}).get("itemInfo") or {}).get("itemStruct") or {})
        video = item.get("video") or {}
        music = item.get("music") or {}

        video_url = video.get("downloadAddr") or video.get("playAddr")
        if not video_url:
            raise RuntimeError("No TikTok video stream found")

        video_streams = [
            MediaStream(
                url=video_url,
                stream_type="video",
                container="mp4",
            )
        ]
        audio_streams = (
            [MediaStream(url=music["playUrl"], stream_type="audio", container="m4a")]
            if music.get("playUrl")
            else []
        )
        return MediaFetchResult(
            platform=self.platform_name,
            content_type="video",
            title=item.get("desc") or "tiktok_video",
            source_url=normalized_link,
            final_url=final_url,
            cover_url=video.get("cover"),
            author=((item.get("author") or {}).get("nickname")),
            video_streams=video_streams,
            audio_streams=audio_streams,
            preferred_video=video_streams[0],
            preferred_audio=audio_streams[0] if audio_streams else None,
            metadata={
                "resolve_method": "next-data",
                "raw_platform_id": item.get("id"),
            },
        )

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
            title=capture.get("title") or "tiktok_video",
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
                "raw_platform_id": self._extract_video_id(normalized_link),
            },
        )

    def _extract_video_id(self, normalized_link: str) -> str | None:
        parts = [part for part in urlparse(normalized_link).path.split("/") if part]
        if "video" not in parts:
            return None
        video_index = parts.index("video")
        return parts[video_index + 1] if len(parts) > video_index + 1 else None
