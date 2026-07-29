from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import browser_cookie3
import requests
from playwright.sync_api import BrowserContext, sync_playwright

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.adapters.common import collect_subtitle_tracks_from_payload, extract_balanced_json_after, host_matches
from fetchers.models import ImageAsset, MediaFetchResult, MediaStream

URL_PATTERN = re.compile(r"https?://[^\s]+")
AWEME_ID_PATTERN = re.compile(r"/(?:(?:share/)?(?:video|note))/(\d+)")
ROUTER_DATA_PATTERN = re.compile(r"window\._ROUTER_DATA\s*=")
SUPPORTED_HOSTS = ("v.douyin.com", "www.douyin.com", "douyin.com", "www.iesdouyin.com", "iesdouyin.com")
PROBE_NAVIGATION_TIMEOUT_MS = 30_000
PROBE_WAIT_MS = 6_000
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


def extract_first_url(raw_text: str) -> str:
    match = URL_PATTERN.search(raw_text)
    if not match:
        raise ValueError("No URL found in input link text")
    return match.group(0)


def has_aweme_reference(url: str) -> bool:
    if AWEME_ID_PATTERN.search(url):
        return True
    query = parse_qs(urlparse(url).query)
    return bool(query.get("modal_id") or query.get("aweme_id"))


def aweme_kind_from_url(url: str) -> str | None:
    match = re.search(r"/(?:(?:share/)?(video|note))/\d+", url)
    return match.group(1) if match else None


def is_douyin_generic_landing_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":", 1)[0]
    path = (parsed.path or "/").strip("/")
    return host_matches(host, ("www.douyin.com", "douyin.com")) and path in {"", "jingxuan"}


def resolve_share_link(url: str) -> str:
    """Resolve Douyin short share links quickly before opening Playwright.

    Opening v.douyin.com directly in a browser can wait for a long anti-bot
    bootstrap path. A normal HTTP redirect is enough to obtain the canonical
    /video/{id} URL and avoids front-end probe requests hanging for two
    minutes before the browser navigation timeout expires.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=12,
            allow_redirects=False,
        )
        location = response.headers.get("location") or ""
        if location and host_matches(urlparse(location).netloc.lower().split(":", 1)[0], SUPPORTED_HOSTS):
            # Some Douyin short links resolve to the generic home page when the
            # link is expired or the request is challenged. Do not treat that as
            # a valid video URL; otherwise the probe captures the homepage demo
            # video and the cover naturally stays empty/broken.
            if has_aweme_reference(location):
                return location
    except Exception:
        pass
    match = AWEME_ID_PATTERN.search(url)
    if match:
        kind = aweme_kind_from_url(url) or "video"
        return f"https://www.iesdouyin.com/share/{kind}/{match.group(1)}/"
    return url


def extract_aweme_id(url: str) -> str | None:
    match = AWEME_ID_PATTERN.search(url)
    return match.group(1) if match else None


def first_url(urls: Any) -> str | None:
    if isinstance(urls, list):
        return next((str(url) for url in urls if url), None)
    if isinstance(urls, str) and urls:
        return urls
    return None


def quality_label_from_url_or_video(url: str | None, video: dict[str, Any]) -> tuple[str | None, int | None]:
    height: int | None = None
    if url:
        ratio = (parse_qs(urlparse(url).query).get("ratio") or [""])[0].lower()
        match = re.search(r"(\d{3,4})p", ratio)
        if match:
            height = int(match.group(1))
    if height is None:
        raw_height = video.get("height")
        if isinstance(raw_height, int) and raw_height > 0:
            height = raw_height
    return (f"{height}P" if height else None), height


def extract_router_data_json(html: str) -> str:
    match = ROUTER_DATA_PATTERN.search(html)
    if not match:
        raise RuntimeError("Failed to locate anchor: window._ROUTER_DATA")
    return extract_balanced_json_after(html[match.start():], "=", "{")


def fetch_share_page_detail(link: str) -> dict[str, Any]:
    aweme_id = extract_aweme_id(link)
    candidates = [link]
    if aweme_id:
        preferred_kind = aweme_kind_from_url(link)
        kinds = [preferred_kind] if preferred_kind else []
        kinds.extend(kind for kind in ("note", "video") if kind not in kinds)
        for kind in kinds:
            candidates.extend([
                f"https://www.iesdouyin.com/share/{kind}/{aweme_id}/",
                f"https://www.douyin.com/share/{kind}/{aweme_id}/",
            ])

    last_error: Exception | None = None
    for url in dict.fromkeys(candidates):
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": MOBILE_USER_AGENT,
                    "Referer": "https://www.douyin.com/",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=18,
                allow_redirects=True,
            )
            response.raise_for_status()
            raw_json = extract_router_data_json(response.text)
            data = json.loads(raw_json)
            loader = data.get("loaderData") or {}
            for page_key in ("note_(id)/page", "note_(id)\\u002Fpage", "video_(id)/page", "video_(id)\\u002Fpage"):
                page_data = loader.get(page_key) or {}
                info = page_data.get("videoInfoRes") or {}
                items = info.get("item_list") or []
                detail = next((item for item in items if isinstance(item, dict)), None)
                if detail:
                    return detail
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"分享页结构化数据解析失败：{last_error}")


def capture_from_share_page(link: str) -> dict[str, Any]:
    detail = fetch_share_page_detail(link)
    images = detail.get("images") or []
    author = detail.get("author") or {}
    if images:
        cover = next((item for item in images if isinstance(item, dict)), {})
        return {
            "final_url": link,
            "title": detail.get("desc") or "抖音图文",
            "media_url": None,
            "media_kind": "images",
            "video_url": None,
            "audio_url": None,
            "aweme_detail": detail,
            "cover_url": first_url((cover or {}).get("url_list")),
            "author": author.get("nickname") if isinstance(author, dict) else None,
        }
    video = detail.get("video") or {}
    play_addr = video.get("play_addr") or {}
    video_url = first_url(play_addr.get("url_list"))
    if not video_url:
        for item in video.get("bit_rate") or []:
            video_url = first_url((item.get("play_addr") or {}).get("url_list"))
            if video_url:
                break
    if not video_url:
        raise RuntimeError("分享页未返回可用视频地址")
    cover = video.get("cover") or {}
    return {
        "final_url": link,
        "title": detail.get("desc") or "抖音视频",
        "media_url": video_url,
        "media_kind": "video",
        "video_url": video_url,
        "audio_url": None,
        "aweme_detail": detail,
        "cover_url": first_url(cover.get("url_list")),
        "author": author.get("nickname") if isinstance(author, dict) else None,
    }


def classify_media_url(url: str | None) -> str | None:
    if not url:
        return None
    normalized = url.strip()
    if not normalized or normalized.startswith("blob:"):
        return None
    lowered = normalized.lower()
    if "media-audio-und-mp4a" in lowered:
        return "audio"
    if "media-video-" in lowered:
        return "video"
    if lowered.endswith(".mp4"):
        return "video"
    return None


def choose_media_capture(
    *,
    candidate_video_url: str | None,
    candidate_audio_url: str | None,
    dom_video_sources: list[str],
    final_url: str,
    title: str,
    aweme_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    video_url = candidate_video_url
    audio_url = candidate_audio_url

    if video_url is None:
        for src in dom_video_sources:
            if classify_media_url(src) == "video":
                video_url = src
                break

    if video_url:
        return {
            "final_url": final_url,
            "title": title,
            "media_url": video_url,
            "media_kind": "video",
            "video_url": video_url,
            "audio_url": audio_url,
            "aweme_detail": aweme_detail,
        }
    if audio_url:
        return {
            "final_url": final_url,
            "title": title,
            "media_url": audio_url,
            "media_kind": "audio",
            "video_url": None,
            "audio_url": audio_url,
            "aweme_detail": aweme_detail,
        }
    raise RuntimeError("No media URL captured")


def enrich_capture_if_missing_audio(
    capture: dict[str, Any],
    *,
    link: str,
    strategy: str,
    no_login_capturer: Any,
    cookie_capturer: Any,
) -> tuple[dict[str, Any], str]:
    if capture.get("media_kind") != "video" or capture.get("audio_url"):
        return capture, strategy
    # The mobile share page usually returns a directly playable mp4/playwm URL,
    # where audio is already muxed into the video. Do not open a PC browser only
    # to look for a separated audio request; that path is currently the source
    # of long "quality recognition" waits on Douyin pages.
    if strategy == "share-page":
        return capture, strategy

    retry_candidates: list[tuple[str, Any]] = []
    if strategy == "no-login":
        retry_candidates.append(("no-login", no_login_capturer))
        if cookie_capturer is not None:
            retry_candidates.append(("chrome-cookies", cookie_capturer))
    elif cookie_capturer is not None:
        retry_candidates.append(("chrome-cookies", cookie_capturer))

    for retry_strategy, capturer in retry_candidates:
        try:
            refreshed_capture = capturer(link, wait_ms=15_000)
        except Exception:
            continue
        if refreshed_capture.get("audio_url"):
            return refreshed_capture, retry_strategy
    return capture, strategy


def _capture_media_from_context(context: BrowserContext, link: str, wait_ms: int = 10_000) -> dict[str, Any]:
    candidate_video_url: str | None = None
    candidate_audio_url: str | None = None
    aweme_detail: dict[str, Any] | None = None
    page = context.new_page()

    def on_request(req: Any) -> None:
        nonlocal candidate_video_url, candidate_audio_url
        url = req.url
        media_kind = classify_media_url(url)
        if media_kind == "video":
            candidate_video_url = url
        elif media_kind == "audio":
            candidate_audio_url = url

    def on_response(resp: Any) -> None:
        nonlocal aweme_detail
        if "/aweme/v1/web/aweme/detail/" not in resp.url:
            return
        try:
            payload = resp.json()
        except Exception:
            return
        detail = payload.get("aweme_detail")
        if isinstance(detail, dict):
            aweme_detail = detail

    page.on("request", on_request)
    page.on("response", on_response)
    try:
        page.goto(link, wait_until="commit", timeout=PROBE_NAVIGATION_TIMEOUT_MS)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8_000)
        except Exception:
            pass
    except Exception as exc:
        raise TimeoutError(f"抖音页面打开超时或被平台拦截：{exc}") from exc
    page.wait_for_timeout(wait_ms)

    video_sources = page.evaluate(
        """() => [...document.querySelectorAll('video')].map(v => ({
            src: v.currentSrc || v.src,
            paused: v.paused,
            readyState: v.readyState,
            duration: v.duration,
            currentTime: v.currentTime,
        }))"""
    )
    final_url = page.url
    title = page.title()
    dom_video_sources = [item.get("src") for item in video_sources if item.get("src")]
    return choose_media_capture(
        candidate_video_url=candidate_video_url,
        candidate_audio_url=candidate_audio_url,
        dom_video_sources=dom_video_sources,
        final_url=final_url,
        title=title,
        aweme_detail=aweme_detail,
    )



def is_generic_home_capture(capture: dict[str, Any]) -> bool:
    if not is_douyin_generic_landing_url(str(capture.get("final_url") or "")):
        return False
    if capture.get("aweme_detail"):
        return False
    title = str(capture.get("title") or "")
    video_url = str(capture.get("video_url") or capture.get("media_url") or "")
    return (
        "抖音精选电脑版" in title
        or "douyin-pc-web" in video_url
        or not capture.get("cover_url")
    )


def raise_if_generic_home_capture(capture: dict[str, Any]) -> None:
    if is_generic_home_capture(capture):
        raise RuntimeError(
            "抖音短链只跳转到首页，无法识别具体视频。请在抖音中重新复制视频分享链接，"
            "或确认该链接没有过期/被平台限制。"
        )

def capture_media_no_login(link: str, wait_ms: int = PROBE_WAIT_MS) -> dict[str, Any]:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            user_agent=USER_AGENT,
        )
        try:
            return _capture_media_from_context(context, link, wait_ms=wait_ms)
        finally:
            browser.close()


def load_chrome_cookies_for_douyin() -> list[dict[str, Any]]:
    cookie_jar = browser_cookie3.chrome(domain_name="douyin.com")
    cookies: list[dict[str, Any]] = []
    for cookie in cookie_jar:
        if "douyin.com" not in cookie.domain:
            continue
        cookies.append(
            {
                "name": cookie.name,
                "value": str(cookie.value or ""),
                "domain": cookie.domain,
                "path": cookie.path or "/",
                "expires": float(cookie.expires) if cookie.expires else -1,
                "httpOnly": bool(
                    cookie.has_nonstandard_attr("HttpOnly")
                    or cookie._rest.get("HttpOnly") is not None
                ),
                "secure": bool(cookie.secure),
                "sameSite": "Lax",
            }
        )
    return cookies


def capture_media_with_chrome_cookies(link: str, wait_ms: int = PROBE_WAIT_MS) -> dict[str, Any]:
    cookies = load_chrome_cookies_for_douyin()
    if not cookies:
        raise RuntimeError("No Douyin cookies found in Chrome")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            user_agent=USER_AGENT,
        )
        context.add_cookies(cookies)
        try:
            return _capture_media_from_context(context, link, wait_ms=wait_ms)
        finally:
            browser.close()


class DouyinAdapter(BasePlatformAdapter):
    platform_name = "douyin"
    supported_hosts = SUPPORTED_HOSTS
    download_user_agent = USER_AGENT
    download_referer = "https://www.douyin.com/"

    def can_handle(self, raw_link: str) -> bool:
        try:
            candidate = extract_first_url(raw_link)
        except ValueError:
            candidate = raw_link
        host = urlparse(candidate).netloc.lower().split(":", 1)[0]
        return host_matches(host, self.supported_hosts)

    def normalize_link(self, raw_link: str) -> str:
        return resolve_share_link(extract_first_url(raw_link))

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        try:
            capture = capture_from_share_page(normalized_link)
            raise_if_generic_home_capture(capture)
            strategy = "share-page"
        except Exception as share_error:
            try:
                capture = capture_media_no_login(normalized_link)
                raise_if_generic_home_capture(capture)
                strategy = "no-login"
            except Exception as no_login_error:
                try:
                    capture = capture_media_with_chrome_cookies(normalized_link)
                    raise_if_generic_home_capture(capture)
                    strategy = "chrome-cookies"
                except Exception as cookie_error:
                    raise RuntimeError(
                        "Capture failed in all strategies: "
                        f"share-page=({share_error}); "
                        f"no-login=({no_login_error}); "
                        f"chrome-cookies=({cookie_error})"
                    )

        if capture.get("media_kind") != "images":
            capture, strategy = enrich_capture_if_missing_audio(
                capture,
                link=normalized_link,
                strategy=strategy,
                no_login_capturer=capture_media_no_login,
                cookie_capturer=capture_media_with_chrome_cookies,
            )
        raise_if_generic_home_capture(capture)

        preferred_video = None
        preferred_audio = None
        is_image_collection = capture.get("media_kind") == "images"
        video_streams = [] if is_image_collection else self._build_video_streams(capture.get("aweme_detail"))
        audio_streams: list[MediaStream] = []
        image_assets = self._build_image_assets(capture.get("aweme_detail"))

        if video_streams:
            preferred_video = max(
                video_streams,
                key=lambda s: ((s.height or 0), (s.width or 0), (s.bitrate or 0)),
            )
        elif capture.get("video_url") and not is_image_collection:
            preferred_video = MediaStream(url=capture["video_url"], stream_type="video", container="mp4")
            video_streams.append(preferred_video)
        if capture.get("audio_url"):
            preferred_audio = MediaStream(
                url=capture["audio_url"],
                stream_type="audio",
                container="m4a",
            )
            audio_streams.append(preferred_audio)

        title = capture["title"].replace(" - 抖音", "").strip()
        return MediaFetchResult(
            platform=self.platform_name,
            content_type=capture["media_kind"],
            title=title,
            source_url=normalized_link,
            final_url=capture["final_url"],
            cover_url=capture.get("cover_url"),
            author=capture.get("author"),
            video_streams=video_streams,
            audio_streams=audio_streams,
            preferred_video=preferred_video,
            preferred_audio=preferred_audio,
            image_assets=image_assets,
            subtitle_tracks=collect_subtitle_tracks_from_payload(
                capture.get("aweme_detail"),
                source="douyin-native",
                base_url=capture.get("final_url") or normalized_link,
                default_format="json",
            ),
            metadata={
                "capture_strategy": strategy,
                "media_kind": capture["media_kind"],
                "aweme_id": extract_aweme_id(capture.get("final_url") or normalized_link),
                "image_count": len(image_assets),
            },
        )

    def _build_image_assets(self, aweme_detail: dict[str, Any] | None) -> list[ImageAsset]:
        if not aweme_detail:
            return []
        assets: list[ImageAsset] = []
        seen_urls: set[str] = set()
        bitrate_candidates: dict[str, list[str]] = {}
        for bitrate in aweme_detail.get("img_bitrate") or []:
            if not isinstance(bitrate, dict):
                continue
            for nested in bitrate.get("images") or []:
                if not isinstance(nested, dict):
                    continue
                uri = str(nested.get("uri") or "")
                if not uri:
                    continue
                bitrate_candidates.setdefault(uri, []).extend(
                    str(url) for url in (nested.get("url_list") or []) if url
                )

        def candidate_score(url: str) -> tuple[int, int]:
            path = urlparse(url).path.lower()
            if "-water:" in path:
                return (-1, 0)
            if re.search(r"~q\d+\.(?:png|jpe?g|webp)$", path):
                transform_score = 500
            elif "lqen-new" in path:
                transform_score = 300
            elif "resize" in path:
                transform_score = 200
            elif "shrink" in path:
                transform_score = 100
            else:
                transform_score = 400
            format_score = 30 if path.endswith(".png") else 20 if path.endswith((".jpg", ".jpeg")) else 10
            return (transform_score, format_score)

        for item in aweme_detail.get("images") or []:
            if not isinstance(item, dict):
                continue
            uri = str(item.get("uri") or "")
            # The top-level url_list can be a 1440px display derivative.
            # img_bitrate also carries an unscaled "~q80" source (currently
            # 2160px for the reported real-world note). Prefer that source,
            # while keeping CDN/format alternatives for integrity fallback.
            raw_candidates = [
                *(str(url) for url in (item.get("url_list") or []) if url),
                *bitrate_candidates.get(uri, []),
            ]
            candidates = sorted(
                dict.fromkeys(
                    candidate for candidate in raw_candidates
                    if candidate_score(candidate)[0] >= 0
                ),
                key=candidate_score,
                reverse=True,
            )
            url = next((candidate for candidate in candidates if candidate not in seen_urls), None)
            if not url:
                continue
            path = urlparse(url).path.lower()
            image_format = (
                "png" if path.endswith(".png")
                else "jpg" if path.endswith((".jpg", ".jpeg"))
                else "webp" if path.endswith(".webp")
                else None
            )
            assets.append(
                ImageAsset(
                    url=url,
                    alternate_urls=[candidate for candidate in candidates if candidate != url],
                    width=item.get("width"),
                    height=item.get("height"),
                    format=image_format,
                    quality_label="full-resolution-source",
                    watermarked=False,
                )
            )
            seen_urls.add(url)
        return assets

    def _build_video_streams(self, aweme_detail: dict[str, Any] | None) -> list[MediaStream]:
        if not aweme_detail:
            return []
        video = aweme_detail.get("video") or {}
        raw_streams = video.get("bit_rate") or []
        streams: list[MediaStream] = []
        seen_urls: set[str] = set()
        for item in raw_streams:
            play_addr = item.get("play_addr") or {}
            url_list = play_addr.get("url_list") or []
            stream_url = next((url for url in url_list if url), None)
            if not stream_url or stream_url in seen_urls:
                continue
            codec = "h265" if item.get("is_h265") else ("bytevc1" if item.get("is_bytevc1") else "h264")
            streams.append(
                MediaStream(
                    url=stream_url,
                    stream_type="video",
                    container=item.get("format") or "mp4",
                    codec=codec,
                    width=play_addr.get("width"),
                    height=play_addr.get("height"),
                    bitrate=item.get("bit_rate"),
                    filesize=play_addr.get("data_size"),
                    quality_label=item.get("gear_name"),
                )
            )
            seen_urls.add(stream_url)
        play_url = first_url((video.get("play_addr") or {}).get("url_list"))
        if play_url and play_url not in seen_urls:
            quality_label, height = quality_label_from_url_or_video(play_url, video)
            streams.append(
                MediaStream(
                    url=play_url,
                    stream_type="video",
                    container="mp4",
                    width=None,
                    height=height,
                    quality_label=quality_label,
                )
            )
            seen_urls.add(play_url)
        return streams
