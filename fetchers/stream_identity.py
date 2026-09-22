"""Stable-enough media selection identity without persisting signed query strings."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

from fetchers.models import MediaStream


def stream_id(stream: MediaStream) -> str:
    parsed = urlsplit(str(stream.url))
    identity = [parsed.hostname, parsed.path, stream.container, stream.codec,
                stream.width, stream.height, stream.bitrate, stream.quality_label]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]
    return f'sid:{digest}'
