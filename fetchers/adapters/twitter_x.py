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


class TwitterXAdapter(BasePlatformAdapter):
    platform_name = "twitter_x"
    supported_hosts = ("x.com", "twitter.com")
    download_user_agent = USER_AGENT
    download_referer = "https://x.com/"

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        host = get_url_host(candidate)
        parsed = urlparse(candidate)
        return host_matches(host, self.supported_hosts) and "/status/" in parsed.path

    def normalize_link(self, raw_link: str) -> str:
        candidate = extract_first_url(raw_link).strip()
        ensure_supported_host(candidate, self.supported_hosts, "X")
        normalized = candidate.replace("://twitter.com/", "://x.com/").replace("://www.twitter.com/", "://x.com/")
        if "/status/" not in urlparse(normalized).path:
            raise ValueError(f"Unsupported X status URL: {candidate}")
        return normalized

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
        status = (((payload.get("props") or {}).get("pageProps") or {}).get("status") or {})
        media_entities = status.get("mediaEntities") or []
        if not media_entities:
            raise RuntimeError("No X media entities found")

        media_entity = media_entities[0]
        variants = (((media_entity.get("video_info") or {}).get("variants")) or [])
        video_streams = self._build_video_streams(variants)
        if not video_streams:
            raise RuntimeError("No X video stream found")

        preferred_video = max(video_streams, key=lambda s: (s.bitrate or 0))
        return MediaFetchResult(
            platform=self.platform_name,
            content_type="video",
            title=status.get("text") or "x_video",
            source_url=normalized_link,
            final_url=final_url,
            cover_url=media_entity.get("media_url_https"),
            author=(((((status.get("core") or {}).get("user_results") or {}).get("result") or {}).get("legacy") or {}).get("name")),
            video_streams=video_streams,
            audio_streams=[],
            preferred_video=preferred_video,
            preferred_audio=None,
            metadata={
                "resolve_method": "next-data",
                "raw_platform_id": status.get("rest_id"),
            },
        )

    def _build_video_streams(self, variants: list[dict[str, Any]]) -> list[MediaStream]:
        streams: list[MediaStream] = []
        for variant in variants:
            if variant.get("content_type") != "video/mp4":
                continue
            stream_url = variant.get("url")
            if not stream_url:
                continue
            streams.append(
                MediaStream(
                    url=stream_url,
                    stream_type="video",
                    container="mp4",
                    bitrate=variant.get("bitrate"),
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
            title=capture.get("title") or "x_video",
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
        parts = [part for part in urlparse(normalized_link).path.split("/") if part]
        if "status" not in parts:
            return None
        status_index = parts.index("status")
        return parts[status_index + 1] if len(parts) > status_index + 1 else None
