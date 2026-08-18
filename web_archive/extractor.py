"""Web page extraction backed by crawl4ai.

The previous implementation fetched HTML with requests (falling back to
Playwright for JavaScript-heavy pages) and converted it with html2text. That
pipeline dropped code blocks, mangled Unicode titles, and produced noisy
output. crawl4ai renders with its own browser pool and emits LLM-ready
Markdown that preserves code blocks, tables, and Unicode, so we delegate both
fetching and Markdown conversion to it.

Image localization is layered on top of the Markdown output: wall links are
rewritten to local paths after download, matching the previous on-disk layout
(`images/` next to `index.md`) so the FastAPI asset route keeps working.

Task queue calls the pipeline from a worker thread, so async crawl4ai runs are
wrapped with asyncio.run() to keep the public sync surface.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
except ImportError as _exc:  # pragma: no cover - exercised via runtime health gate
    raise _exc

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

_REQUESTS_TIMEOUT = 10
_IMAGE_DOWNLOAD_TIMEOUT = 15
_MAX_IMAGES = 50

# Markdown image syntax: ![alt](url). Accepts whitespace/newlines inside the
# link target, and quoted or unquoted titles. Keep it greedy enough for real
# site output but anchored to the closing paren.
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# Trailing permalink anchors some doc sites embed in heading text, e.g.
# "# asyncio — Asynchronous I/O[¶](.../asyncio#module-asyncio \"Link to this heading\")".
# We strip them from titles so the saved H1 reads cleanly.
_PERMALINK_RE = re.compile(r'\[(?:¶|#|¶\s*link)\]\([^)]*\)(?:\s*$)?')


class ExtractorError(Exception):
    """Raised when crawl4ai cannot fetch or parse a page."""


def parse_cookie_string(raw_cookie: str, url: str) -> list[dict[str, Any]]:
    """Parse a ``name=value; ...`` cookie header into Playwright cookie dicts.

    Browsers copy cookies as a single ``Cookie`` header string; Playwright's
    ``cookies`` parameter wants structured dicts. Attributes like ``HttpOnly``
    (no ``=``) are ignored — only name/value pairs are forwarded.
    """
    host = urlparse(url).hostname or ""
    cookies: list[dict[str, Any]] = []
    for part in (raw_cookie or "").split(";"):
        name, sep, value = part.partition("=")
        name = name.strip()
        if not sep or not name:
            continue
        cookies.append({
            "name": name,
            "value": value.strip(),
            "domain": host,
            "path": "/",
        })
    return cookies


def _humanize_error(message: str) -> str:
    """Translate crawl4ai's internal RuntimeError traces into user-facing text.

    crawl4ai wraps failures in long stack snippets like
    "Unexpected error in _crawl_web at line 778 ... Page.goto: Timeout 30000ms
    exceeded". That is useless to the end user; we surface the *kind* of
    failure instead so the UI can show an actionable reason.
    """
    text = (message or "").lower()
    if "timeout" in text or "timed out" in text:
        return "页面加载超时，可能该站点较慢或拒绝了自动化访问，请稍后重试或换一个链接"
    if "navigation" in text and ("err" in text or "failed" in text):
        return "无法打开该页面，请检查链接是否可公开访问"
    if "net::err" in text or "connection" in text and "refused" in text:
        return "无法连接到该站点，请检查链接或网络后重试"
    if not message:
        return "网页抓取失败"
    # Fall through with a trimmed message — strip crawl4ai's noisy prefix if present.
    trimmed = message.split("\n", 1)[0]
    return trimmed[:140] if len(trimmed) > 140 else trimmed


async def _crawl_async(url: str, raw_cookie: str | None = None) -> tuple[str, str, list[str]]:
    """Run crawl4ai and return (markdown, title, image_urls).

    image_urls are the distinct remote image URLs discovered in the returned
    Markdown, in first-seen order — used by localize_images_in_markdown to avoid
    re-scanning the (possibly large) text.

    When the user pastes a Cookie header (login-required sites), it is attached
    to the browser context so the rendered page carries the login state.
    """
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=5,
        excluded_tags=["nav", "footer", "aside", "header"],
        wait_for="body",
        page_timeout=15_000,
    )
    cookies = parse_cookie_string(raw_cookie, url) if raw_cookie else []
    browser_config = BrowserConfig(cookies=cookies) if cookies else None
    if browser_config is not None:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=config)
    else:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)

    if not result.success:
        raise ExtractorError(
            _humanize_error(getattr(result, "error_message", None) or "网页抓取失败")
        )

    markdown_field = getattr(result, "markdown", None)
    fit = getattr(markdown_field, "fit_markdown", None)
    raw = getattr(markdown_field, "raw_markdown", None)
    markdown = (fit or raw or "").strip()
    if not markdown:
        raise ExtractorError("页面正文提取为空")

    title = ""
    metadata = getattr(result, "metadata", None) or {}
    if isinstance(metadata, dict):
        title = str(
            metadata.get("og:title")
            or metadata.get("title")
            or metadata.get("description")
            or ""
        ).strip()

    image_urls = list(dict.fromkeys(m.group(2) for m in _MARKDOWN_IMAGE_RE.finditer(markdown)))
    return markdown, title, image_urls


def crawl_url(url: str, raw_cookie: str | None = None) -> tuple[str, str, list[str]]:
    """Synchronous wrapper around crawl4ai for the worker thread.

    Returns (markdown, title, image_urls).
    """
    try:
        return asyncio.run(_crawl_async(url, raw_cookie))
    except ExtractorError:
        raise
    except RuntimeError as exc:
        # asyncio.run raises RuntimeError if a loop is already running in this
        # thread; crawl4ai internals should not, but guard against nested runs.
        if "asyncio.run" in str(exc) and "loop" in str(exc):
            raise ExtractorError("无法在已有事件循环中运行抓取") from exc
        raise
    except Exception as exc:
        raise ExtractorError(str(exc)) from exc


def extract_title(markdown: str, fallback_title: str) -> str:
    """Derive a page title from the first Markdown heading, else the crawl title.

    Strips trailing permalink anchors (e.g. ``[¶](... "Link to this heading")``)
    that some doc sites append to heading text.
    """
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            text = re.sub(r"^#+\s*", "", stripped)
            text = _PERMALINK_RE.sub("", text).strip()
            return text
    text = _PERMALINK_RE.sub("", fallback_title or "").strip()
    return text or "未命名页面"


def localize_images_in_markdown(
    markdown: str,
    base_url: str,
    images_dir: Path,
    image_urls: list[str] | None = None,
    raw_cookie: str | None = None,
) -> tuple[str, int, int]:
    """Download remote images and rewrite their Markdown links to local paths.

    Returns (rewritten_markdown, downloaded, skipped). Downloads are streamed to
    images_dir/ as image-NNN.<ext>, mirroring the previous on-disk layout.

    Login-required sites may gate image assets too, so the user-provided Cookie
    header is forwarded on image requests for the same host.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    urls = image_urls if image_urls is not None else [m.group(2) for m in _MARKDOWN_IMAGE_RE.finditer(markdown)]
    urls = list(dict.fromkeys(urls))
    base_host = urlparse(base_url).hostname or ""

    downloaded = 0
    skipped = 0
    for idx, src in enumerate(urls):
        if idx >= _MAX_IMAGES:
            skipped += 1
            continue
        if not src or src.startswith(("data:", "blob:", "mailto:")):
            skipped += 1
            continue

        absolute_url = urljoin(base_url, src)
        headers = {"User-Agent": USER_AGENT}
        if raw_cookie and (urlparse(absolute_url).hostname or "") == base_host:
            headers["Cookie"] = raw_cookie
        try:
            resp = requests.get(
                absolute_url,
                headers=headers,
                timeout=_IMAGE_DOWNLOAD_TIMEOUT,
                stream=True,
            )
            resp.raise_for_status()
        except Exception:
            skipped += 1
            continue

        # Prefer the actual content type over the URL suffix so the saved file
        # extension matches what the server really returned (e.g. a .png URL
        # that serves SVG, or a /logo?version=3 URL with no suffix at all).
        ext = _ext_from_content_type(resp.headers.get("Content-Type")) or _infer_image_extension(absolute_url)
        filename = f"image-{idx + 1:03d}.{ext}"
        local_rel = f"images/{filename}"
        local_path = images_dir / filename

        try:
            with open(local_path, "wb") as handle:
                for chunk in resp.iter_content(chunk_size=8192):
                    handle.write(chunk)
            markdown = markdown.replace(f"]({src}", f"]({local_rel}")
            downloaded += 1
        except Exception:
            skipped += 1

    return markdown, downloaded, skipped


def _infer_image_extension(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in ("png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif"):
        if path.endswith(f".{ext}"):
            return ext
    return "png"


# Maps the server-reported Content-Type to the on-disk extension. We prefer the
# actual content type over the URL suffix so a `logo.png` that is really SVG, or
# a `/logo?version=3` with no suffix at all, lands with a matching extension.
_CONTENT_TYPE_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/bmp": "bmp",
    "image/avif": "avif",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
}


def _ext_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    # "image/svg+xml; charset=utf-8" -> "image/svg+xml"
    mime = content_type.split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(mime)
