from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from error_catalog import classify_error
from runtime_checks import prepare_output_directory

from web_archive.extractor import (
    extract_main_content,
    fetch_html_with_playwright,
    fetch_html_with_requests,
    html_to_markdown,
    localize_images,
    should_fallback_to_playwright,
)
from web_archive.models import WebArchiveResult

_ILLEGAL_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|]')
_MAX_TITLE_LENGTH = 80

ProgressCallback = Callable[[str, float], None]


def sanitize_title(title: str) -> str:
    sanitized = _ILLEGAL_FILENAME_CHARS.sub('-', title).strip()
    sanitized = re.sub(r'-{2,}', '-', sanitized)
    if not sanitized:
        sanitized = 'untitled'
    return sanitized[:_MAX_TITLE_LENGTH]


def build_output_dir(output_path: str, page_title: str) -> Path:
    base = Path(output_path).expanduser()
    date_prefix = datetime.now().strftime('%Y-%m-%d')
    safe_title = sanitize_title(page_title)
    dir_name = f'{date_prefix}_{safe_title}'
    target = base / 'web-archive' / dir_name
    target.mkdir(parents=True, exist_ok=True)
    return target


def run_web_archive(payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get('url') or '').strip()
    output_path = str(payload.get('outputPath') or '').strip()
    task_id = str(payload.get('_taskId') or '').strip()

    def report(stage: str, progress: float) -> None:
        if task_id:
            try:
                from tasks.store import TaskStore
                store = TaskStore(storage_path=Path.home() / '.streamdock' / 'tasks.json')
                store.update(task_id, stage=stage, progress=progress)
            except Exception:
                pass

    logs: list[str] = []

    try:
        prepare_output_directory(Path(output_path).expanduser())
    except Exception as exc:
        return _error_result(url, str(exc), logs)

    try:
        report('正在获取页面', 10)
        logs.append(f'开始获取页面: {url}')

        html = fetch_html_with_requests(url)
        extract_mode = 'requests'
        logs.append('requests 模式获取 HTML 成功')

        if should_fallback_to_playwright(html):
            report('正在使用浏览器渲染页面', 20)
            logs.append('检测到需要浏览器渲染，回退到 Playwright')
            try:
                html = fetch_html_with_playwright(url)
                extract_mode = 'playwright'
                logs.append('Playwright 渲染完成')
            except Exception as exc:
                error_msg = f'该页面需要浏览器渲染，但 Playwright 环境不可用：{exc}'
                logs.append(error_msg)
                return _error_result(url, error_msg, logs)

        report('正在提取正文', 40)
        logs.append('开始提取正文内容')
        main_node, page_title = extract_main_content(html, base_url=url)
        logs.append(f'页面标题: {page_title}')

        report('正在下载图片', 70)
        output_dir = build_output_dir(output_path, page_title)
        images_dir = output_dir / 'images'
        main_node, downloaded, skipped = localize_images(main_node, url, images_dir)
        logs.append(f'图片下载完成: {downloaded} 张成功, {skipped} 张跳过')

        report('正在生成 Markdown', 90)
        markdown_content = html_to_markdown(main_node, page_title)
        markdown_path = output_dir / 'index.md'
        markdown_path.write_text(markdown_content, encoding='utf-8')
        logs.append(f'Markdown 文件已保存: {markdown_path}')

        report('已完成', 100)

        result = WebArchiveResult(
            url=url,
            title=page_title,
            output_dir=str(output_dir),
            markdown_path=str(markdown_path),
            image_count=downloaded,
            extract_mode=extract_mode,
            logs=logs,
        )

        body = result.to_dict()
        body['success'] = True
        return body

    except Exception as exc:
        error_msg = str(classify_error(str(exc), fallback='网页存档失败')['message'])
        logs.append(f'错误: {error_msg}')
        return _error_result(url, error_msg, logs)


def _error_result(url: str, error: str, logs: list[str]) -> dict[str, Any]:
    error_info = classify_error(error, fallback='网页存档失败')
    return {
        'success': False,
        'url': url,
        'error': error_info['message'],
        'errorCode': error_info['code'],
        'errorInfo': error_info,
        'logs': logs,
    }