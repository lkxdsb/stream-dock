from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MediaStream:
    url: str
    stream_type: str
    container: str | None = None
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    bitrate: int | None = None
    filesize: int | None = None
    quality_label: str | None = None


@dataclass(frozen=True)
class MediaFetchResult:
    platform: str
    content_type: str
    title: str
    source_url: str
    final_url: str
    cover_url: str | None
    author: str | None
    video_streams: list[MediaStream] = field(default_factory=list)
    audio_streams: list[MediaStream] = field(default_factory=list)
    preferred_video: MediaStream | None = None
    preferred_audio: MediaStream | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportRequest:
    output_path: str
    output_type: str


@dataclass(frozen=True)
class ResolvedMediaSelection:
    video_stream: MediaStream | None
    audio_stream: MediaStream | None
    title: str
    output_type: str
