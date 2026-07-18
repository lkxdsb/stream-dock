from __future__ import annotations

import json
import html as html_lib
import re
from typing import Any

import requests

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.common import (
    capture_media_with_browser,
    collect_subtitle_tracks_from_payload,
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
            note = self._extract_note(payload)
            media = ((note.get("video") or {}).get("media") or {})
            raw_stream_groups = (media.get("stream") or {})

            video_streams = self._build_video_streams(raw_stream_groups)
            audio_streams = self._build_audio_streams(media.get("audioStream"))
            if not video_streams:
                raise RuntimeError("No XiaoHongShu video stream found")

            preferred_video = max(video_streams, key=lambda s: ((s.height or 0), (s.width or 0), (s.bitrate or 0)))
            preferred_audio = max(audio_streams, key=lambda s: (s.bitrate or 0)) if audio_streams else None

            return MediaFetchResult(
                platform=self.platform_name,
                content_type="video",
                title=note.get("title") or self._fallback_title(note.get("noteId") or self._extract_note_id(response.url)),
                source_url=normalized_link,
                final_url=response.url,
                cover_url=self._extract_cover_url(note) or self._extract_meta_cover_url(response.text),
                author=((note.get("user") or {}).get("nickname")),
                video_streams=video_streams,
                audio_streams=audio_streams,
                preferred_video=preferred_video,
                preferred_audio=preferred_audio,
                subtitle_tracks=collect_subtitle_tracks_from_payload(
                    note,
                    source="xiaohongshu-native",
                    base_url=response.url,
                    default_format="json",
                ),
                metadata={
                    "resolve_method": "embedded-json",
                    "raw_platform_id": note.get("noteId"),
                },
            )
        except Exception:
            capture = capture_media_with_browser(normalized_link, user_agent=USER_AGENT)
            return self._build_fallback_result(normalized_link, capture)

    def _extract_initial_state(self, html: str) -> dict[str, Any]:
        raw_state = extract_balanced_json_after(html, "window.__INITIAL_STATE__=", "{")
        return json.loads(self._sanitize_js_object_literal(raw_state))

    def _extract_note(self, payload: dict[str, Any]) -> dict[str, Any]:
        direct_note = payload.get("note")
        if isinstance(direct_note, dict):
            if isinstance(direct_note.get("video"), dict) or isinstance(direct_note.get("imageList"), list):
                return direct_note

            current_note_id = direct_note.get("currentNoteId")
            note_detail_map = direct_note.get("noteDetailMap") or {}
            if isinstance(current_note_id, str) and isinstance(note_detail_map, dict):
                detail = note_detail_map.get(current_note_id) or {}
                if isinstance(detail, dict) and isinstance(detail.get("note"), dict):
                    return detail["note"]

            if isinstance(note_detail_map, dict):
                for detail in note_detail_map.values():
                    if isinstance(detail, dict) and isinstance(detail.get("note"), dict):
                        return detail["note"]

        raise RuntimeError("Failed to extract XiaoHongShu note payload")

    def _sanitize_js_object_literal(self, raw_state: str) -> str:
        parts: list[str] = []
        index = 0
        in_string = False
        escaped = False

        while index < len(raw_state):
            ch = raw_state[index]
            if in_string:
                parts.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                index += 1
                continue

            if ch == '"':
                in_string = True
                parts.append(ch)
                index += 1
                continue

            if raw_state.startswith("undefined", index):
                prev_char = raw_state[index - 1] if index > 0 else ""
                next_index = index + len("undefined")
                next_char = raw_state[next_index] if next_index < len(raw_state) else ""
                if (not prev_char or not (prev_char.isalnum() or prev_char == "_")) and (
                    not next_char or not (next_char.isalnum() or next_char == "_")
                ):
                    parts.append("null")
                    index = next_index
                    continue

            parts.append(ch)
            index += 1

        return "".join(parts)

    def _build_video_streams(self, raw_stream_groups: dict[str, Any]) -> list[MediaStream]:
        streams: list[MediaStream] = []
        seen_urls: set[str] = set()
        for codec_name, raw_streams in raw_stream_groups.items():
            if not isinstance(raw_streams, list):
                continue
            for item in raw_streams:
                stream_url = item.get("masterUrl") or item.get("url")
                if not stream_url or stream_url in seen_urls:
                    continue
                streams.append(
                    MediaStream(
                        url=stream_url,
                        stream_type="video",
                        container="mp4",
                        codec=item.get("codec") or codec_name,
                        width=item.get("width"),
                        height=item.get("height"),
                        bitrate=item.get("avgBitrate") or item.get("bitrate"),
                        filesize=item.get("size"),
                        quality_label=item.get("qualityLabel"),
                    )
                )
                seen_urls.add(stream_url)
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

    @classmethod
    def _extract_cover_url(cls, note: dict[str, Any]) -> str | None:
        candidates: list[str] = []

        cover = note.get("cover")
        if isinstance(cover, str):
            candidates.append(cover)
        elif isinstance(cover, dict):
            candidates.extend(str(cover.get(key) or "") for key in ("url", "urlDefault", "urlPre"))

        for image in note.get("imageList") or []:
            if not isinstance(image, dict):
                continue
            # urlDefault is the full-size web image. urlPre/WB_PRV is only a
            # small preview and should be used after the default image.
            candidates.extend(str(image.get(key) or "") for key in ("url", "urlDefault"))
            info_list = [item for item in (image.get("infoList") or []) if isinstance(item, dict)]
            candidates.extend(
                str(item.get("url") or "")
                for item in info_list
                if str(item.get("imageScene") or "").upper() == "WB_DFT"
            )
            candidates.append(str(image.get("urlPre") or ""))
            candidates.extend(str(item.get("url") or "") for item in info_list)

        for candidate in candidates:
            normalized = cls._normalize_cover_url(candidate)
            if normalized:
                return normalized
        return None

    @classmethod
    def _extract_meta_cover_url(cls, page_html: str) -> str | None:
        for tag in re.findall(r"<meta\b[^>]*>", page_html or "", flags=re.IGNORECASE):
            attrs = {
                name.lower(): html_lib.unescape(value)
                for name, _quote, value in re.findall(
                    r"([:\w-]+)\s*=\s*(['\"])(.*?)\2",
                    tag,
                    flags=re.IGNORECASE | re.DOTALL,
                )
            }
            if str(attrs.get("property") or attrs.get("name") or "").lower() in {"og:image", "twitter:image"}:
                normalized = cls._normalize_cover_url(str(attrs.get("content") or ""))
                if normalized:
                    return normalized
        return None

    @staticmethod
    def _normalize_cover_url(raw_url: str) -> str | None:
        value = html_lib.unescape(str(raw_url or "")).strip()
        if value.startswith("//"):
            return f"https:{value}"
        if value.startswith("http://"):
            return f"https://{value.split('://', 1)[1]}"
        return value if value.startswith("https://") else None

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
            title=capture.get("title") or self._fallback_title(self._extract_note_id(capture.get("final_url") or normalized_link)),
            source_url=normalized_link,
            final_url=capture.get("final_url") or normalized_link,
            cover_url=capture.get("cover_url"),
            author=capture.get("author"),
            video_streams=video_streams,
            audio_streams=audio_streams,
            preferred_video=video_streams[0],
            preferred_audio=audio_streams[0] if audio_streams else None,
            subtitle_tracks=collect_subtitle_tracks_from_payload(
                capture,
                source="xiaohongshu-browser",
                base_url=capture.get("final_url") or normalized_link,
                default_format="json",
            ),
            metadata={
                "resolve_method": "playwright-fallback",
                "raw_platform_id": self._extract_note_id(normalized_link),
            },
        )

    def _extract_note_id(self, normalized_link: str) -> str | None:
        parts = [part for part in normalized_link.rstrip("/").split("/") if part]
        return parts[-1] if parts else None

    @staticmethod
    def _fallback_title(note_id: str | None) -> str:
        clean_id = str(note_id or '').split('?', 1)[0].strip()
        return f'小红书视频_{clean_id[:12]}' if clean_id else '小红书视频'
