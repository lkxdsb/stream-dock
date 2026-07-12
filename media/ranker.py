from __future__ import annotations

from dataclasses import dataclass

from fetchers.models import MediaStream


@dataclass(frozen=True)
class RankedStream:
    stream: MediaStream
    score: float
    reason: str


def _codec_name(stream: MediaStream) -> str:
    return str(stream.codec or '').lower()


def _container_name(stream: MediaStream) -> str:
    return str(stream.container or '').lower()


def score_stream(stream: MediaStream, strategy: str = 'best_quality') -> RankedStream:
    """Score a discovered stream without claiming unavailable quality data."""
    height = stream.height or 0
    width = stream.width or 0
    bitrate = stream.bitrate or 0
    filesize = stream.filesize or 0
    codec = _codec_name(stream)
    container = _container_name(stream)

    if strategy == 'best_compatibility':
        score = 0.0
        score += 500 if container in {'mp4', 'm4v'} else 0
        score += 450 if any(name in codec for name in ('h264', 'avc')) else 0
        score += min(height, 2160) / 10
        score += min(bitrate, 20_000_000) / 1_000_000
        return RankedStream(stream, score, '优先 MP4、H.264 与常见播放器兼容性')

    if strategy == 'smallest_size':
        known_size_penalty = filesize / (1024 * 1024) if filesize else 10_000
        score = -known_size_penalty + min(height, 720) / 100
        return RankedStream(stream, score, '优先已知体积更小的可用视频流')

    score = height * 10 + width / 100 + bitrate / 100_000
    if any(name in codec for name in ('av1', 'av01')):
        score += 8
    elif any(name in codec for name in ('hevc', 'h265', 'hev1', 'hvc1')):
        score += 5
    return RankedStream(stream, score, '优先实际分辨率、码率与高效编码')


def rank_streams(streams: list[MediaStream], strategy: str = 'best_quality') -> list[RankedStream]:
    if strategy not in {'best_quality', 'best_compatibility', 'smallest_size'}:
        raise ValueError(f'Unsupported media ranking strategy: {strategy}')
    return sorted((score_stream(item, strategy) for item in streams), key=lambda item: item.score, reverse=True)


def recommendations(streams: list[MediaStream]) -> dict[str, RankedStream | None]:
    return {
        strategy: (ranked[0] if ranked else None)
        for strategy in ('best_quality', 'best_compatibility', 'smallest_size')
        for ranked in [rank_streams(streams, strategy)]
    }

