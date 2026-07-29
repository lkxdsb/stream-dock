from __future__ import annotations

import os
import re
import asyncio
import signal
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict
from threading import Lock
from threading import Thread
from time import monotonic, sleep
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import uuid4

import requests
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from converters.batch import BatchInput, convert_batch_files, make_batch_inputs, validate_batch_route
from converters.models import ConversionLevel
from converters.executor import convert_file_with_timeout
from converters.registry import find_capability, infer_input_format, list_capabilities, normalize_format, targets_for_source
from converters.sniff import validate_declared_format
from error_catalog import classify_error
from fetchers.adapters.bilibili import USER_AGENT as BILIBILI_USER_AGENT, reset_manual_cookie_overrides, set_manual_cookie_overrides
from fetchers.models import ImageAsset, MediaFetchResult, MediaStream, SubtitleTrack
from fetchers.pipeline import available_output_path, generate_metadata_subtitle_file, probe_media
from fetchers.subtitle_asr import asr_available, generate_asr_subtitle_file
from fetchers.subtitle_ocr import generate_ocr_subtitle_file, ocr_available
from media.ranker import recommendations
from pdf_engine.models import PdfParseMode
from pdf_engine.providers.mineru import MinerUProvider
from pdf_engine.service import analyze_pdf, parse_pdf
from pdf_engine.quality import evaluate_pdf_result
from tasks.media_queue import MediaQueue
from tasks.pdf_queue import PdfQueue
from tasks.subtitle_queue import SubtitleQueue
from tasks.models import TaskKind, TaskStatus
from tasks.store import TaskStore
from runtime_checks import augmented_path, cleanup_task_partials, deep_media_quality, ensure_system_proxy_environment, environment_health, network_subprocess_environment, prepare_output_directory, validate_media_output
from subtitles.service import export_subtitles, normalize_format as normalize_subtitle_format, parse_subtitles

ensure_system_proxy_environment()

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / 'templates'
STATIC_DIR = BASE_DIR / 'static'
SCRIPT_PATH = BASE_DIR / 'douyin_fetch.py'
OUTPUT_FILE_PATTERN = re.compile(r"output file:\s*(.+)$")
PLATFORM_PATTERN = re.compile(r"platform:\s*(.+)$")
TITLE_PATTERN = re.compile(r"title:\s*(.+)$")
COVER_URL_PATTERN = re.compile(r"cover url:\s*(.+)$")
COVER_FILE_PATTERN = re.compile(r"cover file:\s*(.+)$")
SUBTITLE_FILE_PATTERN = re.compile(r"subtitle file:\s*(.+)$")
SUBTITLE_COUNT_PATTERN = re.compile(r"subtitle count:\s*(\d+)$")
SUBTITLE_DETAIL_PATTERN = re.compile(r"subtitle detail:\s*([^|]+)\|([^|]+)\|(.+)$")
SUBTITLE_PENDING_PATTERN = re.compile(r"subtitle pending:\s*(true|false)$", re.IGNORECASE)
MEDIA_KIND_PATTERN = re.compile(r"captured media kind:\s*(.+)$")
IMAGE_FILE_PATTERN = re.compile(r"image file:\s*(.+)$")
IMAGE_COUNT_PATTERN = re.compile(r"image count:\s*(\d+)$")
PROGRESS_PATTERN = re.compile(r"progress:\s*([0-9.]*)\|(.+)$")
UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_CONVERT_FILE_BYTES = int(os.getenv('STREAMDOCK_MAX_CONVERT_FILE_BYTES', str(500 * 1024 * 1024)))
MAX_CONVERT_BATCH_FILES = int(os.getenv('STREAMDOCK_MAX_CONVERT_BATCH_FILES', '20'))
MAX_CONVERT_BATCH_TOTAL_BYTES = int(os.getenv('STREAMDOCK_MAX_CONVERT_BATCH_TOTAL_BYTES', str(1024 * 1024 * 1024)))
CONVERT_TIMEOUT_SECONDS = int(os.getenv('STREAMDOCK_CONVERT_TIMEOUT_SECONDS', '120'))
MEDIA_TIMEOUT_SECONDS = int(os.getenv('STREAMDOCK_MEDIA_TIMEOUT_SECONDS', str(20 * 60)))
MEDIA_IDLE_TIMEOUT_SECONDS = int(os.getenv('STREAMDOCK_MEDIA_IDLE_TIMEOUT_SECONDS', str(5 * 60)))
MAX_SUBTITLE_FILE_BYTES = int(os.getenv('STREAMDOCK_MAX_SUBTITLE_FILE_BYTES', str(5 * 1024 * 1024)))

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app = FastAPI(title='Douyin Local Fetch UI')
app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')


def _task_storage_path() -> Path | None:
    """Allow tests and disposable runs to opt out of the user's persistent history."""
    configured = os.getenv('STREAMDOCK_TASK_STORAGE_PATH')
    if configured is not None:
        configured = configured.strip()
        return Path(configured).expanduser() if configured else None
    return Path.home() / '.streamdock' / 'tasks.json'


task_store = TaskStore(storage_path=_task_storage_path())
_media_processes: dict[str, subprocess.Popen[str]] = {}
_media_process_lock = Lock()
_pdf_processes: dict[str, subprocess.Popen[str]] = {}
_pdf_process_lock = Lock()


@app.middleware('http')
async def local_api_only(request: Request, call_next):
    """Keep filesystem-writing APIs local even if uvicorn is accidentally bound to 0.0.0.0."""
    if request.url.path.startswith('/api/') and os.getenv('STREAMDOCK_ALLOW_LAN_API', '0') != '1':
        client_host = request.client.host if request.client else ''
        if client_host not in {'127.0.0.1', '::1', 'localhost', 'testclient'}:
            return JSONResponse(
                {'success': False, 'error': '为保护本地文件，API 默认仅允许本机访问'},
                status_code=403,
            )
    return await call_next(request)


class FetchRequest(BaseModel):
    link: str = Field(min_length=1)
    outputPath: str = Field(min_length=1)
    outputType: str = Field(pattern=r'^(m4a|mp3|mp4|wav|flac|aac|ogg|opus|mkv|mov|webm)$')
    videoQuality: str | None = None
    bilibiliCookie: str | None = None
    bilibiliCookieFile: str | None = None
    saveAssets: bool = False
    subtitleStrategy: str | None = None


class BatchFetchRequest(BaseModel):
    links: list[str] = Field(min_length=1, max_length=20)
    outputPath: str = Field(min_length=1)
    outputType: str = Field(pattern=r'^(m4a|mp3|mp4|wav|flac|aac|ogg|opus|mkv|mov|webm)$')
    videoQuality: str | None = None
    bilibiliCookie: str | None = None
    bilibiliCookieFile: str | None = None
    saveAssets: bool = False
    subtitleStrategy: str | None = None


class SubtitleTextRequest(BaseModel):
    filename: str = 'subtitle.srt'
    text: str = Field(min_length=1, max_length=MAX_SUBTITLE_FILE_BYTES)
    format: str | None = None


class SubtitleCueRequest(BaseModel):
    start: float = Field(ge=0, le=7 * 24 * 60 * 60)
    end: float = Field(gt=0, le=7 * 24 * 60 * 60)
    text: str = Field(min_length=1, max_length=4000)


class SubtitleExportRequest(BaseModel):
    filename: str = 'subtitle'
    format: str = 'srt'
    cues: list[SubtitleCueRequest] = Field(min_length=1, max_length=5000)


class ProbeRequest(BaseModel):
    link: str = Field(min_length=1)
    bilibiliCookie: str | None = None
    bilibiliCookieFile: str | None = None




def media_cover_headers(raw_url: str) -> dict[str, str]:
    parsed = urlparse(raw_url)
    host = parsed.netloc.lower()
    referer = f'{parsed.scheme}://{parsed.netloc}/'
    if 'hdslb.com' in host or 'bilibili.com' in host:
        referer = 'https://www.bilibili.com/'
    elif 'douyinpic.com' in host or 'douyin.com' in host or 'douyincdn.com' in host:
        referer = 'https://www.douyin.com/'
    elif 'xhscdn.com' in host or 'xiaohongshu.com' in host:
        referer = 'https://www.xiaohongshu.com/'
    elif 'twimg.com' in host or host == 'x.com' or host.endswith('.x.com') or 'twitter.com' in host:
        referer = 'https://x.com/'
    return {
        'User-Agent': BILIBILI_USER_AGENT,
        'Referer': referer,
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
    }


def sniff_image_media_type(content: bytes, fallback: str = 'image/jpeg') -> str | None:
    head = content[:16]
    if head.startswith(bytes.fromhex('ffd8ff')):
        return 'image/jpeg'
    if head.startswith(bytes.fromhex('89504e470d0a1a0a')):
        return 'image/png'
    if head.startswith(b'GIF87a') or head.startswith(b'GIF89a'):
        return 'image/gif'
    if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    if content.lstrip()[:5].lower().startswith(b'<svg'):
        return 'image/svg+xml'
    return fallback if fallback.startswith('image/') else None


def normalize_remote_image_url(raw_url: str) -> str:
    # FastAPI has already decoded the outer ``url=`` query parameter once.
    # Do not unquote the embedded remote URL again: signed image URLs (for
    # example Douyin's ``x-signature=...%3D``) require their percent-encoded
    # query value to remain byte-for-byte intact.  A second unquote turns the
    # encoded padding into a literal ``=`` and Douyin responds with HTTP 403.
    value = str(raw_url or '').strip()
    if value.startswith('//'):
        value = f'https:{value}'
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('仅支持 http/https 图片链接')
    return value

def extract_output_file(stdout: str) -> str | None:
    for line in stdout.splitlines():
        match = OUTPUT_FILE_PATTERN.search(line)
        if match:
            return match.group(1).strip()
    return None


def extract_platform(stdout: str) -> str | None:
    for line in stdout.splitlines():
        match = PLATFORM_PATTERN.search(line)
        if match:
            return match.group(1).strip()
    return None



def extract_first_match(stdout: str, pattern: re.Pattern[str]) -> str | None:
    for line in stdout.splitlines():
        match = pattern.search(line)
        if match:
            return match.group(1).strip()
    return None


def extract_all_matches(stdout: str, pattern: re.Pattern[str]) -> list[str]:
    values: list[str] = []
    for line in stdout.splitlines():
        match = pattern.search(line)
        if match:
            values.append(match.group(1).strip())
    return values

def serialize_stream(stream: MediaStream) -> dict[str, object]:
    stream_url = stream.url.decode('utf-8', errors='ignore') if isinstance(stream.url, bytes) else str(stream.url)
    parsed = urlparse(stream_url)
    path = str(parsed.path or '').lower()
    is_hls = (stream.container or '').lower() == 'm3u8' or path.endswith('.m3u8')
    return {
        'url': stream_url,
        'host': parsed.netloc,
        'streamType': stream.stream_type,
        'container': stream.container,
        'isHls': is_hls,
        'codec': stream.codec,
        'width': stream.width,
        'height': stream.height,
        'bitrate': stream.bitrate,
        'filesize': stream.filesize,
        'filesizeLabel': format_bytes(stream.filesize) if stream.filesize else None,
        'qualityLabel': stream.quality_label,
    }


def probe_stream_http_info(url: str, *, timeout_seconds: float = 4.0) -> dict[str, object]:
    try:
        response = requests.head(
            url,
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.douyin.com/'},
            timeout=(timeout_seconds, timeout_seconds),
            allow_redirects=True,
        )
        response.close()
        content_length = response.headers.get('content-length')
        return {
            'status': response.status_code,
            'contentType': response.headers.get('content-type'),
            'contentLength': int(content_length) if content_length and content_length.isdigit() else None,
            'contentLengthLabel': format_bytes(int(content_length)) if content_length and content_length.isdigit() else None,
            'finalHost': urlparse(response.url).netloc,
        }
    except Exception:
        return {}


def enrich_serialized_streams(streams: list[dict[str, object]], preferred_url: str | None) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for index, stream in enumerate(streams):
        item = dict(stream)
        should_probe = (
            bool(item.get('url'))
            and not item.get('filesize')
            and not item.get('isHls')
            and (item.get('url') == preferred_url or index < 3)
        )
        if should_probe:
            http_info = probe_stream_http_info(str(item.get('url')))
            size = http_info.get('contentLength')
            if size:
                item['filesize'] = size
                item['filesizeLabel'] = http_info.get('contentLengthLabel')
            if http_info.get('contentType'):
                item['contentType'] = http_info.get('contentType')
            if http_info.get('finalHost'):
                item['finalHost'] = http_info.get('finalHost')
        enriched.append(item)
    return enriched


def serialize_subtitle_track(track: SubtitleTrack) -> dict[str, object]:
    return {
        'url': track.url,
        'language': track.language,
        'label': track.label,
        'format': track.format,
        'source': track.source,
    }


def serialize_image_asset(image: ImageAsset) -> dict[str, object]:
    return {
        'url': image.url,
        'candidateCount': 1 + len(image.alternate_urls),
        'width': image.width,
        'height': image.height,
        'format': image.format,
        'filesize': image.filesize,
        'qualityLabel': image.quality_label,
        'watermarked': image.watermarked,
    }


def safe_metadata(metadata: dict[str, object]) -> dict[str, object]:
    allowed = {
        'capture_strategy', 'resolve_method', 'media_kind', 'cookie_source',
        'stream_layout', 'bvid', 'cid', 'raw_platform_id', 'aweme_id', 'note_id', 'photo_id', 'short_url',
        'image_count',
    }
    safe: dict[str, object] = {}
    for key, value in (metadata or {}).items():
        if key in allowed and value not in (None, ''):
            safe[key] = value
    return safe


def infer_video_info(result: MediaFetchResult) -> dict[str, object]:
    best = result.preferred_video
    return {
        'bestQualityLabel': best.quality_label if best else None,
        'bestResolution': f'{best.width}×{best.height}' if best and best.width and best.height else None,
        'bestCodec': best.codec if best else None,
        'bestBitrate': best.bitrate if best else None,
        'delivery': 'image-collection' if result.content_type == 'images' else infer_probe_delivery(result),
        'videoStreamCount': len(result.video_streams),
        'audioStreamCount': len(result.audio_streams),
        'subtitleCount': len(result.subtitle_tracks),
        'coverAvailable': bool(result.cover_url),
        'imageCount': len(result.image_assets),
    }


def infer_probe_delivery(result: MediaFetchResult) -> str:
    streams = result.video_streams or []
    for stream in streams:
        container = str(stream.container or '').lower()
        url = str(stream.url or '').lower()
        if container == 'm3u8' or url.endswith('.m3u8'):
            return 'hls'
    return 'direct'


def infer_access_hint(result: MediaFetchResult) -> str:
    metadata = result.metadata or {}
    platform = result.platform
    capture_strategy = str(metadata.get('capture_strategy') or '')
    cookie_source = metadata.get('cookie_source')

    if platform == 'bilibili':
        if cookie_source:
            return '已使用登录态，清晰度上限取决于账号权限或会员状态'
        return '未检测到登录态，当前可用清晰度可能受限'

    if platform == 'douyin':
        if result.content_type == 'images':
            return f'已识别抖音图文作品，共 {len(result.image_assets)} 张无水印图片'
        if capture_strategy == 'chrome-cookies':
            return '已使用浏览器登录态，当前优先返回可达最高档'
        if capture_strategy == 'no-login':
            return '未登录探测，当前可用清晰度可能受限'

    if len(result.video_streams) <= 1:
        return f'当前仅返回 {len(result.video_streams)} 档清晰度'

    return '自动选择当前可达最高画质'


def infer_source_hint(result: MediaFetchResult) -> str:
    metadata = result.metadata or {}
    platform = result.platform
    resolve_method = str(metadata.get('resolve_method') or '')
    capture_strategy = str(metadata.get('capture_strategy') or '')

    if platform == 'xiaohongshu':
        if resolve_method == 'playwright-fallback':
            return '结构化提取失败，已回退浏览器抓取，清晰度选项可能不完整'
        return '已从页面结构化数据提取视频流'

    if platform == 'weibo':
        if resolve_method == 'playwright-fallback':
            return '微博结构化数据不可用，已回退浏览器抓取'
        return '已从微博页面数据提取视频流'

    if platform == 'channels':
        if resolve_method == 'preview-api-shorturi':
            return '已从视频号分享预览接口提取视频流'
        if resolve_method == 'preview-api-exportid':
            return '已从视频号分享深解析链路提取视频流'
        if resolve_method == 'playwright-fallback':
            return '视频号结构化数据不可用，已回退浏览器抓取'
        return '已从视频号页面变体提取清晰度信息'

    if platform == 'kuaishou':
        if capture_strategy == 'mobile-init-state':
            return '已从快手移动端页面清单提取视频流'

    if platform == 'douyin':
        if result.content_type == 'images':
            return '已从抖音移动端分享页结构化数据提取无水印图片集'
        if capture_strategy == 'share-page':
            return '已从抖音移动端分享页结构化数据提取视频流'
        if capture_strategy == 'chrome-cookies':
            return '已使用浏览器登录态抓取抖音视频流'
        if capture_strategy == 'no-login':
            return '已使用未登录模式抓取抖音视频流'

    if platform == 'bilibili':
        return '已从 B 站播放接口提取视频与音频流'

    return '已完成当前链接的视频流探测'


def build_probe_summary(result: MediaFetchResult) -> dict[str, object]:
    if result.content_type == 'images':
        first = result.image_assets[0] if result.image_assets else None
        return {
            'qualityCount': 0,
            'imageCount': len(result.image_assets),
            'bestResolution': f'{first.width}×{first.height}' if first and first.width and first.height else None,
            'delivery': 'image-collection',
            'sourceHint': infer_source_hint(result),
            'deliveryHint': '将按原顺序逐张保存，并生成不二次压缩的 ZIP',
            'accessHint': infer_access_hint(result),
            'coverAvailable': bool(result.cover_url),
            'subtitleCount': 0,
            'downloadHint': f'已识别 {len(result.image_assets)} 张无水印图片，将保留平台返回的原始文件字节',
        }
    delivery = infer_probe_delivery(result)
    best = result.preferred_video
    best_filesize = best.filesize if best else None
    best_bitrate = best.bitrate if best else None
    return {
        'qualityCount': len(result.video_streams),
        'bestQualityLabel': result.preferred_video.quality_label if result.preferred_video else None,
        'bestResolution': f'{best.width}×{best.height}' if best and best.width and best.height else None,
        'bestContainer': best.container if best else None,
        'bestCodec': best.codec if best else None,
        'bestBitrate': best_bitrate,
        'bestBitrateLabel': f'{round(best_bitrate / 1000)} kbps' if best_bitrate else None,
        'bestFilesize': best_filesize,
        'bestFilesizeLabel': format_bytes(best_filesize) if best_filesize else None,
        'delivery': delivery,
        'sourceHint': infer_source_hint(result),
        'deliveryHint': '当前为 HLS 流，下载时会走 ffmpeg 合流' if delivery == 'hls' else '当前为直链视频流',
        'accessHint': infer_access_hint(result),
        'coverAvailable': bool(result.cover_url),
        'subtitleCount': len(result.subtitle_tracks),
        'downloadHint': (
            '平台未返回文件大小，下载耗时取决于当前 CDN 速度'
            if best and not best_filesize else
            '文件较大，建议确认网络稳定后下载'
            if best_filesize and best_filesize >= 100 * 1024 * 1024 else
            '资源体积较小或中等，可直接下载'
            if best else '未发现视频流'
        ),
    }


def serialize_probe_result(result: MediaFetchResult) -> dict[str, object]:
    ranked = recommendations(result.video_streams)
    preferred_url = result.preferred_video.url if result.preferred_video else None
    serialized_video_streams = enrich_serialized_streams(
        [serialize_stream(stream) for stream in result.video_streams],
        preferred_url,
    )
    stream_by_url = {str(stream.get('url')): stream for stream in serialized_video_streams if stream.get('url')}

    def recommendation(strategy: str) -> dict[str, object] | None:
        item = ranked[strategy]
        if item is None:
            return None
        serialized = stream_by_url.get(item.stream.url) or serialize_stream(item.stream)
        return {
            'strategy': strategy,
            'score': round(item.score, 2),
            'reason': item.reason,
            'stream': serialized,
        }

    probe_summary = build_probe_summary(result)
    if result.preferred_video and result.preferred_video.url in stream_by_url:
        preferred_stream = stream_by_url[result.preferred_video.url]
        if preferred_stream.get('filesize') and not probe_summary.get('bestFilesize'):
            probe_summary['bestFilesize'] = preferred_stream.get('filesize')
            probe_summary['bestFilesizeLabel'] = preferred_stream.get('filesizeLabel')
            probe_summary['downloadHint'] = (
                '文件较大，建议确认网络稳定后下载'
                if int(preferred_stream.get('filesize') or 0) >= 100 * 1024 * 1024
                else '资源体积较小或中等，可直接下载'
            )

    return {
        'success': True,
        'platform': result.platform,
        'title': result.title,
        'contentType': result.content_type,
        'sourceUrl': result.source_url,
        'finalUrl': result.final_url,
        'coverUrl': result.cover_url,
        'author': result.author,
        'metadata': safe_metadata(result.metadata),
        'videoInfo': infer_video_info(result),
        'subtitleTracks': [serialize_subtitle_track(track) for track in result.subtitle_tracks],
        'assetSummary': {
            'coverAvailable': bool(result.cover_url),
            'subtitleCount': len(result.subtitle_tracks),
            'imageCount': len(result.image_assets),
        },
        'imageAssets': [serialize_image_asset(image) for image in result.image_assets],
        'videoStreams': serialized_video_streams,
        'audioStreams': [serialize_stream(stream) for stream in result.audio_streams],
        'preferredVideoQuality': result.preferred_video.quality_label if result.preferred_video else None,
        'recommendations': {
            key: recommendation(key)
            for key in ('best_quality', 'best_compatibility', 'smallest_size')
        },
        'probeSummary': probe_summary,
    }


@contextmanager
def bilibili_cookie_env(raw_cookie: str | None = None, cookie_file: str | None = None):
    tokens = set_manual_cookie_overrides(raw_cookie, cookie_file)
    try:
        yield
    finally:
        reset_manual_cookie_overrides(tokens)


def build_subprocess_env(*, raw_cookie: str | None = None, cookie_file: str | None = None) -> dict[str, str]:
    env = network_subprocess_environment()
    env['PATH'] = augmented_path(env.get('PATH'))
    if raw_cookie:
        env['BILIBILI_COOKIE'] = raw_cookie
    else:
        env.pop('BILIBILI_COOKIE', None)
    if cookie_file:
        env['BILIBILI_COOKIE_FILE'] = cookie_file
    else:
        env.pop('BILIBILI_COOKIE_FILE', None)
    return env


def format_bytes(value: int) -> str:
    if value >= 1024 * 1024 * 1024:
        return f'{value / 1024 / 1024 / 1024:.1f}GB'
    if value >= 1024 * 1024:
        return f'{value / 1024 / 1024:.0f}MB'
    if value >= 1024:
        return f'{value / 1024:.0f}KB'
    return f'{value}B'


def public_error_message(raw_error: str | None, *, fallback: str = '操作失败') -> str:
    """Return a concise user-facing error without leaking a Python traceback."""
    return str(classify_error(raw_error, fallback=fallback)['message'])


async def save_upload_with_limits(
    upload: UploadFile,
    destination: Path,
    *,
    max_file_bytes: int | None = None,
    current_total_bytes: int = 0,
    max_total_bytes: int | None = None,
) -> int:
    effective_max_file_bytes = MAX_CONVERT_FILE_BYTES if max_file_bytes is None else max_file_bytes
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with destination.open('wb') as output:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            written += len(chunk)
            if written > effective_max_file_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f'上传文件超过单文件上限 {format_bytes(effective_max_file_bytes)}：{upload.filename or "input"}',
                )
            if max_total_bytes is not None and current_total_bytes + written > max_total_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f'批量上传总大小超过上限 {format_bytes(max_total_bytes)}',
                )
            output.write(chunk)
    return written


def run_media_fetch(payload: dict[str, object]) -> dict[str, object]:
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        '--link', str(payload.get('link') or ''),
        '--outputPath', str(payload.get('outputPath') or ''),
        '--outputType', str(payload.get('outputType') or ''),
    ]
    video_quality = str(payload.get('videoQuality') or '').strip()
    if video_quality:
        command.extend(['--videoQuality', video_quality])
    if bool(payload.get('saveAssets')):
        command.append('--saveAssets')
    subtitle_strategy = str(payload.get('subtitleStrategy') or '').strip()
    if subtitle_strategy:
        command.extend(['--subtitleStrategy', subtitle_strategy])
    task_id = str(payload.get('_taskId') or '').strip()
    should_defer_subtitles = (
        bool(task_id)
        and bool(payload.get('saveAssets'))
        and str(payload.get('outputType') or '') in {'mp4', 'mkv', 'mov', 'webm'}
        and (subtitle_strategy or 'native-asr-ocr') in {'native-asr', 'native-asr-ocr', 'ocr'}
    )
    if should_defer_subtitles:
        command.append('--deferGeneratedSubtitles')

    env = build_subprocess_env(
        raw_cookie=str(payload.get('bilibiliCookie') or '').strip() or None,
        cookie_file=str(payload.get('bilibiliCookieFile') or '').strip() or None,
    )
    if task_id:
        env['STREAMDOCK_TASK_ID'] = task_id
    try:
        if not task_id:
            completed = subprocess.run(
                command,
                cwd=str(BASE_DIR),
                text=True,
                capture_output=True,
                env=env,
                timeout=MEDIA_TIMEOUT_SECONDS,
            )
            returncode = completed.returncode
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()
        else:
            process = subprocess.Popen(
                command,
                cwd=str(BASE_DIR),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
            with _media_process_lock:
                _media_processes[task_id] = process
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []

            def consume(stream, sink: list[str], *, report_progress: bool = False) -> None:
                if stream is None:
                    return
                for line in iter(stream.readline, ''):
                    clean = line.rstrip()
                    sink.append(clean)
                    if report_progress:
                        match = PROGRESS_PATTERN.search(clean)
                        if match:
                            progress_value = float(match.group(1)) if match.group(1) else None
                            stage = match.group(2).strip()
                            current = task_store.get(task_id)
                            logs = list(current.logs if current else [])
                            if not logs or logs[-1] != stage:
                                logs.append(stage)
                            task_store.update(task_id, logs=logs[-40:], stage=stage, progress=progress_value)

            stdout_thread = Thread(target=consume, args=(process.stdout, stdout_lines), kwargs={'report_progress': True}, daemon=True)
            stderr_thread = Thread(target=consume, args=(process.stderr, stderr_lines), daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            started = monotonic()
            last_activity = started
            observed_output_lines = 0
            try:
                while process.poll() is None:
                    current_output_lines = len(stdout_lines) + len(stderr_lines)
                    if current_output_lines > observed_output_lines:
                        last_activity = monotonic()
                        observed_output_lines = current_output_lines
                    now = monotonic()
                    if now - started > MEDIA_TIMEOUT_SECONDS:
                        terminate_media_process(task_id)
                        raise subprocess.TimeoutExpired(command, MEDIA_TIMEOUT_SECONDS)
                    if now - last_activity > MEDIA_IDLE_TIMEOUT_SECONDS:
                        terminate_media_process(task_id)
                        raise subprocess.TimeoutExpired(command, MEDIA_IDLE_TIMEOUT_SECONDS)
                    sleep(.2)
                stdout_thread.join(timeout=2)
                stderr_thread.join(timeout=2)
                returncode = process.returncode
                stdout = '\n'.join(stdout_lines).strip()
                stderr = '\n'.join(stderr_lines).strip()
            finally:
                with _media_process_lock:
                    _media_processes.pop(task_id, None)
    except subprocess.TimeoutExpired:
        if task_id:
            terminate_media_process(task_id)
            cleanup_task_partials(Path(str(payload.get('outputPath') or '')).expanduser(), task_id)
        return {
            'success': False,
            'stdout': '',
            'stderr': '',
            'returncode': None,
            'outputPath': None,
            'platform': None,
            'error': f'视频解析超时（timeout，总超时 {MEDIA_TIMEOUT_SECONDS} 秒 / 空闲超时 {MEDIA_IDLE_TIMEOUT_SECONDS} 秒），已终止任务',
        }

    output_file = extract_output_file(stdout)
    platform = extract_platform(stdout)
    title = extract_first_match(stdout, TITLE_PATTERN)
    cover_url = extract_first_match(stdout, COVER_URL_PATTERN)
    cover_file = extract_first_match(stdout, COVER_FILE_PATTERN)
    subtitle_files = extract_all_matches(stdout, SUBTITLE_FILE_PATTERN)
    subtitle_details = [
        {'source': match.group(1).strip(), 'quality': match.group(2).strip(), 'path': match.group(3).strip()}
        for match in SUBTITLE_DETAIL_PATTERN.finditer(stdout)
    ]
    subtitle_count_raw = extract_first_match(stdout, SUBTITLE_COUNT_PATTERN)
    subtitle_count = int(subtitle_count_raw) if subtitle_count_raw and subtitle_count_raw.isdigit() else len(subtitle_files)
    subtitle_pending_raw = extract_first_match(stdout, SUBTITLE_PENDING_PATTERN)
    subtitle_pending = str(subtitle_pending_raw or '').lower() == 'true'
    media_kind = extract_first_match(stdout, MEDIA_KIND_PATTERN)
    image_files = extract_all_matches(stdout, IMAGE_FILE_PATTERN)
    image_count_raw = extract_first_match(stdout, IMAGE_COUNT_PATTERN)
    image_count = int(image_count_raw) if image_count_raw and image_count_raw.isdigit() else len(image_files)
    success = returncode == 0
    validation = None
    if success and output_file:
        try:
            if media_kind == 'images':
                archive = Path(output_file)
                if not archive.is_file() or archive.suffix.lower() != '.zip':
                    raise RuntimeError('图片集输出压缩包不存在')
                with zipfile.ZipFile(archive) as bundle:
                    names = [name for name in bundle.namelist() if not name.endswith('/')]
                    if bundle.testzip() is not None or len(names) != image_count:
                        raise RuntimeError('图片集输出压缩包校验失败')
                validation = {
                    'valid': True,
                    'kind': 'images',
                    'imageCount': image_count,
                    'archiveFormat': 'zip',
                    'sizeBytes': archive.stat().st_size,
                }
            else:
                output_kind = 'video' if str(payload.get('outputType') or '') in {'mp4', 'mkv', 'mov', 'webm'} else 'audio'
                validation = validate_media_output(Path(output_file), expected_kind=output_kind)
        except Exception as exc:
            success = False
            stderr = str(exc)
    if media_kind == 'images':
        subtitle_job = {
            'status': 'skipped',
            'message': '图文作品不需要字幕处理',
            'strategy': None,
        }
    elif not bool(payload.get('saveAssets')):
        subtitle_job = {
            'status': 'not_requested',
            'message': '未开启字幕保存',
            'strategy': subtitle_strategy or 'native-asr-ocr',
        }
    elif subtitle_pending:
        subtitle_job = {
            'status': 'pending',
            'message': '视频已下载，字幕将在后台识别',
            'strategy': subtitle_strategy or 'native-asr-ocr',
        }
    elif subtitle_files:
        subtitle_job = {
            'status': 'completed',
            'message': '字幕已保存',
            'strategy': subtitle_strategy or 'native-asr-ocr',
        }
    elif str(payload.get('outputType') or '') not in {'mp4', 'mkv', 'mov', 'webm'}:
        subtitle_job = {
            'status': 'skipped',
            'message': '音频导出任务不生成画面字幕',
            'strategy': subtitle_strategy or 'native-asr-ocr',
        }
    else:
        subtitle_job = {
            'status': 'unavailable',
            'message': '当前策略未生成字幕',
            'strategy': subtitle_strategy or 'native-asr-ocr',
        }
    body: dict[str, object] = {
        'success': success,
        'downloadCompleted': success and bool(output_file),
        'stdout': stdout,
        'stderr': stderr,
        'returncode': returncode,
        'outputPath': output_file,
        'platform': platform,
        'title': title,
        'coverUrl': cover_url,
        'mediaKind': media_kind,
        'imageCount': image_count,
        'subtitleCount': subtitle_count,
        'subtitleJob': subtitle_job,
        'assets': {
            'cover': cover_file,
            'subtitles': subtitle_files,
            'subtitleDetails': subtitle_details,
            'images': image_files,
            'archive': output_file if media_kind == 'images' else None,
        },
        'validation': validation,
    }
    if not success:
        error_info = classify_error(stderr or stdout, fallback='解析失败')
        body['error'] = error_info['message']
        body['errorCode'] = error_info['code']
        body['errorInfo'] = error_info
        # 不把完整 Python traceback 传给前端或任务中心。
        body['stderr'] = body['error']
        if 'traceback (most recent call last)' in stdout.lower():
            body['stdout'] = ''
    return body


def terminate_media_process(task_id: str) -> bool:
    with _media_process_lock:
        process = _media_processes.get(task_id)
    if process is None or process.poll() is not None:
        return False
    try:
        if sys.platform != 'win32':
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if sys.platform != 'win32':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        return True
    except (OSError, ProcessLookupError):
        return False


def terminate_pdf_process(task_id: str) -> bool:
    with _pdf_process_lock:
        process = _pdf_processes.get(task_id)
    if process is None or process.poll() is not None:
        return False
    try:
        if sys.platform != 'win32':
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        return True
    except (OSError, ProcessLookupError):
        return False


def run_subtitle_recognition(payload: dict[str, object]) -> dict[str, object]:
    """Generate optional subtitle sidecars without delaying the completed video task."""
    video_path = Path(str(payload.get('inputPath') or '')).expanduser().resolve()
    if not video_path.exists() or not video_path.is_file():
        raise FileNotFoundError('视频文件不存在，无法继续识别字幕')
    strategy = str(payload.get('strategy') or 'native-asr-ocr').strip().lower()
    output_dir = video_path.parent
    base_name = video_path.stem
    subtitles: list[str] = []
    details: list[dict[str, object]] = []
    errors: list[str] = []

    if strategy in {'native-asr', 'native-asr-ocr'}:
        if asr_available():
            try:
                asr_path = available_output_path(output_dir, f'{base_name}_subtitle_asr', 'srt')
                generated = generate_asr_subtitle_file(video_path, asr_path)
                if generated:
                    subtitles.append(str(generated))
                    details.append({
                        'path': str(generated),
                        'source': 'speech-asr',
                        'quality': 'medium',
                        'language': os.getenv('STREAMDOCK_SUBTITLE_ASR_LANG', 'zh'),
                        'label': '语音识别字幕',
                    })
            except Exception as exc:
                errors.append(f'语音识别失败：{exc}')
        else:
            errors.append('本机未安装可用的 Whisper 语音识别引擎')

    if not subtitles and strategy in {'native-asr-ocr', 'ocr'}:
        if ocr_available():
            try:
                ocr_path = available_output_path(output_dir, f'{base_name}_subtitle_ocr', 'srt')
                generated = generate_ocr_subtitle_file(video_path, ocr_path)
                if generated:
                    subtitles.append(str(generated))
                    details.append({
                        'path': str(generated),
                        'source': 'screen-ocr',
                        'quality': 'low',
                        'language': os.getenv('STREAMDOCK_SUBTITLE_OCR_LANG', 'chi_sim+eng'),
                        'label': '画面 OCR 字幕（可能不准确）',
                    })
            except Exception as exc:
                errors.append(f'画面字幕识别失败：{exc}')
        elif strategy == 'ocr':
            errors.append('本机未安装可用的 OCR 字幕引擎')

    if not subtitles and strategy == 'native-asr-ocr':
        try:
            title = str(payload.get('title') or base_name).strip()
            source_url = str(payload.get('sourceUrl') or '').strip()
            platform = str(payload.get('platform') or 'unknown').strip()
            fallback_result = MediaFetchResult(
                platform=platform,
                content_type='video',
                title=title,
                source_url=source_url,
                final_url=source_url,
                cover_url=None,
                author=None,
                metadata={'description': title},
            )
            validation = payload.get('validation') if isinstance(payload.get('validation'), dict) else {}
            duration = float((validation or {}).get('durationSeconds') or 0)
            text_path = available_output_path(output_dir, f'{base_name}_subtitle_text', 'srt')
            generated = generate_metadata_subtitle_file(fallback_result, text_path, duration_seconds=duration)
            if generated:
                subtitles.append(str(generated))
                details.append({
                    'path': str(generated),
                    'source': 'metadata-text',
                    'quality': 'low',
                    'language': None,
                    'label': '平台文案兜底（无可识别语音/字幕轨）',
                })
        except Exception as exc:
            errors.append(f'平台文案兜底失败：{exc}')

    if subtitles:
        source = str(details[0].get('source') or '') if details else ''
        message = {
            'speech-asr': '语音字幕识别完成，字幕文件已保存',
            'screen-ocr': '画面字幕识别完成，字幕文件已保存',
            'metadata-text': '未获得可用识别字幕，已保存平台文案兜底',
        }.get(source, '字幕文件已保存')
        return {
            'status': 'completed',
            'message': message,
            'subtitles': subtitles,
            'subtitleDetails': details,
        }

    return {
        'status': 'unavailable',
        'message': '未生成字幕，视频文件仍可正常打开',
        'error': '；'.join(errors) if errors else None,
        'subtitles': [],
        'subtitleDetails': [],
    }


def enqueue_subtitle_after_media_success(
    task_id: str,
    payload: dict[str, object],
    result: dict[str, object],
) -> None:
    subtitle_job = result.get('subtitleJob') if isinstance(result.get('subtitleJob'), dict) else {}
    if subtitle_job.get('status') != 'pending':
        return
    subtitle_queue.submit(task_id, {
        'inputPath': result.get('outputPath'),
        'strategy': subtitle_job.get('strategy') or payload.get('subtitleStrategy') or 'native-asr-ocr',
        'title': result.get('title'),
        'platform': result.get('platform'),
        'sourceUrl': payload.get('link'),
        'validation': result.get('validation') or {},
    })


def run_pdf_task(payload: dict[str, object]) -> dict[str, object]:
    task_id = str(payload.get('_taskId') or '')
    input_path = Path(str(payload.get('inputPath') or '')).expanduser().resolve()
    output_dir = Path(str(payload.get('outputPath') or '')).expanduser().resolve()
    requested_mode = PdfParseMode(str(payload.get('mode') or 'auto'))

    def register_process(process: subprocess.Popen[str]) -> None:
        with _pdf_process_lock:
            _pdf_processes[task_id] = process
        current = task_store.get(task_id)
        logs = list(current.logs if current else [])
        current_mode = str(payload.get('_currentMode') or requested_mode.value)
        task_store.update(task_id, logs=[*logs, '文档模型已启动'], stage=f'{current_mode.upper()} 解析中', progress=None)

    try:
        analysis = analyze_pdf(input_path)
        if requested_mode == PdfParseMode.AUTO:
            first_mode = analysis.recommended_mode if analysis.recommended_mode != PdfParseMode.AUTO else PdfParseMode.FAST
            attempts = [first_mode]
            if first_mode == PdfParseMode.FAST:
                attempts.append(PdfParseMode.OCR)
            attempts.append(PdfParseMode.PRECISE)
        else:
            attempts = [requested_mode]
        attempts = list(dict.fromkeys(attempts))
        fallback_history: list[dict[str, object]] = []
        parsed = None
        quality = None
        for index, attempt_mode in enumerate(attempts):
            payload['_currentMode'] = attempt_mode.value
            if output_dir.exists():
                shutil.rmtree(output_dir)
            task_store.update(task_id, stage=f'{attempt_mode.value.upper()} 解析中', progress=None, logs=[f'策略 {index + 1}/{len(attempts)}：{attempt_mode.value}'])
            parsed = parse_pdf(input_path, output_dir, attempt_mode, process_callback=register_process)
            task_store.update(task_id, stage='正在校验解析结果', progress=88 + index * 2)
            quality = evaluate_pdf_result(output_dir)
            fallback_history.append({'mode': attempt_mode.value, 'score': quality['score'], 'valid': quality['valid']})
            if quality['valid']:
                break
        if parsed is None or quality is None or not quality['valid']:
            raise RuntimeError('PDF 解析结果质量校验未通过')
        markdown = next(iter(output_dir.rglob('*.md')), None)
        preview = markdown.read_text(encoding='utf-8', errors='replace')[:6000] if markdown else ''
        return {
            'success': True,
            'provider': parsed.provider,
            'mode': parsed.mode.value,
            'outputPath': parsed.output_dir,
            'files': parsed.files,
            'metadata': parsed.metadata,
            'quality': quality,
            'strategy': {'requestedMode': requested_mode.value, 'attempts': fallback_history, 'finalMode': parsed.mode.value},
            'preview': preview,
            'logs': [f'生成 {len(parsed.files)} 个文件', f'质量评分 {quality["score"]}'],
        }
    finally:
        with _pdf_process_lock:
            _pdf_processes.pop(task_id, None)


subtitle_queue = SubtitleQueue(task_store, run_subtitle_recognition)
media_queue = MediaQueue(task_store, run_media_fetch, success_hook=enqueue_subtitle_after_media_success)
pdf_queue = PdfQueue(task_store, run_pdf_task)


@app.get('/api/health')
def health(outputPath: str | None = None):
    return JSONResponse({'success': True, **environment_health(outputPath)})


@app.get('/api/platform-status')
def platform_status():
    registered = {'douyin', 'kuaishou', 'bilibili', 'xiaohongshu', 'weibo', 'channels', 'youtube', 'tiktok', 'twitter_x'}
    latest: dict[str, dict[str, object]] = {}
    for task in task_store.list(TaskKind.MEDIA):
        result = task.result or {}
        platform = str(result.get('platform') or task.payload.get('platform') or '').strip()
        if not platform or platform in latest:
            continue
        latest[platform] = {
            'lastStatus': task.status.value,
            'lastCheckedAt': task.updated_at,
            'validationPassed': bool((result.get('validation') or {}).get('valid')),
        }
    rows = []
    for platform in sorted(registered):
        recent = latest.get(platform)
        rows.append({
            'platform': platform,
            'registered': True,
            'runtimeStatus': (
                'verified' if recent and recent['lastStatus'] == 'completed' and recent['validationPassed']
                else 'failed' if recent and recent['lastStatus'] == 'failed'
                else 'unverified'
            ),
            **(recent or {}),
        })
    return JSONResponse({'success': True, 'platforms': rows})


@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        'home.html',
        {
            'request': request,
            'title': 'StreamDock · 多平台媒体解析工具',
            'active_nav': 'home',
        },
    )


@app.get('/use', response_class=HTMLResponse)
def use_page(request: Request):
    return templates.TemplateResponse(
        'use.html',
        {
            'request': request,
            'title': 'StreamDock · 在线使用',
            'active_nav': 'use',
        },
    )


@app.get('/platforms', response_class=HTMLResponse)
def platforms_page(request: Request):
    return templates.TemplateResponse(
        'platforms.html',
        {
            'request': request,
            'title': 'StreamDock · 支持平台',
            'active_nav': 'platforms',
        },
    )


@app.get('/about', response_class=HTMLResponse)
def about_page(request: Request):
    return templates.TemplateResponse(
        'about.html',
        {
            'request': request,
            'title': 'StreamDock · 产品介绍',
            'active_nav': '',
        },
    )


@app.get('/updates', response_class=HTMLResponse)
def updates_page(request: Request):
    return templates.TemplateResponse(
        'updates.html',
        {
            'request': request,
            'title': 'StreamDock · 更新日志',
            'active_nav': 'updates',
        },
    )


@app.get('/convert', response_class=HTMLResponse)
def convert_page(request: Request):
    return templates.TemplateResponse(
        'convert.html',
        {
            'request': request,
            'title': 'StreamDock · 文件转换',
            'active_nav': 'convert',
        },
    )


@app.get('/pdf', response_class=HTMLResponse)
def pdf_page(request: Request):
    return templates.TemplateResponse(
        'pdf.html',
        {
            'request': request,
            'title': 'StreamDock · PDF 智能解析',
            'active_nav': 'pdf',
        },
    )


@app.get('/subtitles', response_class=HTMLResponse)
def subtitles_page(request: Request):
    return templates.TemplateResponse(
        'subtitles.html',
        {'request': request, 'title': 'StreamDock · 字幕工作台', 'active_nav': 'subtitles'},
    )


def decode_subtitle_bytes(content: bytes) -> str:
    if len(content) > MAX_SUBTITLE_FILE_BYTES:
        raise ValueError('字幕文件不能超过 5MB')
    for encoding in ('utf-8-sig', 'utf-16', 'gb18030'):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError('字幕文件编码无法识别，请转换为 UTF-8 后重试')


@app.post('/api/subtitles/import')
async def subtitle_import(file: UploadFile = File(...)):
    filename = Path(file.filename or 'subtitle.srt').name
    try:
        normalize_subtitle_format(filename)
        content = await file.read(MAX_SUBTITLE_FILE_BYTES + 1)
        document = parse_subtitles(decode_subtitle_bytes(content), filename=filename)
    except ValueError as exc:
        return JSONResponse({'success': False, 'error': str(exc)}, status_code=400)
    return JSONResponse({'success': True, 'document': document.to_dict()})


@app.post('/api/subtitles/parse')
def subtitle_parse_text(payload: SubtitleTextRequest):
    try:
        document = parse_subtitles(payload.text, filename=Path(payload.filename).name, format=payload.format)
    except ValueError as exc:
        return JSONResponse({'success': False, 'error': str(exc)}, status_code=400)
    return JSONResponse({'success': True, 'document': document.to_dict()})


@app.post('/api/subtitles/export')
def subtitle_export(payload: SubtitleExportRequest):
    try:
        target_format = normalize_subtitle_format(f'subtitle.{payload.format}', payload.format)
        content = export_subtitles([cue.model_dump() for cue in payload.cues], target_format)
    except (OverflowError, TypeError, ValueError) as exc:
        return JSONResponse({'success': False, 'error': str(exc)}, status_code=400)
    safe_name = re.sub(r'[^\w\-.\u4e00-\u9fff]+', '_', Path(payload.filename).stem).strip('._') or 'subtitle'
    download_name = f'{safe_name}.{target_format}'
    ascii_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', download_name).strip('._') or f'subtitle.{target_format}'
    media_type = 'text/vtt' if target_format == 'vtt' else 'text/plain'
    headers = {'Content-Disposition': f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(download_name, safe='')}"}
    return Response(content.encode('utf-8'), media_type=f'{media_type}; charset=utf-8', headers=headers)


def select_output_directory_with_system_dialog() -> tuple[bool, str | None, str | None]:
    if sys.platform != 'darwin':
        return False, None, '当前仅支持在 macOS 本地弹出目录选择窗口'

    script = (
        'set selectedFolder to choose folder with prompt "选择 StreamDock 保存目录"\n'
        'return POSIX path of selectedFolder'
    )
    try:
        completed = subprocess.run(
            ['osascript', '-e', script],
            text=True,
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, None, '目录选择超时，请重新点击选择目录'
    except OSError as exc:
        return False, None, f'无法打开系统目录选择窗口：{exc}'

    selected_path = completed.stdout.strip()
    if completed.returncode != 0 or not selected_path:
        return False, None, '已取消目录选择'
    return True, selected_path.rstrip('/'), None


@app.post('/api/select-output-dir')
def select_output_dir():
    success, selected_path, error = select_output_directory_with_system_dialog()
    return JSONResponse(
        {
            'success': success,
            'path': selected_path,
            'error': error,
        }
    )


@app.get('/api/convert/capabilities')
def convert_capabilities():
    capabilities = [cap.to_dict() for cap in list_capabilities()]
    return JSONResponse({'success': True, 'capabilities': capabilities})


@app.post('/api/convert/probe')
async def convert_probe(file: UploadFile = File(...)):
    filename = file.filename or 'input'
    declared_source = infer_input_format(filename)
    with tempfile.TemporaryDirectory(prefix='streamdock_probe_') as tmp_dir:
        input_path = Path(tmp_dir) / Path(filename).name
        try:
            await save_upload_with_limits(file, input_path)
        finally:
            await file.close()
        valid, detected_source = validate_declared_format(input_path, declared_source)
    if not valid:
        return JSONResponse(
            {
                'success': False,
                'error': f'文件内容与扩展名不一致：扩展名为 {declared_source.upper()}，内容识别为 {(detected_source or "未知").upper()}',
                'filename': filename,
                'source': declared_source,
                'detectedSource': detected_source,
                'options': [],
                'supported': False,
            },
            status_code=400,
        )
    source = declared_source
    options = [cap.to_dict() for cap in targets_for_source(source)]
    return JSONResponse(
        {
            'success': True,
            'filename': filename,
            'source': source,
            'detectedSource': detected_source,
            'options': options,
            'supported': bool(options),
        }
    )


@app.post('/api/convert/batch-probe')
async def convert_batch_probe(files: list[UploadFile] = File(...)):
    if len(files) > MAX_CONVERT_BATCH_FILES:
        for file in files:
            await file.close()
        raise HTTPException(status_code=413, detail=f'批量转换一次最多选择 {MAX_CONVERT_BATCH_FILES} 个文件')
    filenames = [file.filename or 'input' for file in files]
    if not filenames:
        return JSONResponse({'success': False, 'error': '请先选择至少一个文件', 'files': []})
    response_files: list[dict[str, object]] = []
    total_bytes = 0
    with tempfile.TemporaryDirectory(prefix='streamdock_batch_probe_') as tmp_dir:
        tmp_path = Path(tmp_dir)
        for index, (upload, name) in enumerate(zip(files, filenames)):
            declared = infer_input_format(name)
            input_path = tmp_path / f'{index}_{Path(name).name}'
            try:
                written = await save_upload_with_limits(
                    upload,
                    input_path,
                    current_total_bytes=total_bytes,
                    max_total_bytes=MAX_CONVERT_BATCH_TOTAL_BYTES,
                )
            finally:
                await upload.close()
            total_bytes += written
            valid, detected = validate_declared_format(input_path, declared)
            response_files.append({'filename': Path(name).name, 'source': declared, 'detectedSource': detected, 'valid': valid})

    invalid_files = [item for item in response_files if not item['valid']]
    if invalid_files:
        names = '、'.join(str(item['filename']) for item in invalid_files)
        return JSONResponse({'success': False, 'error': f'以下文件内容与扩展名不一致：{names}', 'files': response_files}, status_code=400)

    sources = sorted({str(item['source']) for item in response_files})
    if len(sources) != 1:
        return JSONResponse(
            {
                'success': False,
                'error': '批量转换第一版要求所有文件使用同一种输入格式',
                'files': response_files,
            }
        )

    source = sources[0]
    options = [cap.to_dict() for cap in targets_for_source(source)]
    return JSONResponse(
        {
            'success': True,
            'fileCount': len(filenames),
            'source': source,
            'files': response_files,
            'options': options,
            'supported': bool(options),
        }
    )


@app.post('/api/convert/run')
async def convert_run(
    file: UploadFile = File(...),
    outputType: str = Form(...),
    outputPath: str = Form(...),
    inputType: str | None = Form(None),
    namingStrategy: str = Form('append'),
):
    filename = file.filename or 'input'
    source = inputType or infer_input_format(filename)
    target = outputType
    capability = find_capability(source, target)
    if capability is None:
        await file.close()
        return JSONResponse({'success': False, 'error': f'暂不支持 {source.upper()} → {target.upper()} 转换路径', 'logs': []})
    with tempfile.TemporaryDirectory(prefix='streamdock_convert_') as tmp_dir:
        input_path = Path(tmp_dir) / Path(filename).name
        try:
            await save_upload_with_limits(file, input_path)
        finally:
            await file.close()
        valid, detected = validate_declared_format(input_path, source)
        if not valid:
            return JSONResponse(
                {'success': False, 'error': f'文件内容与输入格式不一致：声明为 {source.upper()}，内容识别为 {(detected or "未知").upper()}', 'logs': []},
                status_code=400,
            )
        task = task_store.create(
            TaskKind.CONVERT,
            f'{Path(filename).name} → {normalize_format(target).upper()}',
            {'filename': Path(filename).name, 'source': source, 'target': target, 'outputPath': outputPath},
        )
        task_store.update(task.id, status=TaskStatus.RUNNING, logs=['正在转换文件'], stage='转换中', progress=15)
        result = await asyncio.to_thread(
            convert_file_with_timeout,
            input_path,
            filename,
            source,
            target,
            Path(outputPath).expanduser(),
            timeout_seconds=CONVERT_TIMEOUT_SECONDS,
            naming_strategy=namingStrategy,
        )
    body = result.to_dict()
    body['capability'] = capability.to_dict()
    task_store.update(
        task.id,
        status=TaskStatus.COMPLETED if result.success else TaskStatus.FAILED,
        logs=list(result.logs),
        result=body,
        error=result.error,
        stage='已完成' if result.success else '失败',
        progress=100 if result.success else None,
    )
    body['task'] = task_store.get(task.id).to_dict() if task_store.get(task.id) else None
    return JSONResponse(body)


@app.post('/api/convert/batch-run')
async def convert_batch_run(
    files: list[UploadFile] = File(...),
    outputType: str = Form(...),
    outputPath: str = Form(...),
    inputType: str | None = Form(None),
    namingStrategy: str = Form('append'),
):
    filenames = [file.filename or 'input' for file in files]
    if len(files) > MAX_CONVERT_BATCH_FILES:
        for file in files:
            await file.close()
        raise HTTPException(status_code=413, detail=f'批量转换一次最多选择 {MAX_CONVERT_BATCH_FILES} 个文件')
    validation = validate_batch_route(filenames, outputType, input_type=inputType)
    if not validation.success:
        for file in files:
            await file.close()
        return JSONResponse(validation.to_dict())
    if validation.capability and validation.capability.level == ConversionLevel.VENDOR:
        for file in files:
            await file.close()
        return JSONResponse(
            {
                **validation.to_dict(),
                'success': False,
                'error': '该批量转换属于推荐厂商能力，不执行本地转换',
                'vendorRecommendations': list(validation.capability.vendors),
            }
        )

    target = normalize_format(outputType)
    output_dir = Path(outputPath).expanduser()
    tasks = []
    with tempfile.TemporaryDirectory(prefix='streamdock_batch_convert_') as tmp_dir:
        tmp_path = Path(tmp_dir)
        batch_inputs: list[BatchInput] = []
        source_inputs = make_batch_inputs(filenames, input_type=inputType)
        total_bytes = 0
        try:
            for upload, source_input in zip(files, source_inputs):
                safe_name = Path(source_input.filename).name
                input_path = tmp_path / safe_name
                try:
                    written = await save_upload_with_limits(
                        upload,
                        input_path,
                        current_total_bytes=total_bytes,
                        max_total_bytes=MAX_CONVERT_BATCH_TOTAL_BYTES,
                    )
                finally:
                    await upload.close()
                total_bytes += written
                batch_inputs.append(BatchInput(filename=safe_name, source=source_input.source, input_path=input_path))
        except HTTPException:
            for upload in files:
                await upload.close()
            raise

        for item in batch_inputs:
            valid, detected = validate_declared_format(item.input_path, item.source)
            if not valid:
                return JSONResponse(
                    {
                        'success': False,
                        'error': f'{item.filename} 的内容与声明格式 {item.source.upper()} 不一致，内容识别为 {(detected or "未知").upper()}',
                        'tasks': [],
                    },
                    status_code=400,
                )

        for item in batch_inputs:
            task = task_store.create(
                TaskKind.CONVERT,
                f'{item.filename} → {target.upper()}',
                {'filename': item.filename, 'source': item.source, 'target': target, 'outputPath': str(output_dir)},
            )
            task_store.update(task.id, status=TaskStatus.RUNNING, logs=['正在等待批量转换执行'], stage='等待批量转换', progress=5)
            tasks.append(task)

        result = await asyncio.to_thread(
            convert_batch_files,
            batch_inputs,
            target,
            output_dir,
            timeout_seconds=CONVERT_TIMEOUT_SECONDS,
            naming_strategy=namingStrategy,
        )

    rows = result.get('results', [])
    for task, row in zip(tasks, rows):
        status = TaskStatus.COMPLETED if row.get('success') else TaskStatus.FAILED
        task_store.update(
            task.id,
            status=status,
            logs=list(row.get('logs') or []),
            result=dict(row),
            error=str(row.get('error') or '') or None,
            stage='已完成' if row.get('success') else '失败',
            progress=100 if row.get('success') else None,
        )

    return JSONResponse(
        {
            **result,
            'capability': validation.capability.to_dict() if validation.capability else None,
            'tasks': [task_store.get(task.id).to_dict() for task in tasks if task_store.get(task.id)],
        }
    )


@app.post('/api/convert/select-output-dir')
def convert_select_output_dir():
    success, selected_path, error = select_output_directory_with_system_dialog()
    return JSONResponse({'success': success, 'path': selected_path, 'error': error})


@app.get('/api/tasks')
def list_tasks(kind: str | None = None):
    kind_filter: TaskKind | None = None
    if kind:
        try:
            kind_filter = TaskKind(kind)
        except ValueError:
            return JSONResponse({'success': False, 'error': '未知任务类型', 'tasks': []}, status_code=400)
    body: dict[str, object] = {'success': True, 'tasks': [task.to_dict() for task in task_store.list(kind_filter)]}
    if kind_filter in {None, TaskKind.MEDIA}:
        body['mediaQueue'] = {'paused': media_queue.is_paused()}
    return JSONResponse(body)


@app.get('/api/tasks/{task_id}')
def get_task(task_id: str):
    task = task_store.get(task_id)
    if task is None:
        return JSONResponse({'success': False, 'error': '任务不存在'}, status_code=404)
    return JSONResponse({'success': True, 'task': task.to_dict()})


@app.delete('/api/tasks/{task_id}')
def cancel_task(task_id: str):
    task = task_store.get(task_id)
    if task is None:
        return JSONResponse({'success': False, 'error': '任务不存在'}, status_code=404)
    if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}:
        subtitle_job = (task.result or {}).get('subtitleJob')
        if isinstance(subtitle_job, dict) and subtitle_job.get('status') in {'pending', 'running'}:
            return JSONResponse({'success': False, 'error': '视频已可用，但字幕仍在后台识别；请等待字幕任务结束后再删除记录'}, status_code=409)
        deleted = task_store.delete(task_id)
        return JSONResponse({'success': True, 'deleted': True, 'task': deleted.to_dict() if deleted else None})
    if task.kind == TaskKind.PDF:
        if not pdf_queue.cancel(task_id):
            return JSONResponse({'success': False, 'error': '任务已结束，无需取消'}, status_code=409)
        terminate_pdf_process(task_id)
        current = task_store.get(task_id)
        return JSONResponse({'success': True, 'task': current.to_dict() if current else None})
    if task.kind != TaskKind.MEDIA:
        return JSONResponse({'success': False, 'error': '当前转换任务已同步执行，无法取消'}, status_code=409)
    if not media_queue.cancel(task_id):
        return JSONResponse({'success': False, 'error': '任务已结束，无需取消'}, status_code=409)
    terminate_media_process(task_id)
    cleanup_task_partials(Path(str(task.payload.get('outputPath') or '')).expanduser(), task_id)
    current = task_store.get(task_id)
    return JSONResponse({'success': True, 'task': current.to_dict() if current else None})


@app.post('/api/tasks/{task_id}/retry')
def retry_task(task_id: str):
    task = task_store.get(task_id)
    if task is None:
        return JSONResponse({'success': False, 'error': '任务不存在'}, status_code=404)
    if task.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}:
        return JSONResponse({'success': False, 'error': '只有失败、取消或跳过的任务可以重新执行'}, status_code=409)
    if task.kind != TaskKind.MEDIA:
        return JSONResponse({'success': False, 'error': '转换任务不会保留原始上传文件，请重新选择文件后执行'}, status_code=409)
    payload = dict(task.payload)
    for key in ('bilibiliCookie', 'bilibiliCookieFile'):
        if payload.get(key) == '[REDACTED]':
            payload[key] = None
    payload['retryOf'] = task.id
    submitted = media_queue.submit([payload])
    return JSONResponse({'success': True, 'mode': 'reprobe', 'task': submitted[0]})


@app.post('/api/tasks/media/pause')
def pause_media_tasks():
    media_queue.pause()
    return JSONResponse({'success': True, 'paused': True})


@app.post('/api/tasks/media/resume')
def resume_media_tasks():
    media_queue.resume()
    return JSONResponse({'success': True, 'paused': False})


@app.delete('/api/task-actions/clear-finished')
def clear_finished_tasks(kind: str | None = None):
    kind_filter = None
    if kind:
        try:
            kind_filter = TaskKind(kind)
        except ValueError:
            return JSONResponse({'success': False, 'error': '未知任务类型'}, status_code=400)
    deleted = task_store.clear_finished(kind_filter)
    return JSONResponse({'success': True, 'deleted': deleted})


@app.post('/api/open-output-path')
def open_output_path(path: str = Form(...)):
    target = Path(path).expanduser().resolve()
    directory = target if target.is_dir() else target.parent
    if not directory.exists():
        return JSONResponse({'success': False, 'error': '输出目录不存在'}, status_code=404)
    try:
        if sys.platform == 'darwin':
            subprocess.Popen(['open', str(directory)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform.startswith('linux'):
            subprocess.Popen(['xdg-open', str(directory)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return JSONResponse({'success': False, 'error': '当前系统不支持自动打开目录'}, status_code=400)
    except OSError as exc:
        return JSONResponse({'success': False, 'error': f'打开目录失败：{exc}'}, status_code=500)
    return JSONResponse({'success': True, 'path': str(directory)})


@app.post('/api/open-output-file')
def open_output_file(path: str = Form(...)):
    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_file():
        return JSONResponse({'success': False, 'error': '输出文件不存在'}, status_code=404)
    try:
        if sys.platform == 'darwin':
            subprocess.Popen(['open', str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform.startswith('linux'):
            subprocess.Popen(['xdg-open', str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return JSONResponse({'success': False, 'error': '当前系统不支持自动打开文件'}, status_code=400)
    except OSError as exc:
        return JSONResponse({'success': False, 'error': f'打开文件失败：{exc}'}, status_code=500)
    return JSONResponse({'success': True, 'path': str(target)})


@app.post('/api/probe')
def probe(payload: ProbeRequest):
    try:
        with bilibili_cookie_env(payload.bilibiliCookie, payload.bilibiliCookieFile):
            result = probe_media(payload.link)
    except Exception as exc:
        error_info = classify_error(str(exc), fallback='链接探测失败')
        return JSONResponse(
            {
                'success': False,
                'error': error_info['message'],
                'errorCode': error_info['code'],
                'errorInfo': error_info,
                'platform': None,
                'videoStreams': [],
                'audioStreams': [],
            }
        )
    return JSONResponse(serialize_probe_result(result))


@app.post('/api/media/probe')
def media_probe(payload: ProbeRequest):
    """Stable media-module endpoint; /api/probe remains for compatibility."""
    return probe(payload)




@app.get('/api/media/cover-proxy')
def media_cover_proxy(url: str):
    """Proxy remote platform covers so hotlink protections (notably Bilibili) do not break local previews."""
    try:
        remote_url = normalize_remote_image_url(url)
    except ValueError as exc:
        return JSONResponse({'success': False, 'error': str(exc)}, status_code=400)
    try:
        response = requests.get(remote_url, headers=media_cover_headers(remote_url), timeout=15, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException as exc:
        return JSONResponse({'success': False, 'error': f'封面加载失败：{exc}'}, status_code=502)
    content = response.content[:8 * 1024 * 1024]
    raw_content_type = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    content_type = raw_content_type if raw_content_type.startswith('image/') else sniff_image_media_type(content, raw_content_type or 'image/jpeg')
    if not content_type or not content_type.startswith('image/'):
        return JSONResponse({'success': False, 'error': '远端资源不是图片'}, status_code=415)
    headers = {'Cache-Control': 'public, max-age=3600'}
    return Response(content=content, media_type=content_type, headers=headers)


@app.get('/api/pdf/health')
def pdf_health():
    return JSONResponse({'success': True, **MinerUProvider().health()})


@app.post('/api/media/quality/deep')
async def media_deep_quality(path: str = Form(...)):
    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_file():
        return JSONResponse({'success': False, 'error': '视频文件不存在'}, status_code=404)
    try:
        report = await asyncio.to_thread(deep_media_quality, target)
    except RuntimeError as exc:
        return JSONResponse({'success': False, 'error': str(exc)}, status_code=400)
    return JSONResponse({'success': True, 'report': report})


@app.post('/api/pdf/tasks/{task_id}/archive')
def archive_pdf_result(task_id: str):
    task = task_store.get(task_id)
    if task is None or task.kind != TaskKind.PDF or task.status != TaskStatus.COMPLETED:
        return JSONResponse({'success': False, 'error': '已完成的 PDF 任务不存在'}, status_code=404)
    output = Path(str((task.result or {}).get('outputPath') or '')).expanduser().resolve()
    if not output.is_dir():
        return JSONResponse({'success': False, 'error': '解析结果目录不存在'}, status_code=404)
    archive_path = shutil.make_archive(str(output), 'zip', root_dir=str(output))
    return JSONResponse({'success': True, 'path': archive_path})





@app.get('/api/media/tasks/{task_id}/asset')
def get_media_task_asset(task_id: str, path: str):
    task = task_store.get(task_id)
    if task is None or task.kind != TaskKind.MEDIA:
        return JSONResponse({'success': False, 'error': '视频任务不存在'}, status_code=404)
    result = task.result or {}
    assets = result.get('assets') if isinstance(result.get('assets'), dict) else {}
    allowed = []
    cover = str((assets or {}).get('cover') or '').strip()
    if cover:
        allowed.append(Path(cover).expanduser().resolve())
    for subtitle in (assets or {}).get('subtitles') or []:
        if subtitle:
            allowed.append(Path(str(subtitle)).expanduser().resolve())
    for item in (assets or {}).get('subtitleDetails') or []:
        if isinstance(item, dict) and item.get('path'):
            allowed.append(Path(str(item.get('path'))).expanduser().resolve())
    for image in (assets or {}).get('images') or []:
        if image:
            allowed.append(Path(str(image)).expanduser().resolve())

    requested = Path(path).expanduser().resolve()
    if requested not in allowed:
        return JSONResponse({'success': False, 'error': '该资源不属于当前任务'}, status_code=403)
    if not requested.exists() or not requested.is_file():
        return JSONResponse({'success': False, 'error': '资源文件不存在'}, status_code=404)
    allowed_suffixes = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.vtt', '.srt', '.ass', '.ssa', '.txt', '.json'}
    if requested.suffix.lower() not in allowed_suffixes:
        return JSONResponse({'success': False, 'error': '不支持预览该资源类型'}, status_code=400)
    return FileResponse(requested)


@app.get('/api/pdf/tasks/{task_id}/asset')
def get_pdf_result_asset(task_id: str, path: str):
    task = task_store.get(task_id)
    if task is None or task.kind != TaskKind.PDF or task.status != TaskStatus.COMPLETED:
        return JSONResponse({'success': False, 'error': '已完成的 PDF 任务不存在'}, status_code=404)
    output = Path(str((task.result or {}).get('outputPath') or '')).expanduser().resolve()
    if not output.is_dir():
        return JSONResponse({'success': False, 'error': '解析结果目录不存在'}, status_code=404)

    requested = Path(path)
    image_suffixes = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff'}
    if requested.suffix.lower() not in image_suffixes:
        return JSONResponse({'success': False, 'error': '仅允许预览图片资源'}, status_code=400)

    candidates: list[Path] = []
    if not requested.is_absolute():
        candidates.append((output / requested).resolve())
    # Some engines place Markdown in a subdirectory and use image paths relative to it.
    candidates.extend(path.resolve() for path in output.rglob(requested.name))

    for candidate in candidates:
        try:
            candidate.relative_to(output)
        except ValueError:
            continue
        if candidate.is_file() and candidate.suffix.lower() in image_suffixes:
            return FileResponse(candidate)
    return JSONResponse({'success': False, 'error': '图片资源不存在'}, status_code=404)


@app.get('/api/pdf/tasks/{task_id}/content')
def get_pdf_result_content(task_id: str):
    """Return the complete Markdown result instead of the short task-list preview."""
    task = task_store.get(task_id)
    if task is None or task.kind != TaskKind.PDF or task.status != TaskStatus.COMPLETED:
        return JSONResponse({'success': False, 'error': '已完成的 PDF 任务不存在'}, status_code=404)
    output = Path(str((task.result or {}).get('outputPath') or '')).expanduser().resolve()
    if not output.is_dir():
        return JSONResponse({'success': False, 'error': '解析结果目录不存在'}, status_code=404)
    markdown_files = sorted(output.rglob('*.md'), key=lambda path: (-path.stat().st_size, str(path)))
    if not markdown_files:
        return JSONResponse({'success': False, 'error': '没有找到 Markdown 结果'}, status_code=404)

    sections: list[str] = []
    sources: list[str] = []
    for markdown_path in markdown_files:
        content = markdown_path.read_text(encoding='utf-8', errors='replace')
        if len(markdown_files) > 1:
            sections.append(f'# {markdown_path.stem}\n\n{content}')
        else:
            sections.append(content)
        sources.append(str(markdown_path.relative_to(output)))
    markdown = '\n\n'.join(sections)
    headings = [
        {
            'level': len(match.group(1)),
            'title': re.sub(r'\s+#+\s*$', '', match.group(2)).strip(),
            'offset': match.start(),
        }
        for match in re.finditer(r'(?m)^(#{1,6})\s+(.+?)\s*$', markdown)
    ]
    return JSONResponse({
        'success': True,
        'content': markdown,
        'headings': headings,
        'sources': sources,
        'characters': len(markdown),
    })


@app.post('/api/pdf/analyze')
async def pdf_analyze(file: UploadFile = File(...)):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix != '.pdf':
        raise HTTPException(status_code=400, detail='请选择 PDF 文件')
    with tempfile.TemporaryDirectory(prefix='streamdock-pdf-analyze-') as temp_dir:
        input_path = Path(temp_dir) / (Path(file.filename or 'document.pdf').name)
        await save_upload_with_limits(file, input_path)
        try:
            analysis = await asyncio.to_thread(analyze_pdf, input_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = asdict(analysis)
    payload['recommended_mode'] = analysis.recommended_mode.value
    return JSONResponse({'success': True, 'analysis': payload, 'engine': MinerUProvider().health()})


@app.post('/api/pdf/parse')
async def pdf_parse(
    file: UploadFile = File(...),
    outputPath: str = Form(...),
    mode: str = Form('auto'),
):
    try:
        parse_mode = PdfParseMode(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='不支持的 PDF 解析模式') from exc
    output_root = Path(outputPath).expanduser().resolve()
    prepare_output_directory(output_root)
    safe_name = re.sub(r'[^\w\-.\u4e00-\u9fff]+', '_', Path(file.filename or 'document.pdf').stem).strip('._') or 'document'
    task_token = uuid4().hex[:10]
    result_dir = output_root / f'{safe_name}_parsed_{task_token}'
    input_root = Path.home() / '.streamdock' / 'pdf-inputs'
    input_path = input_root / f'{task_token}_{safe_name}.pdf'
    try:
        await save_upload_with_limits(file, input_path)
        analyze_pdf(input_path)
        task = pdf_queue.submit({
            'filename': file.filename or f'{safe_name}.pdf',
            'inputPath': str(input_path),
            'outputPath': str(result_dir),
            'mode': parse_mode.value,
        })
    except (ValueError, RuntimeError, HTTPException):
        input_path.unlink(missing_ok=True)
        raise
    return JSONResponse({'success': True, 'queued': True, 'task': task})


@app.post('/api/fetch')
def fetch(payload: FetchRequest):
    return JSONResponse(run_media_fetch(payload.model_dump()))


@app.post('/api/fetch/batch')
def fetch_batch(payload: BatchFetchRequest):
    items = [
        {
            'link': link.strip(),
            'outputPath': payload.outputPath,
            'outputType': payload.outputType,
            'videoQuality': payload.videoQuality,
            'bilibiliCookie': payload.bilibiliCookie,
            'bilibiliCookieFile': payload.bilibiliCookieFile,
            'saveAssets': payload.saveAssets,
            'subtitleStrategy': payload.subtitleStrategy,
        }
        for link in payload.links
        if link.strip()
    ]
    if not items:
        return JSONResponse({'success': False, 'error': '请至少输入一个有效链接', 'tasks': []}, status_code=400)
    tasks = media_queue.submit(items)
    return JSONResponse({'success': True, 'tasks': tasks})
