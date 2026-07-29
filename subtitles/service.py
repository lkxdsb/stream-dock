from __future__ import annotations

import re
import math
from pathlib import Path
from uuid import uuid4

from .models import SubtitleCue, SubtitleDocument

SUPPORTED_FORMATS = {'srt', 'vtt', 'txt'}
MAX_CUES = 5000
MAX_CUE_TEXT_LENGTH = 4000
MAX_TIMELINE_SECONDS = 7 * 24 * 60 * 60
MAX_DOCUMENT_TEXT_LENGTH = 5 * 1024 * 1024
TIMING_RE = re.compile(
    r'(?P<start>(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3})\s*-->\s*'
    r'(?P<end>(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3})(?:\s+.*)?$'
)


def normalize_format(filename: str, requested: str | None = None) -> str:
    value = str(requested or Path(filename).suffix.lstrip('.')).lower().strip()
    if value not in SUPPORTED_FORMATS:
        raise ValueError('仅支持 SRT、VTT 和 TXT 字幕')
    return value


def _parse_timestamp(value: str) -> float:
    parts = value.replace(',', '.').split(':')
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError('字幕时间格式不正确')
    hour_value = int(hours)
    minute_value = int(minutes)
    second_value = float(seconds)
    if minute_value >= 60 or second_value >= 60:
        raise ValueError('字幕时间中的分和秒必须小于 60')
    result = hour_value * 3600 + minute_value * 60 + second_value
    if not math.isfinite(result) or result < 0 or result > MAX_TIMELINE_SECONDS:
        raise ValueError('字幕时间必须位于 0～7 天范围内')
    return round(result, 3)


def _cue(start: float, end: float, text: str) -> SubtitleCue:
    clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text).replace('\r\n', '\n').replace('\r', '\n').strip()
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end > MAX_TIMELINE_SECONDS:
        raise ValueError('字幕时间必须位于 0～7 天范围内')
    if not clean or end <= start:
        raise ValueError('字幕片段必须包含文本，且结束时间应晚于开始时间')
    if len(clean) > MAX_CUE_TEXT_LENGTH:
        raise ValueError('单条字幕文本过长')
    return SubtitleCue(id=uuid4().hex[:12], start=round(start, 3), end=round(end, 3), text=clean)


def _parse_timed(text: str, *, vtt: bool) -> list[SubtitleCue]:
    normalized = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff')
    blocks = re.split(r'\n\s*\n', normalized)
    cues: list[SubtitleCue] = []
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if vtt and (lines[0].startswith('WEBVTT') or lines[0].startswith(('NOTE', 'STYLE', 'REGION'))):
            continue
        timing_index = next((index for index, line in enumerate(lines) if '-->' in line), -1)
        if timing_index < 0:
            continue
        match = TIMING_RE.match(lines[timing_index].strip())
        if not match:
            continue
        body = '\n'.join(lines[timing_index + 1:]).strip()
        if body:
            cues.append(_cue(_parse_timestamp(match.group('start')), _parse_timestamp(match.group('end')), body))
            if len(cues) > MAX_CUES:
                raise ValueError(f'字幕片段不能超过 {MAX_CUES} 条')
    return cues


def parse_subtitles(text: str, *, filename: str = 'subtitle.srt', format: str | None = None) -> SubtitleDocument:
    if len(text.encode('utf-8')) > MAX_DOCUMENT_TEXT_LENGTH:
        raise ValueError('字幕文本不能超过 5MB')
    source_format = normalize_format(filename, format)
    if source_format == 'txt':
        lines = [line.strip() for line in text.replace('\r\n', '\n').split('\n') if line.strip()]
        if len(lines) > MAX_CUES:
            raise ValueError(f'字幕片段不能超过 {MAX_CUES} 条')
        cues = [_cue(index * 3.0, index * 3.0 + 2.8, line) for index, line in enumerate(lines)]
    else:
        cues = _parse_timed(text, vtt=source_format == 'vtt')
    if not cues:
        raise ValueError('没有识别到有效字幕片段')
    if len(cues) > MAX_CUES:
        raise ValueError(f'字幕片段不能超过 {MAX_CUES} 条')
    return SubtitleDocument(filename=Path(filename).name, format=source_format, cues=cues)


def validate_cues(rows: list[dict[str, object]]) -> list[SubtitleCue]:
    if not rows or len(rows) > MAX_CUES:
        raise ValueError(f'字幕片段数量应为 1～{MAX_CUES} 条')
    total_text_length = sum(len(str(row.get('text') or '').encode('utf-8')) for row in rows)
    if total_text_length > MAX_DOCUMENT_TEXT_LENGTH:
        raise ValueError('字幕文本不能超过 5MB')
    cues = [_cue(float(row.get('start', 0)), float(row.get('end', 0)), str(row.get('text') or '')) for row in rows]
    return sorted(cues, key=lambda cue: (cue.start, cue.end))


def _format_time(seconds: float, separator: str) -> str:
    millis_total = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(millis_total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}'


def export_subtitles(rows: list[dict[str, object]], format: str) -> str:
    target = normalize_format(f'subtitle.{format}', format)
    cues = validate_cues(rows)
    if target == 'txt':
        return '\n'.join(cue.text.replace('\n', ' ') for cue in cues) + '\n'
    separator = ',' if target == 'srt' else '.'
    blocks = []
    for index, cue in enumerate(cues, 1):
        timing = f'{_format_time(cue.start, separator)} --> {_format_time(cue.end, separator)}'
        blocks.append(f'{index}\n{timing}\n{cue.text}' if target == 'srt' else f'{timing}\n{cue.text}')
    prefix = 'WEBVTT\n\n' if target == 'vtt' else ''
    return prefix + '\n\n'.join(blocks) + '\n'
