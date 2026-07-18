from __future__ import annotations

import json
import os
import random
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.common import (
    capture_media_with_browser,
    collect_subtitle_tracks_from_payload,
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
    short_link_hosts = ("weixin.qq.com",)
    download_user_agent = USER_AGENT
    download_referer = "https://channels.weixin.qq.com/"

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        host = get_url_host(candidate)
        if host_matches(host, self.supported_hosts):
            return True
        return host_matches(host, self.short_link_hosts) and urlparse(candidate).path.startswith("/sph/")

    def normalize_link(self, raw_link: str) -> str:
        candidate = extract_first_url(raw_link).strip()
        host = get_url_host(candidate)
        if host_matches(host, self.supported_hosts):
            return ensure_supported_host(candidate, self.supported_hosts, "Channels")
        if host_matches(host, self.short_link_hosts) and urlparse(candidate).path.startswith("/sph/"):
            response = requests.get(
                candidate,
                headers={"User-Agent": USER_AGENT, "Referer": self.download_referer},
                timeout=30,
            )
            response.raise_for_status()
            return ensure_supported_host(response.url, self.supported_hosts, "Channels")
        raise ValueError(f"Unsupported Channels host: {candidate}")

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        short_uri = self._extract_short_uri(normalized_link)
        if short_uri:
            try:
                preview_payload = self._fetch_preview_feed_info_with_short_uri(short_uri)
                result = self._build_preview_api_result(
                    preview_payload,
                    source_url=normalized_link,
                    final_url=normalized_link,
                    raw_platform_id=short_uri,
                    resolve_method="preview-api-shorturi",
                )
                if result is not None:
                    return result
                deep_result = self._fetch_share_media_via_optional_parse_service(normalized_link)
                if deep_result is not None:
                    return deep_result
            except Exception:
                pass

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

            video_streams = self._build_video_streams(video_info)
            if not video_streams:
                raise RuntimeError("No Channels video stream found")
            preferred_video = max(
                video_streams,
                key=lambda stream: (
                    stream.height or 0,
                    stream.width or 0,
                    stream.bitrate or 0,
                ),
            )

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
                video_streams=video_streams,
                audio_streams=[preferred_audio] if preferred_audio else [],
                preferred_video=preferred_video,
                preferred_audio=preferred_audio,
                subtitle_tracks=collect_subtitle_tracks_from_payload(
                    feed,
                    source="channels-native",
                    base_url=response.url,
                    default_format="json",
                ),
                metadata={
                    "resolve_method": "embedded-json",
                    "raw_platform_id": feed.get("feedId"),
                },
            )
        except Exception:
            try:
                capture = capture_media_with_browser(normalized_link, user_agent=USER_AGENT)
            except RuntimeError as exc:
                if short_uri:
                    raise RuntimeError(
                        "当前视频号分享链接仅返回封面或文案，未暴露真实视频流；当前环境可能需要更深的播放上下文。"
                    ) from exc
                raise RuntimeError(
                    "未捕获到可下载的视频号媒体流：当前链接可能是图文内容，或需要在微信内打开。"
                ) from exc
            return self._build_fallback_result(normalized_link, capture)

    def _extract_next_data(self, html: str) -> dict[str, Any]:
        return json.loads(extract_script_json_by_id(html, "__NEXT_DATA__"))

    def _build_video_streams(self, video_info: dict[str, Any]) -> list[MediaStream]:
        streams: list[MediaStream] = []
        seen_urls: set[str] = set()

        for item in video_info.get("variants") or []:
            if not isinstance(item, dict):
                continue
            stream_url = item.get("playUrl") or item.get("url")
            if not stream_url or stream_url in seen_urls:
                continue
            streams.append(
                MediaStream(
                    url=stream_url,
                    stream_type="video",
                    container="mp4",
                    width=item.get("width"),
                    height=item.get("height"),
                    bitrate=item.get("bitrate"),
                    quality_label=item.get("qualityLabel"),
                )
            )
            seen_urls.add(stream_url)

        default_url = video_info.get("playUrl")
        if default_url and default_url not in seen_urls:
            streams.append(
                MediaStream(
                    url=default_url,
                    stream_type="video",
                    container="mp4",
                    width=video_info.get("width"),
                    height=video_info.get("height"),
                    bitrate=video_info.get("bitrate"),
                    quality_label=video_info.get("qualityLabel"),
                )
            )
        return streams

    def _extract_short_uri(self, normalized_link: str) -> str | None:
        parsed = urlparse(normalized_link)
        host = get_url_host(normalized_link)
        if host_matches(host, self.short_link_hosts):
            path_parts = [part for part in parsed.path.split("/") if part]
            if len(path_parts) >= 2 and path_parts[0] == "sph":
                return path_parts[1]
        if host_matches(host, self.supported_hosts) and parsed.path.endswith("/pages/sph"):
            ids = parse_qs(parsed.query).get("id") or []
            return ids[0] if ids else None
        return None

    def _generate_rid(self) -> str:
        timestamp_hex = f"{int(time.time()):x}"
        random_hex = "".join(random.choice("0123456789abcdef") for _ in range(8))
        return f"{timestamp_hex}-{random_hex}"

    def _fetch_preview_feed_info_with_short_uri(self, short_uri: str) -> dict[str, Any]:
        page_url = f"https://channels.weixin.qq.com/finder-preview/pages/sph?id={short_uri}"
        api_url = (
            "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
            f"?_rid={self._generate_rid()}"
            "&_pageUrl=https:%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Fsph"
        )
        response = requests.post(
            api_url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Content-Type": "application/json",
                "Origin": "https://channels.weixin.qq.com",
                "Referer": page_url,
                "User-Agent": USER_AGENT,
            },
            json={
                "baseReq": {"generalToken": ""},
                "shortUri": short_uri,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _fetch_preview_feed_info_with_export_id(self, export_id: str, general_token: str) -> dict[str, Any]:
        api_url = (
            "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
            f"?_rid={self._generate_rid()}"
            "&_pageUrl=https:%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed"
        )
        referer = (
            "https://channels.weixin.qq.com/finder-preview/pages/feed"
            f"?entry_card_type=48&comment_scene=39&appid=0&token={general_token}&entry_scene=0&eid={export_id}"
        )
        response = requests.post(
            api_url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Content-Type": "application/json",
                "Origin": "https://channels.weixin.qq.com",
                "Referer": referer,
                "User-Agent": USER_AGENT,
            },
            json={
                "baseReq": {"generalToken": general_token},
                "exportId": export_id,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _build_preview_video_streams(self, feed_info: dict[str, Any]) -> list[MediaStream]:
        candidates = [
            ("原始", feed_info.get("originVideoUrl")),
            ("H.265", ((feed_info.get("h265VideoInfo") or {}).get("videoUrl"))),
            ("H.264", ((feed_info.get("h264VideoInfo") or {}).get("videoUrl"))),
            ("默认", feed_info.get("videoUrl")),
        ]
        streams: list[MediaStream] = []
        seen: set[str] = set()
        for quality_label, stream_url in candidates:
            if not stream_url or stream_url in seen:
                continue
            streams.append(
                MediaStream(
                    url=stream_url,
                    stream_type="video",
                    container="mp4",
                    quality_label=quality_label,
                )
            )
            seen.add(stream_url)
        return streams

    def _build_preview_api_result(
        self,
        payload: dict[str, Any],
        *,
        source_url: str,
        final_url: str,
        raw_platform_id: str | None,
        resolve_method: str,
    ) -> MediaFetchResult | None:
        data = payload.get("data") or {}
        feed_info = data.get("feedInfo") or {}
        author_info = data.get("authorInfo") or {}
        video_streams = self._build_preview_video_streams(feed_info)
        if not video_streams:
            return None
        preferred_video = video_streams[0]
        return MediaFetchResult(
            platform=self.platform_name,
            content_type="video",
            title=feed_info.get("description") or "channels_video",
            source_url=source_url,
            final_url=final_url,
            cover_url=feed_info.get("coverUrl"),
            author=author_info.get("nickname"),
            video_streams=video_streams,
            audio_streams=[],
            preferred_video=preferred_video,
            preferred_audio=None,
            subtitle_tracks=collect_subtitle_tracks_from_payload(
                feed_info,
                source="channels-preview-api",
                base_url=final_url,
                default_format="json",
            ),
            metadata={
                "resolve_method": resolve_method,
                "raw_platform_id": raw_platform_id,
            },
        )

    def _fetch_share_media_via_optional_parse_service(self, normalized_link: str) -> MediaFetchResult | None:
        cookie = os.getenv("CHANNELS_PARSE_COOKIE") or os.getenv("YUANBAO_COOKIE")
        if not cookie:
            return None

        response = requests.post(
            "https://yuanbao.tencent.com/api/weixin/get_parse_result",
            headers={
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
                "content-type": "application/json",
                "origin": "https://yuanbao.tencent.com",
                "referer": "https://yuanbao.tencent.com/",
                "user-agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
                ),
                "x-source": "web",
                "cookie": cookie,
            },
            json={
                "type": "video_channel_url",
                "url": normalized_link,
                "scene": 1,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        parse_data = payload.get("data") or {}
        playable_url = parse_data.get("playable_url") or ""
        if not playable_url:
            return None

        playable_query = parse_qs(urlparse(playable_url).query)
        general_token = (playable_query.get("token") or [""])[0]
        export_id = (playable_query.get("eid") or [""])[0]
        if not general_token or not export_id:
            return None

        preview_payload = self._fetch_preview_feed_info_with_export_id(export_id, general_token)
        return self._build_preview_api_result(
            preview_payload,
            source_url=normalized_link,
            final_url=playable_url,
            raw_platform_id=export_id,
            resolve_method="preview-api-exportid",
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
            title=capture.get("title") or "channels_video",
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
                source="channels-browser",
                base_url=capture.get("final_url") or normalized_link,
                default_format="json",
            ),
            metadata={
                "resolve_method": "playwright-fallback",
                "raw_platform_id": self._extract_feed_id(normalized_link),
            },
        )

    def _extract_feed_id(self, normalized_link: str) -> str | None:
        query = parse_qs(urlparse(normalized_link).query)
        feed_ids = query.get("feedid") or query.get("feedId")
        return feed_ids[0] if feed_ids else None
