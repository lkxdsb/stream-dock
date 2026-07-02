from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

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
PLAYER_RESPONSE_PATTERN = re.compile(r"(?:var\s+)?ytInitialPlayerResponse\s*=")


class YoutubeAdapter(BasePlatformAdapter):
    platform_name = "youtube"
    supported_hosts = ("youtube.com",)
    short_link_hosts = ("youtu.be",)
    download_user_agent = USER_AGENT
    download_referer = "https://www.youtube.com/"

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        host = get_url_host(candidate)
        parsed = urlparse(candidate)
        return host_matches(host, self.supported_hosts + self.short_link_hosts) and (
            host_matches(host, self.short_link_hosts) or parsed.path == "/watch"
        )

    def normalize_link(self, raw_link: str) -> str:
        candidate = extract_first_url(raw_link).strip()
        host = get_url_host(candidate)
        if host_matches(host, self.short_link_hosts):
            video_id = self._extract_video_id_from_short_url(candidate)
            return f"https://www.youtube.com/watch?v={video_id}"
        ensure_supported_host(candidate, self.supported_hosts, "YouTube")
        video_id = self._extract_video_id_from_watch_url(candidate)
        if not video_id:
            raise ValueError(f"Unsupported YouTube watch URL: {candidate}")
        return f"https://www.youtube.com/watch?v={video_id}"

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        try:
            response = requests.get(
                normalized_link,
                headers={"User-Agent": USER_AGENT, "Referer": self.download_referer},
                timeout=30,
            )
            response.raise_for_status()
            payload = self._extract_player_response(response.text)
            video_details = payload.get("videoDetails") or {}
            streaming_data = payload.get("streamingData") or {}

            video_streams = self._build_streams(
                (streaming_data.get("formats") or []) + (streaming_data.get("adaptiveFormats") or []),
                expected_type="video",
            )
            audio_streams = self._build_streams(
                (streaming_data.get("adaptiveFormats") or []) + (streaming_data.get("formats") or []),
                expected_type="audio",
            )
            if not video_streams:
                raise RuntimeError("No YouTube video stream found")

            preferred_video = max(video_streams, key=lambda s: ((s.height or 0), (s.width or 0), (s.bitrate or 0)))
            preferred_audio = max(audio_streams, key=lambda s: (s.bitrate or 0)) if audio_streams else None

            return MediaFetchResult(
                platform=self.platform_name,
                content_type="video",
                title=video_details.get("title") or "youtube_video",
                source_url=normalized_link,
                final_url=response.url,
                cover_url=self._extract_cover_url(video_details),
                author=video_details.get("author"),
                video_streams=video_streams,
                audio_streams=audio_streams,
                preferred_video=preferred_video,
                preferred_audio=preferred_audio,
                metadata={
                    "resolve_method": "embedded-json",
                    "raw_platform_id": video_details.get("videoId") or self._extract_video_id_from_watch_url(normalized_link),
                },
            )
        except Exception:
            capture = capture_media_with_browser(normalized_link, user_agent=USER_AGENT)
            return self._build_fallback_result(normalized_link, capture)

    def _extract_player_response(self, html: str) -> dict[str, Any]:
        match = PLAYER_RESPONSE_PATTERN.search(html)
        if not match:
            raise RuntimeError("Failed to locate ytInitialPlayerResponse anchor")
        return json.loads(extract_balanced_json_after(html[match.start():], "ytInitialPlayerResponse", "{"))

    def _build_streams(self, raw_streams: list[dict[str, Any]], *, expected_type: str) -> list[MediaStream]:
        streams: list[MediaStream] = []
        seen_urls: set[str] = set()
        for item in raw_streams:
            mime_type = item.get("mimeType") or ""
            if not mime_type.startswith(f"{expected_type}/"):
                continue
            stream_url = self._extract_stream_url(item)
            if not stream_url or stream_url in seen_urls:
                continue
            container, codec = self._parse_mime_type(mime_type)
            streams.append(
                MediaStream(
                    url=stream_url,
                    stream_type=expected_type,
                    container=container,
                    codec=codec,
                    width=item.get("width"),
                    height=item.get("height"),
                    bitrate=item.get("bitrate"),
                    filesize=self._parse_int(item.get("contentLength")),
                    quality_label=item.get("qualityLabel"),
                )
            )
            seen_urls.add(stream_url)
        return streams

    def _parse_mime_type(self, mime_type: str) -> tuple[str | None, str | None]:
        media_type, _, params = mime_type.partition(";")
        container = media_type.split("/", 1)[1] if "/" in media_type else None
        codec: str | None = None
        if "codecs=" in params:
            codec = params.split("codecs=", 1)[1].strip().strip('"')
        return container, codec

    def _extract_video_id_from_short_url(self, url: str) -> str:
        path = urlparse(url).path.strip("/")
        if not path:
            raise ValueError(f"Unsupported YouTube short link: {url}")
        return path.split("/", 1)[0]

    def _extract_stream_url(self, item: dict[str, Any]) -> str | None:
        direct_url = item.get("url")
        if direct_url:
            return direct_url

        cipher_text = item.get("signatureCipher") or item.get("cipher")
        if not cipher_text:
            return None
        cipher_params = parse_qs(cipher_text)
        base_url = (cipher_params.get("url") or [None])[0]
        if not base_url:
            return None

        signature_key = (cipher_params.get("sp") or ["signature"])[0]
        signature_value = (cipher_params.get("sig") or cipher_params.get("signature") or [None])[0]
        if signature_value:
            return self._append_query_param(base_url, signature_key, signature_value)

        encrypted_signature = (cipher_params.get("s") or [None])[0]
        if encrypted_signature:
            return None
        return base_url

    def _extract_video_id_from_watch_url(self, url: str) -> str | None:
        parsed = urlparse(url)
        video_ids = parse_qs(parsed.query).get("v")
        return video_ids[0] if video_ids else None

    def _extract_cover_url(self, video_details: dict[str, Any]) -> str | None:
        thumbnails = ((video_details.get("thumbnail") or {}).get("thumbnails")) or []
        if not thumbnails:
            return None
        return thumbnails[-1].get("url")

    def _parse_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _build_fallback_result(self, normalized_link: str, capture: dict[str, Any]) -> MediaFetchResult:
        video_streams = [
            MediaStream(
                url=capture["video_url"],
                stream_type="video",
                container=self._infer_container(capture["video_url"]),
            )
        ]
        audio_streams = (
            [
                MediaStream(
                    url=capture["audio_url"],
                    stream_type="audio",
                    container=self._infer_container(capture["audio_url"]),
                )
            ]
            if capture.get("audio_url")
            else []
        )
        return MediaFetchResult(
            platform=self.platform_name,
            content_type="video",
            title=capture.get("title") or "youtube_video",
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
                "raw_platform_id": self._extract_video_id_from_watch_url(normalized_link),
            },
        )

    def _infer_container(self, url: str | None) -> str | None:
        if not url:
            return None
        path = urlparse(url).path.rsplit("/", 1)[-1]
        if "." not in path:
            return None
        return path.rsplit(".", 1)[-1].lower() or None

    def _append_query_param(self, url: str, key: str, value: str) -> str:
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        query.append((key, value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
