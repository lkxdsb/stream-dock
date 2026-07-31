from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import html2text
import requests
from bs4 import BeautifulSoup, Tag

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

_REQUESTS_TIMEOUT = 5
_PLAYWRIGHT_WAIT_MS = 10_000
_PLAYWRIGHT_GOTO_TIMEOUT = 30_000
_MIN_BODY_TEXT_LENGTH = 200
_MAX_IMAGES = 50
_IMAGE_DOWNLOAD_TIMEOUT = 10

_NON_CONTENT_TAGS = ('nav', 'header', 'footer', 'aside', 'script', 'style', 'form', 'noscript')
_SEMANTIC_MAIN_TAGS = ('main', 'article')

_NOSCRIPT_JS_HINTS = (
    'enable javascript', '需要启用 javascript', '请启用 javascript',
    'javascript is disabled', 'turn on javascript',
)


def fetch_html_with_requests(url: str) -> str:
    headers = {'User-Agent': USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=_REQUESTS_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def fetch_html_with_playwright(url: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until='networkidle', timeout=_PLAYWRIGHT_GOTO_TIMEOUT)
            page.wait_for_timeout(_PLAYWRIGHT_WAIT_MS)
            return page.content()
        finally:
            browser.close()


def should_fallback_to_playwright(html: str) -> bool:
    soup = BeautifulSoup(html, 'html.parser')

    noscript_tags = soup.find_all('noscript')
    for ns in noscript_tags:
        text = (ns.get_text() or '').lower()
        if any(hint in text for hint in _NOSCRIPT_JS_HINTS):
            return True

    body = soup.find('body')
    if body is None:
        return True

    main_node = soup.find(_SEMANTIC_MAIN_TAGS)
    body_text = body.get_text(strip=True)
    if len(body_text) < _MIN_BODY_TEXT_LENGTH:
        return True

    if main_node is None:
        main_like = soup.find(attrs={'role': 'main'}) or soup.find('div', id=re.compile(r'content|main|article', re.I))
        if main_like is None and len(body_text) < _MIN_BODY_TEXT_LENGTH * 2:
            return True

    return False


def extract_main_content(html: str, base_url: str | None = None) -> tuple[Tag, str]:
    soup = BeautifulSoup(html, 'html.parser')

    for tag_name in _NON_CONTENT_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    page_title = _extract_page_title(soup)

    main_node = soup.find(_SEMANTIC_MAIN_TAGS)
    if main_node is None:
        main_node = soup.find(attrs={'role': 'main'})
    if main_node is None:
        main_node = soup.find('body') or soup

    return main_node, page_title


def _extract_page_title(soup: BeautifulSoup) -> str:
    h1 = soup.find('h1')
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    title_tag = soup.find('title')
    if title_tag and title_tag.get_text(strip=True):
        return title_tag.get_text(strip=True)
    return '未命名页面'


def html_to_markdown(html_fragment: Tag, page_title: str) -> str:
    converter = html2text.HTML2Text()
    converter.body_width = 0
    converter.ignore_links = False
    converter.ignore_images = False
    converter.protect_links = True
    converter.unicode_snob = True

    inner_html = str(html_fragment)
    body_md = converter.handle(inner_html).strip()
    title_md = f'# {page_title}\n\n'
    return title_md + body_md


def localize_images(
    html_fragment: Tag,
    base_url: str,
    images_dir: Path,
) -> tuple[Tag, int, int]:
    images_dir.mkdir(parents=True, exist_ok=True)
    img_tags = html_fragment.find_all('img')
    downloaded = 0
    skipped = 0

    for idx, img in enumerate(img_tags):
        if idx >= _MAX_IMAGES:
            skipped += 1
            continue

        src = img.get('src') or img.get('data-src') or ''
        if not src:
            skipped += 1
            continue

        absolute_url = urljoin(base_url, src)
        ext = _infer_image_extension(absolute_url)
        filename = f'image-{idx + 1:03d}.{ext}'
        local_path = images_dir / filename

        try:
            resp = requests.get(
                absolute_url,
                headers={'User-Agent': USER_AGENT},
                timeout=_IMAGE_DOWNLOAD_TIMEOUT,
                stream=True,
            )
            resp.raise_for_status()
            with open(local_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            img['src'] = f'images/{filename}'
            if 'srcset' in img.attrs:
                del img['srcset']
            downloaded += 1
        except Exception:
            skipped += 1

    return html_fragment, downloaded, skipped


def _infer_image_extension(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'avif'):
        if path.endswith(f'.{ext}'):
            return ext
    return 'png'


def extract_page_title_from_html(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    return _extract_page_title(soup)