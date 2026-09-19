from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Importing app in tests must not touch ~/.streamdock/tasks.json.
os.environ['STREAMDOCK_TASK_STORAGE_PATH'] = ''


# ── Extractor tests ──────────────────────────────────────────

from web_archive.extractor import (
    ExtractorError,
    crawl_url,
    extract_title,
    localize_images_in_markdown,
    parse_cookie_string,
    _humanize_error,
    _MARKDOWN_IMAGE_RE,
    _infer_image_extension,
)
from web_archive.pipeline import build_output_dir, sanitize_title
from web_archive.models import ExtractRequest, WebArchiveResult


def test_humanize_error_translates_timeout():
    raw = "Unexpected error in _crawl_web at line 778 ... Page.goto: Timeout 30000ms exceeded"
    assert "超时" in _humanize_error(raw)


def test_humanize_error_translates_navigation_failure():
    raw = "Failed on navigating ACS-GOTO: net::ERR_NAME_NOT_RESOLVED"
    out = _humanize_error(raw)
    assert "无法打开" in out or "无法连接" in out


def test_humanize_error_blanks_empty_message():
    assert _humanize_error("") == "网页抓取失败"


def test_extract_title_prefers_first_heading():
    md = "some intro\n\n# Real Heading\n\nbody text"
    assert extract_title(md, "Fallback") == "Real Heading"


def test_extract_title_falls_back_to_crawl_title_when_no_heading():
    md = "no heading here, just body text"
    assert extract_title(md, "Crawl Title") == "Crawl Title"


def test_extract_title_defaults_when_both_empty():
    assert extract_title("", "") == "未命名页面"


def test_extract_title_strips_permalink_anchor():
    md = '# `asyncio` — Asynchronous I/O[¶](https://x/asyncio#module-asyncio "Link to this heading")'
    assert extract_title(md, "") == "`asyncio` — Asynchronous I/O"


def test_markdown_image_regex_captures_url():
    md = "![cat](https://example.com/cat.png) and ![dog](/dog.jpg)"
    matches = [m.group(2) for m in _MARKDOWN_IMAGE_RE.finditer(md)]
    assert matches == ["https://example.com/cat.png", "/dog.jpg"]


def test_markdown_image_regex_skips_data_uris_only_when_filtered():
    # The regex still captures data: URIs; filtering happens in localize step.
    md = "![x](data:image/png;base64,abcd)"
    matches = [m.group(2) for m in _MARKDOWN_IMAGE_RE.finditer(md)]
    assert matches == ["data:image/png;base64,abcd"]


def test_infer_image_extension_known_types():
    assert _infer_image_extension("https://x.com/a.png") == "png"
    assert _infer_image_extension("https://x.com/a.JPG") == "jpg"
    assert _infer_image_extension("https://x.com/a.weBP") == "webp"
    assert _infer_image_extension("https://x.com/noext") == "png"


def test_ext_from_content_type_maps_known_mimes():
    from web_archive.extractor import _ext_from_content_type

    assert _ext_from_content_type("image/png") == "png"
    assert _ext_from_content_type("image/jpeg") == "jpg"
    assert _ext_from_content_type("image/svg+xml") == "svg"
    assert _ext_from_content_type("image/webp") == "webp"
    assert _ext_from_content_type("image/avif") == "avif"
    assert _ext_from_content_type("image/x-icon") == "ico"


def test_ext_from_content_type_handles_charset_and_none():
    from web_archive.extractor import _ext_from_content_type

    assert _ext_from_content_type("image/svg+xml; charset=utf-8") == "svg"
    assert _ext_from_content_type("  IMAGE/PNG ") == "png"
    assert _ext_from_content_type(None) is None
    assert _ext_from_content_type("") is None
    assert _ext_from_content_type("application/octet-stream") is None


# ── crawl_url wrapper tests ──────────────────────────────────


def _fake_markdown_result(markdown: str, title: str = "T"):
    result = MagicMock()
    result.success = True
    result.error_message = None
    result.markdown = MagicMock()
    result.markdown.fit_markdown = ""
    result.markdown.raw_markdown = markdown
    result.metadata = {"title": title}
    return result


def test_crawl_url_returns_markdown_and_title_from_raw_when_fit_empty():
    md = "# Page\n\n![img](https://example.com/a.png) text"
    fake = _fake_markdown_result(md, "Crawl Title")
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(return_value=fake)

    with patch("web_archive.extractor.AsyncWebCrawler", return_value=crawler):
        out_md, title, imgs = crawl_url("https://example.com/p")
    assert title == "Crawl Title"
    assert "Page" in out_md
    assert imgs == ["https://example.com/a.png"]


def test_crawl_url_prefers_raw_markdown_to_avoid_fit_content_loss():
    fake = _fake_markdown_result("# 标题\n\n中文正文\n\n| 姓名 | 分数 |\n|---|---|\n| 张三 | 98 |", "标题")
    fake.markdown.fit_markdown = '```python\nprint("only code survived")\n```'
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(return_value=fake)

    with patch("web_archive.extractor.AsyncWebCrawler", return_value=crawler):
        out_md, _, _ = crawl_url("https://example.com/p")

    assert "中文正文" in out_md
    assert "张三" in out_md


def test_crawl_url_raises_extractor_error_when_crawl_fails():
    fake = MagicMock()
    fake.success = False
    fake.error_message = "boom"
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(return_value=fake)

    with patch("web_archive.extractor.AsyncWebCrawler", return_value=crawler):
        try:
            crawl_url("https://example.com/p")
            assert False, "expected ExtractorError"
        except ExtractorError as exc:
            assert "boom" in str(exc)


def test_crawl_url_raises_extractor_error_on_empty_markdown():
    fake = _fake_markdown_result("", "")
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(return_value=fake)

    with patch("web_archive.extractor.AsyncWebCrawler", return_value=crawler):
        try:
            crawl_url("https://example.com/p")
            assert False, "expected ExtractorError"
        except ExtractorError:
            pass


# ── Image localization tests ─────────────────────────────────


def test_localize_images_downloads_and_rewrites_links():
    md = "![a](https://example.com/cat.png)![b](https://example.com/dog.jpg)"

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.headers = {"Content-Type": "image/jpeg" if ".jpg" in url else "image/png"}
        resp.raise_for_status = MagicMock()
        resp.iter_content = lambda chunk_size: [b"img-bytes"]
        return resp

    with tempfile.TemporaryDirectory() as tmp:
        images_dir = Path(tmp) / "images"
        with patch("web_archive.extractor.requests.get", side_effect=mock_get):
            out_md, downloaded, skipped = localize_images_in_markdown(
                md, "https://example.com", images_dir
            )
        assert downloaded == 2
        assert skipped == 0
        assert "images/image-001.png" in out_md
        assert "images/image-002.jpg" in out_md
        assert (images_dir / "image-001.png").is_file()
        assert (images_dir / "image-002.jpg").is_file()


def test_localize_images_uses_content_type_over_url_suffix():
    # URL claims .png but server actually serves SVG -> saved as .svg
    md = "![logo](https://example.com/logo.png)"
    with tempfile.TemporaryDirectory() as tmp:
        images_dir = Path(tmp) / "images"
        with patch("web_archive.extractor.requests.get") as mock_get:
            resp = MagicMock()
            resp.headers = {"Content-Type": "image/svg+xml"}
            resp.raise_for_status = MagicMock()
            resp.iter_content = lambda chunk_size: [b"<svg/>"]
            mock_get.return_value = resp

            out_md, downloaded, skipped = localize_images_in_markdown(
                md, "https://example.com", images_dir
            )
        assert downloaded == 1
        assert "images/image-001.svg" in out_md
        assert (images_dir / "image-001.svg").is_file()
        assert not (images_dir / "image-001.png").exists()


def test_localize_images_falls_back_to_url_suffix_without_content_type():
    # No Content-Type header -> fall back to URL suffix (.png)
    md = "![x](https://example.com/pic.png)"
    with tempfile.TemporaryDirectory() as tmp:
        images_dir = Path(tmp) / "images"
        with patch("web_archive.extractor.requests.get") as mock_get:
            resp = MagicMock()
            resp.headers = {}
            resp.raise_for_status = MagicMock()
            resp.iter_content = lambda chunk_size: [b"data"]
            mock_get.return_value = resp

            out_md, downloaded, skipped = localize_images_in_markdown(
                md, "https://example.com", images_dir
            )
        assert downloaded == 1
        assert "images/image-001.png" in out_md


def test_localize_images_no_suffix_url_uses_content_type():
    # URL has no extension (e.g. /logo?v=3) -> Content-Type decides
    md = "![x](https://example.com/avatar?v=3)"
    with tempfile.TemporaryDirectory() as tmp:
        images_dir = Path(tmp) / "images"
        with patch("web_archive.extractor.requests.get") as mock_get:
            resp = MagicMock()
            resp.headers = {"Content-Type": "image/webp"}
            resp.raise_for_status = MagicMock()
            resp.iter_content = lambda chunk_size: [b"data"]
            mock_get.return_value = resp

            out_md, downloaded, skipped = localize_images_in_markdown(
                md, "https://example.com", images_dir
            )
        assert downloaded == 1
        assert "images/image-001.webp" in out_md
        assert (images_dir / "image-001.webp").is_file()


def test_localize_images_skips_broken_and_keeps_original_link():
    md = "![a](https://broken.example.com/bad.jpg)![b](https://good.example.com/ok.png)"

    def mock_get(url, **kwargs):
        if "broken" in url:
            raise Exception("Connection error")
        mock_resp = MagicMock()
        mock_resp.headers = {}
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content = lambda chunk_size: [b"ok"]
        return mock_resp

    with tempfile.TemporaryDirectory() as tmp:
        images_dir = Path(tmp) / "images"
        with patch("web_archive.extractor.requests.get", side_effect=mock_get):
            out_md, downloaded, skipped = localize_images_in_markdown(
                md, "https://example.com", images_dir
            )
        assert downloaded == 1
        assert skipped == 1
        # Broken image link stays as the original remote URL (not rewritten).
        assert "broken.example.com/bad.jpg" in out_md
        assert "images/image-002.png" in out_md


def test_localize_images_skips_data_uris():
    md = "![a](data:image/png;base64,xxxx)![b](https://example.com/real.png)"
    with tempfile.TemporaryDirectory() as tmp:
        images_dir = Path(tmp) / "images"
        with patch("web_archive.extractor.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.headers = {}
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_content = lambda chunk_size: [b"data"]
            mock_get.return_value = mock_resp

            out_md, downloaded, skipped = localize_images_in_markdown(
                md, "https://example.com", images_dir
            )
        assert downloaded == 1
        assert skipped == 1
        assert "images/image-002.png" in out_md
        assert "data:" in out_md  # data URI left untouched


def test_localize_images_respects_max_limit():
    md = "".join(f"![x](https://example.com/img-{i}.png)" for i in range(55))
    with tempfile.TemporaryDirectory() as tmp:
        images_dir = Path(tmp) / "images"
        with patch("web_archive.extractor.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.headers = {}
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_content = lambda chunk_size: [b"data"]
            mock_get.return_value = mock_resp

            _, downloaded, skipped = localize_images_in_markdown(
                md, "https://example.com", images_dir
            )
        assert downloaded == 50
        assert skipped == 5


def test_localize_images_accepts_precomputed_url_list():
    md = "![a](https://example.com/kept.png)"
    urls = ["https://example.com/kept.png", "https://example.com/list-only.png"]
    with tempfile.TemporaryDirectory() as tmp:
        images_dir = Path(tmp) / "images"
        with patch("web_archive.extractor.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.headers = {}
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_content = lambda chunk_size: [b"d"]
            mock_get.return_value = mock_resp

            out_md, downloaded, skipped = localize_images_in_markdown(
                md, "https://example.com", images_dir, image_urls=urls
            )
        # The url list drives downloads; only links present in md get rewritten.
        assert downloaded == 2
        assert skipped == 0
        assert "images/image-001.png" in out_md


# ── Output directory naming tests ────────────────────────────


def test_sanitize_title_replaces_illegal_chars():
    assert sanitize_title('hello/world:test') == 'hello-world-test'
    assert sanitize_title('a\\b*c?d"e<f>g|h') == 'a-b-c-d-e-f-g-h'


def test_sanitize_title_truncates_long_titles():
    long_title = 'A' * 100
    result = sanitize_title(long_title)
    assert len(result) <= 80


def test_sanitize_title_handles_empty_string():
    assert sanitize_title('') == 'untitled'


def test_archive_output_directory_is_task_unique_for_same_title():
    with tempfile.TemporaryDirectory() as tmp:
        first = build_output_dir(tmp, '相同标题', 'a' * 32)
        second = build_output_dir(tmp, '相同标题', 'b' * 32)

        assert first != second
        assert first.is_dir() and second.is_dir()


# ── Model tests ──────────────────────────────────────────────

def test_extract_request_validates_url():
    import pytest
    with pytest.raises(Exception):
        ExtractRequest(url='not-a-url', outputPath='/tmp')


def test_extract_request_accepts_valid_url():
    req = ExtractRequest(url='https://example.com/page', outputPath='/tmp')
    assert req.url == 'https://example.com/page'
    assert req.cookie is None


def test_extract_request_normalizes_cookie():
    req = ExtractRequest(url='https://example.com/p', outputPath='/tmp', cookie='  a=1; b=2  ')
    assert req.cookie == 'a=1; b=2'
    req_empty = ExtractRequest(url='https://example.com/p', outputPath='/tmp', cookie='   ')
    assert req_empty.cookie is None


# ── Cookie parsing tests ─────────────────────────────────────

def test_parse_cookie_string_pairs():
    cookies = parse_cookie_string('session=abc; theme=dark', 'https://example.com/p')
    assert cookies == [
        {'name': 'session', 'value': 'abc', 'domain': 'example.com', 'path': '/'},
        {'name': 'theme', 'value': 'dark', 'domain': 'example.com', 'path': '/'},
    ]


def test_parse_cookie_string_skips_flags_and_empty():
    cookies = parse_cookie_string('a=1; HttpOnly; ; =noval; b=2', 'https://sub.example.com')
    assert [c['name'] for c in cookies] == ['a', 'b']
    assert cookies[0]['domain'] == 'sub.example.com'


def test_parse_cookie_string_keeps_equals_in_value():
    cookies = parse_cookie_string('token=ab==cd==', 'https://example.com')
    assert cookies[0]['value'] == 'ab==cd=='


def test_crawl_url_passes_cookie_to_browser_config():
    fake = _fake_markdown_result('# T', 'T')
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(return_value=fake)

    captured = {}

    class FakeBrowserConfig:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    with patch('web_archive.extractor.AsyncWebCrawler', return_value=crawler), \
         patch('web_archive.extractor.BrowserConfig', FakeBrowserConfig):
        crawl_url('https://example.com/p', 'session=abc')

    assert captured['cookies'][0]['name'] == 'session'
    assert captured['cookies'][0]['value'] == 'abc'
    assert captured['cookies'][0]['domain'] == 'example.com'


def test_localize_images_forwards_cookie_to_same_host():
    md = '![a](https://example.com/a.png)![b](https://cdn.other.com/b.png)'
    seen = {}

    def mock_get(url, **kwargs):
        seen[url] = kwargs.get('headers', {})
        resp = MagicMock()
        resp.headers = {'Content-Type': 'image/png'}
        resp.raise_for_status = MagicMock()
        resp.iter_content = lambda chunk_size: [b'd']
        return resp

    with tempfile.TemporaryDirectory() as tmp:
        images_dir = Path(tmp) / 'images'
        with patch('web_archive.extractor.requests.get', side_effect=mock_get):
            localize_images_in_markdown(md, 'https://example.com', images_dir, raw_cookie='s=1')

    assert seen['https://example.com/a.png'].get('Cookie') == 's=1'
    assert 'Cookie' not in seen['https://cdn.other.com/b.png']


def test_web_archive_result_to_dict():
    result = WebArchiveResult(
        url='https://example.com',
        title='Test',
        output_dir='/tmp/test',
        markdown_path='/tmp/test/index.md',
        image_count=3,
        extract_mode='crawl4ai',
    )
    d = result.to_dict()
    assert d['url'] == 'https://example.com'
    assert d['imageCount'] == 3
    assert d['extractMode'] == 'crawl4ai'
    assert d['markdownPath'] == '/tmp/test/index.md'


# ── API endpoint tests ───────────────────────────────────────

import httpx
import pytest


def test_web_archive_page_loads():
    async def run():
        from app import app
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            resp = await client.get('/web-archive')
            assert resp.status_code == 200
            assert '网页存档' in resp.text
    asyncio.run(run())


def test_web_archive_extract_rejects_invalid_url():
    async def run():
        from app import app
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            return await client.post('/api/web-archive/extract', json={
                'url': 'not-a-url',
                'outputPath': '/tmp',
            })
    resp = asyncio.run(run())
    # Pydantic validation returns 422 for invalid input.
    assert resp.status_code in (400, 422)


def test_web_archive_asset_rejects_nonexistent_task():
    async def run():
        from app import app
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            return await client.get('/api/web-archive/tasks/nonexistent-id/asset?path=index.md')
    assert asyncio.run(run()).status_code == 404


def test_web_archive_svg_asset_is_forced_to_attachment():
    async def run():
        from app import app, task_store
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'active.svg').write_text('<svg><script>alert(1)</script></svg>', encoding='utf-8')
            task = task_store.create(TaskKind.WEB_ARCHIVE, 'svg archive', {'url': 'https://example.com'})
            task_store.update(task.id, status=TaskStatus.COMPLETED, result={'outputDir': str(root)})
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
                return await client.get(f'/api/web-archive/tasks/{task.id}/asset', params={'path': 'active.svg'})

    response = asyncio.run(run())
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/octet-stream'
    assert response.headers['content-disposition'].startswith('attachment;')
    assert response.headers['x-content-type-options'] == 'nosniff'


# ── Queue tests ──────────────────────────────────────────────

from web_archive.queue import WebArchiveQueue
from tasks.store import TaskStore
from tasks.models import TaskKind, TaskStatus


def test_web_archive_queue_submit_creates_task():
    store = TaskStore()
    queue = WebArchiveQueue(store, lambda payload: {'success': True, 'logs': []})
    task_dict = queue.submit({'url': 'https://example.com', 'outputPath': '/tmp'})
    assert task_dict['kind'] == 'web_archive'
    assert 'example.com' in task_dict['title']
    assert task_dict['status'] == 'pending'


def test_web_archive_queue_cancel_pending_task():
    import time
    from threading import Event

    started = Event()

    def slow_runner(payload):
        started.set()
        time.sleep(1.0)
        return {'success': True, 'logs': []}

    store = TaskStore()
    queue = WebArchiveQueue(store, slow_runner)
    task_dict = queue.submit({'url': 'https://example.com', 'outputPath': '/tmp'})

    # Wait for the worker to start so the task is in RUNNING state.
    started.wait(timeout=2)

    cancelled = queue.cancel(task_dict['id'])
    assert cancelled is True

    # Wait for the runner to finish so the queue can process the cancellation.
    time.sleep(1.5)
    updated = store.get(task_dict['id'])
    assert updated.status in {TaskStatus.CANCELLED, TaskStatus.COMPLETED}


def test_web_archive_queue_marks_unsuccessful_runner_result_failed():
    import time

    store = TaskStore()
    queue = WebArchiveQueue(store, lambda payload: {'success': False, 'error': 'controlled failure', 'logs': []})
    task_dict = queue.submit({'url': 'https://example.com', 'outputPath': '/tmp'})
    deadline = time.time() + 2
    task = store.get(task_dict['id'])
    while task and task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED} and time.time() < deadline:
        time.sleep(.01)
        task = store.get(task_dict['id'])
    assert task is not None
    assert task.status == TaskStatus.FAILED
    assert 'controlled failure' in str(task.error)
