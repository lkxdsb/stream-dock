from __future__ import annotations

import re
from pathlib import Path

_TIME = re.compile(r'(\d\d):(\d\d):(\d\d),(\d\d\d)')
_LRC_LINE = re.compile(r'\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)')


def srt_to_vtt(text: str) -> str:
    text = _TIME.sub(lambda m: f'{m.group(1)}:{m.group(2)}:{m.group(3)}.{m.group(4)}', text)
    return 'WEBVTT\n\n' + text.strip() + '\n'


def vtt_to_srt(text: str) -> str:
    text = text.replace('WEBVTT', '').strip()
    return re.sub(r'(\d\d:\d\d:\d\d)\.(\d\d\d)', r'\1,\2', text) + '\n'


def ass_to_srt(text: str) -> str:
    lines = []
    index = 1
    for line in text.splitlines():
        if not line.startswith('Dialogue:'):
            continue
        parts = line.split(',', 9)
        if len(parts) < 10:
            continue
        start = parts[1].strip()
        end = parts[2].strip()
        body = re.sub(r'\{[^}]*\}', '', parts[9]).replace('\\N', '\n')
        lines.append(f'{index}\n{_ass_time(start)} --> {_ass_time(end)}\n{body}\n')
        index += 1
    return '\n'.join(lines)


def _ass_time(value: str) -> str:
    h, m, rest = value.split(':')
    s, cs = rest.split('.')
    return f'{int(h):02d}:{int(m):02d}:{int(s):02d},{int(cs) * 10:03d}'


def txt_to_srt(text: str) -> str:
    chunks = [line.strip() for line in text.splitlines() if line.strip()]
    out = []
    for index, line in enumerate(chunks, start=1):
        start = index - 1
        end = index
        out.append(f'{index}\n00:00:{start:02d},000 --> 00:00:{end:02d},000\n{line}\n')
    return '\n'.join(out)


def lrc_to_srt(text: str) -> str:
    entries = []
    for line in text.splitlines():
        match = _LRC_LINE.match(line.strip())
        if not match:
            continue
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        fraction = (match.group(3) or '0')[:3].ljust(3, '0')
        millis = (minutes * 60 + seconds) * 1000 + int(fraction)
        body = match.group(4).strip()
        if body:
            entries.append((millis, body))
    out = []
    for index, (start_ms, body) in enumerate(entries, start=1):
        if index < len(entries):
            end_ms = max(entries[index][0], start_ms + 1000)
        else:
            end_ms = start_ms + 3000
        out.append(f'{index}\n{_format_srt_time(start_ms)} --> {_format_srt_time(end_ms)}\n{body}\n')
    return '\n'.join(out)


def _format_srt_time(total_ms: int) -> str:
    hours, rem = divmod(total_ms, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}'


def convert_subtitle(source: str, target: str, input_path: Path, output_path: Path) -> list[str]:
    text = input_path.read_text(encoding='utf-8-sig')
    if source == 'srt' and target == 'vtt':
        result = srt_to_vtt(text)
    elif source == 'vtt' and target == 'srt':
        result = vtt_to_srt(text)
    elif source == 'ass' and target == 'srt':
        result = ass_to_srt(text)
    elif source == 'ass' and target == 'vtt':
        result = srt_to_vtt(ass_to_srt(text))
    elif source == 'txt' and target == 'srt':
        result = txt_to_srt(text)
    elif source == 'lrc' and target == 'srt':
        result = lrc_to_srt(text)
    elif source == 'lrc' and target == 'vtt':
        result = srt_to_vtt(lrc_to_srt(text))
    else:
        raise RuntimeError(f'暂不支持字幕转换 {source} → {target}')
    output_path.write_text(result, encoding='utf-8')
    return [f'字幕已转换为 {target.upper()}']
