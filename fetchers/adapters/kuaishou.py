from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import requests

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.models import MediaFetchResult, MediaStream

URL_PATTERN = re.compile(r"https?://[^\s]+")
SHORT_VIDEO_PATH_PATTERN = re.compile(r"^/short-video/([^/?#]+)")
MOBILE_PHOTO_PATH_PATTERN = re.compile(r"^/fw/photo/([^/?#]+)")
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)


def extract_first_url(raw_text: str) -> str:
    match = URL_PATTERN.search(raw_text)
    if not match:
        raise ValueError("No URL found in input link text")
    return match.group(0)


class KuaishouAdapter(BasePlatformAdapter):
    platform_name = "kuaishou"
    supported_hosts = ("kuaishou.com", "v.kuaishou.com", "m.gifshow.com", "chenzhongtech.com")
    download_user_agent = USER_AGENT
    download_referer = "https://m.gifshow.com/"

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        parsed = urlparse(candidate)
        host = parsed.netloc.lower()
        path = parsed.path
        if host == "v.kuaishou.com":
            return True
        if host in {"www.kuaishou.com", "kuaishou.com"}:
            return bool(SHORT_VIDEO_PATH_PATTERN.search(path))
        if host in {"m.gifshow.com", "chenzhongtech.com"}:
            return bool(MOBILE_PHOTO_PATH_PATTERN.search(path))
        return False

    def normalize_link(self, raw_link: str) -> str:
        candidate = extract_first_url(raw_link).strip()
        parsed = urlparse(candidate)
        host = parsed.netloc.lower()
        path = parsed.path
        query = f"?{parsed.query}" if parsed.query else ""

        if host in {"www.kuaishou.com", "kuaishou.com"}:
            match = SHORT_VIDEO_PATH_PATTERN.search(path)
            if not match:
                raise ValueError(f"Unsupported Kuaishou page: {candidate}")
            return f"https://m.gifshow.com/fw/photo/{match.group(1)}{query}"

        if host in {"m.gifshow.com", "chenzhongtech.com"}:
            if not MOBILE_PHOTO_PATH_PATTERN.search(path):
                raise ValueError(f"Unsupported Kuaishou mobile page: {candidate}")
            return candidate

        if host == "v.kuaishou.com":
            response = requests.get(
                candidate,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            response.raise_for_status()
            return self.normalize_link(response.url)

        raise ValueError(f"Unsupported Kuaishou host: {candidate}")

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        response = requests.get(
            normalized_link,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        response.raise_for_status()
        state = self._extract_init_state(response.text)
        photo = self._extract_photo_payload(state)
        if photo.get("singlePicture") or photo.get("type") != 1:
            raise RuntimeError("Kuaishou page is not a normal video")

        video_streams = self._build_video_streams(photo)
        if not video_streams:
            raise RuntimeError("No Kuaishou video streams found")
        preferred_video = max(
            video_streams,
            key=lambda stream: (
                stream.height or 0,
                stream.width or 0,
                stream.bitrate or 0,
            ),
        )

        return MediaFetchResult(
            platform=self.platform_name,
            content_type="video",
            title=photo.get("caption") or photo.get("photoId") or "kuaishou_video",
            source_url=normalized_link,
            final_url=response.url,
            cover_url=((photo.get("coverUrls") or [{}])[0].get("url")),
            author=photo.get("userName"),
            video_streams=video_streams,
            audio_streams=[],
            preferred_video=preferred_video,
            preferred_audio=None,
            metadata={
                "capture_strategy": "mobile-init-state",
                "media_kind": "video",
                "photo_id": photo.get("photoId"),
            },
        )

    def _extract_init_state(self, html: str) -> dict[str, object]:
        needle = "window.INIT_STATE = "
        idx = html.find(needle)
        if idx == -1:
            raise RuntimeError("Failed to locate Kuaishou INIT_STATE")
        start = html.find("{", idx)
        if start == -1:
            raise RuntimeError("Failed to locate Kuaishou INIT_STATE JSON start")

        level = 0
        in_string = False
        escaped = False
        end = None
        for offset, ch in enumerate(html[start:], start):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    level += 1
                elif ch == "}":
                    level -= 1
                    if level == 0:
                        end = offset + 1
                        break
        if end is None:
            raise RuntimeError("Failed to locate Kuaishou INIT_STATE JSON end")
        return json.loads(html[start:end])

    def _extract_photo_payload(self, state: dict[str, object]) -> dict[str, object]:
        for value in state.values():
            if isinstance(value, dict) and isinstance(value.get("photo"), dict):
                return value["photo"]
        raise RuntimeError("Failed to extract Kuaishou photo payload")

    def _extract_preferred_representation(self, photo: dict[str, object]) -> dict[str, object]:
        manifest = photo.get("manifest") or {}
        adaptation_sets = manifest.get("adaptationSet") or []
        best: dict[str, object] | None = None
        for adaptation in adaptation_sets:
            if not isinstance(adaptation, dict):
                continue
            for representation in adaptation.get("representation") or []:
                if not isinstance(representation, dict):
                    continue
                if best is None:
                    best = representation
                    continue
                current_score = (
                    representation.get("height") or 0,
                    representation.get("width") or 0,
                    representation.get("avgBitrate") or 0,
                )
                best_score = (
                    best.get("height") or 0,
                    best.get("width") or 0,
                    best.get("avgBitrate") or 0,
                )
                if current_score > best_score:
                    best = representation
        return best or {}

    def _build_video_streams(self, photo: dict[str, object]) -> list[MediaStream]:
        manifest = photo.get("manifest") or {}
        adaptation_sets = manifest.get("adaptationSet") or []
        streams: list[MediaStream] = []
        seen_urls: set[str] = set()

        for adaptation in adaptation_sets:
            if not isinstance(adaptation, dict):
                continue
            for representation in adaptation.get("representation") or []:
                if not isinstance(representation, dict):
                    continue
                stream_url = representation.get("url")
                if not stream_url or stream_url in seen_urls:
                    continue
                streams.append(
                    MediaStream(
                        url=stream_url,
                        stream_type="video",
                        container="m3u8" if str(stream_url).lower().endswith(".m3u8") else "mp4",
                        codec=representation.get("videoCodec") or representation.get("codecs"),
                        width=representation.get("width") or photo.get("width"),
                        height=representation.get("height") or photo.get("height"),
                        bitrate=representation.get("avgBitrate"),
                        filesize=None,
                        quality_label=representation.get("qualityLabel"),
                    )
                )
                seen_urls.add(stream_url)

        if len(streams) > 1:
            return streams

        main_mv_urls = photo.get("mainMvUrls") or []
        video_url = next(
            (
                item.get("url")
                for item in main_mv_urls
                if isinstance(item, dict) and item.get("url")
            ),
            None,
        )
        if not video_url:
            return streams

        representation = self._extract_preferred_representation(photo)
        return [
            MediaStream(
                url=video_url,
                stream_type="video",
                container="mp4",
                codec=representation.get("videoCodec") or representation.get("codecs"),
                width=representation.get("width") or photo.get("width"),
                height=representation.get("height") or photo.get("height"),
                bitrate=representation.get("avgBitrate"),
                filesize=None,
                quality_label=representation.get("qualityLabel"),
            )
        ]
