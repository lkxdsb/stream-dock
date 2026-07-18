from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, sync_playwright

from fetchers.models import SubtitleTrack

URL_PATTERN = re.compile(r"https?://[^\s]+")
AUDIO_EXTENSIONS = (".m4a", ".mp3", ".aac", ".wav", ".flac", ".ogg", ".opus")
VIDEO_EXTENSIONS = (".mp4", ".m3u8", ".webm", ".mov", ".mkv", ".m4s")
STATIC_ASSET_EXTENSIONS = (".js", ".css", ".json", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2")
SUBTITLE_EXTENSIONS = (".vtt", ".srt", ".ass", ".ssa", ".ttml", ".dfxp")
SUBTITLE_CONTEXT_KEYWORDS = (
    "subtitle", "subtitles", "caption", "captions", "closedcaption",
    "closed_caption", "danmaku", "danmu", "texttrack", "text_track",
)
SUBTITLE_URL_KEYS = (
    "url", "baseurl", "base_url", "subtitleurl", "subtitle_url",
    "captionurl", "caption_url", "downloadurl", "download_url",
    "playurl", "play_url", "src",
)
SUBTITLE_LABEL_KEYS = ("label", "name", "title", "displayname", "display_name", "desc")
SUBTITLE_LANGUAGE_KEYS = ("language", "languagecode", "language_code", "lang", "langcode", "lan", "locale")
SUBTITLE_FORMAT_KEYS = ("format", "fmt", "type", "mime", "mimetype", "mime_type")


def extract_first_url(raw_text: str) -> str:
    match = URL_PATTERN.search(raw_text)
    if not match:
        raise ValueError("No URL found in input link text")
    return match.group(0)


def get_url_host(url: str) -> str:
    return urlparse(url).netloc.lower().split(":", 1)[0]


def host_matches(host: str, supported_hosts: tuple[str, ...]) -> bool:
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in supported_hosts)


def url_matches_supported_host(url: str, supported_hosts: tuple[str, ...]) -> bool:
    return host_matches(get_url_host(url), supported_hosts)


def ensure_supported_host(url: str, supported_hosts: tuple[str, ...], label: str) -> str:
    if not url_matches_supported_host(url, supported_hosts):
        raise ValueError(f"Unsupported {label} host: {url}")
    return url


def absolutize_url(url: str, base_url: str | None = None) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    if base_url and url.startswith("/"):
        base = urlsplit(base_url)
        return urlunsplit((base.scheme or "https", base.netloc, url, "", ""))
    return url


def extract_balanced_json_after(text: str, anchor: str, opening_char: str) -> str:
    anchor_index = text.find(anchor)
    if anchor_index == -1:
        raise RuntimeError(f"Failed to locate anchor: {anchor}")
    start = text.find(opening_char, anchor_index)
    if start == -1:
        raise RuntimeError(f"Failed to locate JSON start after anchor: {anchor}")

    closing_char = "}" if opening_char == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == opening_char:
            depth += 1
        elif ch == closing_char:
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    raise RuntimeError(f"Failed to locate JSON end after anchor: {anchor}")


def extract_script_json_by_id(html: str, script_id: str) -> str:
    marker = f'id="{script_id}"'
    marker_index = html.find(marker)
    if marker_index == -1:
        raise RuntimeError(f"Failed to locate script id: {script_id}")
    tag_end = html.find(">", marker_index)
    if tag_end == -1:
        raise RuntimeError(f"Failed to locate script tag end for: {script_id}")
    close_tag = html.find("</script>", tag_end)
    if close_tag == -1:
        raise RuntimeError(f"Failed to locate closing script tag for: {script_id}")
    return html[tag_end + 1:close_tag].strip()


def _plain_text_from_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        simple = value.get("simpleText") or value.get("text") or value.get("name")
        if isinstance(simple, str) and simple.strip():
            return simple.strip()
        runs = value.get("runs")
        if isinstance(runs, list):
            text = "".join(str(run.get("text") or "") for run in runs if isinstance(run, dict)).strip()
            return text or None
    return None


def _dict_get_case_insensitive(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    lowered = {str(key).replace("-", "_").lower(): value for key, value in item.items()}
    for key in keys:
        normalized = key.replace("-", "_").lower()
        if normalized in lowered:
            return lowered[normalized]
    return None


def _infer_subtitle_format(url: str, item: dict[str, Any] | None = None, default: str = "vtt") -> str:
    item = item or {}
    value = _plain_text_from_value(_dict_get_case_insensitive(item, SUBTITLE_FORMAT_KEYS))
    if value:
        lowered = value.lower()
        for fmt in ("vtt", "srt", "ass", "ssa", "ttml", "dfxp", "json"):
            if fmt in lowered:
                return fmt
    path = urlparse(url).path.lower()
    for extension in SUBTITLE_EXTENSIONS:
        if path.endswith(extension):
            return extension.lstrip(".")
    if path.endswith(".json"):
        return "json"
    return default


def _looks_like_subtitle_url(url: str, context: tuple[str, ...]) -> bool:
    lowered = url.lower()
    path = urlparse(lowered).path
    if any(path.endswith(extension) for extension in SUBTITLE_EXTENSIONS):
        return True
    if path.endswith(".json") and any(keyword in lowered for keyword in SUBTITLE_CONTEXT_KEYWORDS):
        return True
    return any(keyword in lowered for keyword in SUBTITLE_CONTEXT_KEYWORDS) or any(
        keyword in ".".join(context).lower() for keyword in SUBTITLE_CONTEXT_KEYWORDS
    )


def collect_subtitle_tracks_from_payload(
    payload: Any,
    *,
    source: str,
    base_url: str | None = None,
    default_format: str = "vtt",
    max_tracks: int = 12,
) -> list[SubtitleTrack]:
    """Best-effort native subtitle extractor for platform JSON payloads.

    Short-video platforms use inconsistent field names. This deliberately only
    accepts URLs found under caption/subtitle-like contexts, so ordinary image
    or video URLs are not misreported as subtitles.
    """
    tracks: list[SubtitleTrack] = []
    seen: set[str] = set()

    def add_track(url: str, item: dict[str, Any] | None, context: tuple[str, ...]) -> None:
        if len(tracks) >= max_tracks:
            return
        raw_url = str(url).strip()
        if not (raw_url.startswith(("http://", "https://", "//")) or (base_url and raw_url.startswith("/"))):
            return
        url = absolutize_url(raw_url, base_url)
        if not url or url in seen or not _looks_like_subtitle_url(url, context):
            return
        item = item or {}
        language = _plain_text_from_value(_dict_get_case_insensitive(item, SUBTITLE_LANGUAGE_KEYS))
        label = _plain_text_from_value(_dict_get_case_insensitive(item, SUBTITLE_LABEL_KEYS))
        tracks.append(
            SubtitleTrack(
                url=url,
                language=language,
                label=label or language,
                format=_infer_subtitle_format(url, item, default_format),
                source=source,
            )
        )
        seen.add(url)

    def walk(value: Any, context: tuple[str, ...] = ()) -> None:
        if len(tracks) >= max_tracks:
            return
        if isinstance(value, dict):
            lowered_context = ".".join(context).lower()
            context_is_subtitle = any(keyword in lowered_context for keyword in SUBTITLE_CONTEXT_KEYWORDS)
            for key, child in value.items():
                normalized_key = str(key).replace("-", "_").lower()
                child_context = (*context, normalized_key)
                if isinstance(child, str):
                    if normalized_key in SUBTITLE_URL_KEYS or context_is_subtitle:
                        add_track(child, value, child_context)
                elif isinstance(child, list) and normalized_key in SUBTITLE_URL_KEYS:
                    for item in child:
                        if isinstance(item, str):
                            add_track(item, value, child_context)
                walk(child, child_context)
        elif isinstance(value, list):
            for item in value:
                walk(item, context)

    walk(payload)
    return tracks


def classify_generic_media_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    path = parsed.path.lower()
    lowered = url.lower()
    if is_known_non_target_media_url(url):
        return None
    if any(path.endswith(ext) for ext in STATIC_ASSET_EXTENSIONS):
        return None
    if "video.twimg.com" in parsed.netloc.lower():
        if "/aud/" in path or "/pl/mp4a/" in path:
            return "audio"
        if "/vid/" in path or "/pl/avc1/" in path:
            return "video"
    if any(path.endswith(ext) for ext in AUDIO_EXTENSIONS):
        return "audio"
    if any(path.endswith(ext) for ext in VIDEO_EXTENSIONS):
        return "video"
    if "audio" in lowered and "video" not in lowered:
        return "audio"
    if "video" in lowered or "playurl" in lowered:
        return "video"
    return None


def is_known_non_target_media_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    lowered = url.lower()
    if path.endswith("/generate_204") or path == "/generate_204":
        return True
    if path.startswith("/s/search/audio/"):
        return True
    if "tiktok_web_login_static" in lowered or "website-login" in host:
        return True
    if "default-video-player-ui" in path or "/x-web/assets/" in path:
        return True
    return False


def classify_browser_response_candidate(
    url: str | None,
    *,
    resource_type: str | None = None,
    content_type: str | None = None,
) -> str | None:
    if not url:
        return None

    if is_known_non_target_media_url(url):
        return None

    normalized_resource_type = (resource_type or "").lower()
    normalized_content_type = (content_type or "").lower()

    if normalized_content_type.startswith("image/") or normalized_resource_type == "image":
        return None
    if (
        normalized_content_type.startswith("text/")
        or normalized_content_type.startswith("application/javascript")
        or normalized_content_type.startswith("application/x-javascript")
        or normalized_content_type.startswith("application/json")
        or normalized_content_type.startswith("font/")
    ):
        return None

    url_kind = classify_generic_media_url(url)
    if url_kind in {"audio", "video"}:
        return url_kind

    if normalized_content_type.startswith("audio/"):
        return "audio"
    if normalized_content_type.startswith("video/"):
        return "video"
    return url_kind


def _extract_largest_dimension_area(url: str) -> int:
    areas = [int(width) * int(height) for width, height in re.findall(r"(\d{2,5})x(\d{2,5})", url)]
    return max(areas, default=0)


def _extract_largest_number(url: str) -> int:
    numbers = [int(value) for value in re.findall(r"(?<!\d)(\d{4,9})(?!\d)", url)]
    return max(numbers, default=0)


def choose_best_browser_media_url(urls: list[str], *, kind: str) -> str | None:
    if not urls:
        return None

    def score(url: str) -> tuple[int, int, int, int]:
        path = urlparse(url).path.lower()
        extension_score = 0
        is_twitter_media = "video.twimg.com" in urlparse(url).netloc.lower()
        if path.endswith(".m3u8"):
            extension_score = 3 if is_twitter_media else 2
        elif path.endswith(".mp4") or path.endswith(".m4a"):
            extension_score = 2 if is_twitter_media else 3
        elif path.endswith(".m4s"):
            extension_score = 1
        if kind == "video":
            return (extension_score, _extract_largest_dimension_area(url), _extract_largest_number(url), len(url))
        return (extension_score, _extract_largest_number(url), len(url), 0)

    return max(dict.fromkeys(urls), key=score)


def choose_generic_capture(
    *,
    candidate_video_url: str | None,
    candidate_audio_url: str | None,
    dom_video_sources: list[str],
    final_url: str,
    title: str,
    author: str | None,
    cover_url: str | None,
) -> dict[str, Any]:
    video_url = candidate_video_url
    audio_url = candidate_audio_url
    if video_url is None:
        for source in dom_video_sources:
            if classify_generic_media_url(source) == "video":
                video_url = source
                break

    if not video_url and not audio_url:
        raise RuntimeError("No media URL captured")

    return {
        "final_url": final_url,
        "title": title,
        "author": author,
        "cover_url": cover_url,
        "video_url": video_url,
        "audio_url": audio_url,
    }


def _capture_media_from_context(context: BrowserContext, link: str, wait_ms: int = 10_000) -> dict[str, Any]:
    candidate_video_urls: list[str] = []
    candidate_audio_urls: list[str] = []
    page = context.new_page()

    def on_response(resp: Any) -> None:
        media_kind = classify_browser_response_candidate(
            resp.url,
            resource_type=getattr(resp.request, "resource_type", None),
            content_type=(resp.headers or {}).get("content-type"),
        )
        if media_kind == "video":
            candidate_video_urls.append(resp.url)
        elif media_kind == "audio":
            candidate_audio_urls.append(resp.url)

    page.on("response", on_response)
    page.goto(link, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(wait_ms)

    page_state = page.evaluate(
        """() => ({
            title: document.title,
            author: document.querySelector('meta[name="author"]')?.content || null,
            cover: document.querySelector('meta[property="og:image"]')?.content || document.querySelector('video')?.poster || null,
            videoSources: [...document.querySelectorAll('video')].map(v => v.currentSrc || v.src).filter(Boolean),
        })"""
    )

    return choose_generic_capture(
        candidate_video_url=choose_best_browser_media_url(candidate_video_urls, kind="video"),
        candidate_audio_url=choose_best_browser_media_url(candidate_audio_urls, kind="audio"),
        dom_video_sources=page_state.get("videoSources") or [],
        final_url=page.url,
        title=page_state.get("title") or page.title(),
        author=page_state.get("author"),
        cover_url=page_state.get("cover"),
    )


def capture_media_with_browser(link: str, *, user_agent: str, wait_ms: int = 10_000) -> dict[str, Any]:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            user_agent=user_agent,
        )
        try:
            return _capture_media_from_context(context, link, wait_ms=wait_ms)
        finally:
            browser.close()
