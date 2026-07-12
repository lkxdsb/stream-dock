from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests
from typing import Callable

HLS_DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv('STREAMDOCK_HLS_DOWNLOAD_TIMEOUT_SECONDS', str(20 * 60)))
DownloadProgress = Callable[[float | None], None]


def is_hls_url(url: str) -> bool:
    lowered = urlparse(url).path.lower()
    return lowered.endswith(".m3u8")


def download_hls_media(
    url: str,
    destination: Path,
    *,
    user_agent: str,
    referer: str,
    progress_callback: DownloadProgress | None = None,
) -> Path:
    if progress_callback:
        progress_callback(None)
    headers = f"User-Agent: {user_agent}\r\nReferer: {referer}\r\n"
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-headers",
                headers,
                "-i",
                url,
                "-c",
                "copy",
                str(destination),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=HLS_DOWNLOAD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'HLS 下载超时，已停止任务（{HLS_DOWNLOAD_TIMEOUT_SECONDS} 秒）') from exc
    if progress_callback:
        progress_callback(100)
    return destination


def download_media(
    url: str,
    destination: Path,
    *,
    user_agent: str,
    referer: str = "https://www.douyin.com/",
    progress_callback: DownloadProgress | None = None,
) -> Path:
    headers = {
        "User-Agent": user_agent,
        "Referer": referer,
    }
    if is_hls_url(url):
        return download_hls_media(
            url,
            destination,
            user_agent=user_agent,
            referer=referer,
            progress_callback=progress_callback,
        )
    response = requests.get(url, headers=headers, timeout=60, stream=True)
    try:
        response.raise_for_status()
        total = int(response.headers.get('content-length') or 0)
        written = 0
        last_reported = -1
        with destination.open('wb') as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                output.write(chunk)
                written += len(chunk)
                if progress_callback and total > 0:
                    percent = min(100, int(written * 100 / total))
                    if percent >= last_reported + 5 or percent == 100:
                        progress_callback(percent)
                        last_reported = percent
        if progress_callback and total <= 0:
            progress_callback(100)
    finally:
        response.close()
    return destination
