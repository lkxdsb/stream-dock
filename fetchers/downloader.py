from __future__ import annotations

from pathlib import Path

import requests


def download_media(
    url: str,
    destination: Path,
    *,
    user_agent: str,
    referer: str = "https://www.douyin.com/",
) -> Path:
    headers = {
        "User-Agent": user_agent,
        "Referer": referer,
    }
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination
