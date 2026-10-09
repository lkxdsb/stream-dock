"""Stable-enough media selection identity without persisting signed query strings."""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit

from fetchers.models import MediaStream


def stream_id(stream: MediaStream) -> str:
    parsed = urlsplit(str(stream.url))
    host, path = parsed.hostname, parsed.path
    # Douyin signs both the query and the path prefix and rotates CDN shards.
    # Only canonicalize the observed CDN route; retain the full asset path.
    if host and host.endswith('.douyinvod.com'):
        match = re.fullmatch(r'/[0-9a-fA-F]{32}/[0-9a-fA-F]{8}(/video/tos/.+)', path)
        if match:
            host, path = 'douyinvod.com', match.group(1)
    identity = [host, path, stream.container, stream.codec,
                stream.width, stream.height, stream.bitrate, stream.quality_label]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]
    return f'sid:{digest}'
