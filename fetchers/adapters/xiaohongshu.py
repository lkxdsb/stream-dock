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


class XiaohongshuAdapter(BasePlatformAdapter):
    platform_name = "xiaohongshu"
    supported_hosts = ("xiaohongshu.com",)
    short_link_hosts = ("xhslink.com",)
    download_user_agent = USER_AGENT
    download_referer = "https://www.xiaohongshu.com/"

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        host = get_url_host(candidate)
        return host_matches(host, self.supported_hosts + self.short_link_hosts)

    def normalize_link(self, raw_link: str) -> str:
        candidate = extract_first_url(raw_link).strip()
        host = get_url_host(candidate)
        if host_matches(host, self.supported_hosts):
            return ensure_supported_host(candidate, self.supported_hosts, "XiaoHongShu")
        if not host_matches(host, self.short_link_hosts):
            raise ValueError(f"Unsupported XiaoHongShu host: {candidate}")
        response = requests.get(
            candidate,
            headers={"User-Agent": USER_AGENT, "Referer": self.download_referer},
            timeout=30,
        )
        response.raise_for_status()
        return ensure_supported_host(response.url, self.supported_hosts, "XiaoHongShu")

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        try:
            response = requests.get(
                normalized_link,
                headers={"User-Agent": USER_AGENT, "Referer": self.download_referer},
                timeout=30,
            )
            response.raise_for_status()
            payload = self._extract_initial_state(response.text)
            note = payload.get("note") or {}
            media = ((note.get("video") or {}).get("media") or {})

            video_streams = self._build_video_streams(((media.get("stream") or {}).get("h264")) or [])
            audio_streams = self._build_audio_streams(media.get("audioStream"))
            if not video_streams:
                raise RuntimeError("No XiaoHongShu video stream found")

            preferred_video = max(video_streams, key=lambda s: ((s.height or 0), (s.width or 0), (s.bitrate or 0)))
            preferred_audio = max(audio_streams, key=lambda s: (s.bitrate or 0)) if audio_streams else None

            return MediaFetchResult(
                platform=self.platform_name,
                content_type="video",
                title=note.get("title") or "xiaohongshu_video",
                source_url=normalized_link,
                final_url=response.url,
                cover_url=((note.get("cover") or {}).get("url")),
                author=((note.get("user") or {}).get("nickname")),
                video_streams=video_streams,
                audio_streams=audio_streams,
                preferred_video=preferred_video,
                preferred_audio=preferred_audio,
                metadata={
                    "resolve_method": "embedded-json",
                    "raw_platform_id": note.get("noteId"),
                },
            )
        except Exception:
            capture = capture_media_with_browser(normalized_link, user_agent=USER_AGENT)
            return self._build_fallback_result(normalized_link, capture)

    def _extract_initial_state(self, html: str) -> dict[str, Any]:
        return json.loads(extract_balanced_json_after(html, "window.__INITIAL_STATE__=", "{"))

    def _build_video_streams(self, raw_streams: list[dict[str, Any]]) -> list[MediaStream]:
        streams: list[MediaStream] = []
        for item in raw_streams:
            stream_url = item.get("masterUrl") or item.get("url")
            if not stream_url:
                continue
            streams.append(
                MediaStream(
                    url=stream_url,
                    stream_type="video",
                    container="mp4",
                    codec=item.get("codec"),
                    width=item.get("width"),
                    height=item.get("height"),
                    bitrate=item.get("avgBitrate") or item.get("bitrate"),
                    filesize=item.get("size"),
                    quality_label=item.get("qualityLabel"),
                )
            )
        return streams

    def _build_audio_streams(self, raw_audio: dict[str, Any] | None) -> list[MediaStream]:
        if not raw_audio:
            return []
        stream_url = raw_audio.get("url") or raw_audio.get("masterUrl")
        if not stream_url:
            return []
        return [
            MediaStream(
                url=stream_url,
                stream_type="audio",
                container="m4a",
                codec=raw_audio.get("codec"),
                bitrate=raw_audio.get("avgBitrate") or raw_audio.get("bitrate"),
                filesize=raw_audio.get("size"),
                quality_label=raw_audio.get("qualityLabel"),
            )
        ]

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
            title=capture.get("title") or "xiaohongshu_video",
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
                "raw_platform_id": self._extract_note_id(normalized_link),
            },
        )

    def _extract_note_id(self, normalized_link: str) -> str | None:
        parts = [part for part in normalized_link.rstrip("/").split("/") if part]
        return parts[-1] if parts else None
