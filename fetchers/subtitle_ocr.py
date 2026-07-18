from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from runtime_checks import augmented_path, resolve_tool_path

OCR_INTERVAL_SECONDS = float(os.getenv('STREAMDOCK_SUBTITLE_OCR_INTERVAL_SECONDS', '1.0'))
OCR_MAX_FRAMES = int(os.getenv('STREAMDOCK_SUBTITLE_OCR_MAX_FRAMES', '80'))
OCR_TIMEOUT_SECONDS = int(os.getenv('STREAMDOCK_SUBTITLE_OCR_TIMEOUT_SECONDS', '240'))
OCR_LANGUAGE = os.getenv('STREAMDOCK_SUBTITLE_OCR_LANG', 'chi_sim+eng')


@dataclass(frozen=True)
class OcrSubtitleCue:
    start: float
    end: float
    text: str


def ocr_available() -> bool:
    return bool(shutil.which('tesseract', path=augmented_path()) and shutil.which('ffmpeg', path=augmented_path()))


def _normalize_ocr_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        line = re.sub(r'^[\W_]+|[\W_]+$', '', line)
        if not line or len(line) <= 1:
            continue
        if re.fullmatch(r'[\d\W_]+', line):
            continue

        cjk_count = len(re.findall(r'[\u4e00-\u9fff]', line))
        latin_count = len(re.findall(r'[A-Za-z]', line))
        digit_count = len(re.findall(r'\d', line))

        if cjk_count > 0:
            # 中文平台的 OCR 容易把水印、UI 和花字识别成大段拉丁乱码。
            # 对含中文的行优先保留中文、数字和中文常用标点，去掉明显拉丁噪声。
            cleaned = re.sub(r'https?://\S+|www\.\S+', '', line, flags=re.I)
            cleaned = re.sub(r'[A-Za-z]{2,}', ' ', cleaned)
            cleaned = re.sub(r'[^\u4e00-\u9fff0-9０-９，。！？、：；“”‘’（）《》【】\[\]()./%\-+\s]', ' ', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -_/|·.。')
            cleaned_cjk = len(re.findall(r'[\u4e00-\u9fff]', cleaned))
            cleaned_digit = len(re.findall(r'\d', cleaned))
            if cleaned_cjk >= 2 or (cleaned_cjk >= 1 and cleaned_digit >= 1):
                lines.append(cleaned)
            continue

        # 没有中文时只保留看起来像自然英文字幕的行；短碎片和随机 OCR 串丢弃。
        words = re.findall(r'[A-Za-z]{2,}', line)
        if len(words) < 2:
            continue
        weird_chars = len(re.findall(r'[^A-Za-z0-9\s,.!?\'"-]', line))
        if weird_chars > 0:
            continue
        upper_count = len(re.findall(r'[A-Z]', line))
        avg_word_len = sum(len(word) for word in words) / max(1, len(words))
        uppercase_ratio = upper_count / max(1, latin_count)
        if uppercase_ratio > 0.75 and avg_word_len <= 4:
            continue
        if uppercase_ratio > 0.45 and len(words) < 5:
            continue
        if latin_count < 8 or digit_count > latin_count:
            continue
        lines.append(line)

    compact = '\n'.join(dict.fromkeys(lines))
    total_cjk = len(re.findall(r'[\u4e00-\u9fff]', compact))
    total_latin = len(re.findall(r'[A-Za-z]', compact))
    if total_cjk == 0 and total_latin < 8:
        return ''
    return compact[:240]


def _format_srt_time(seconds: float) -> str:
    millis_total = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(millis_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}'


def cues_to_srt(cues: list[OcrSubtitleCue]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        text = cue.text.strip()
        if not text:
            continue
        blocks.append(f'{index}\n{_format_srt_time(cue.start)} --> {_format_srt_time(max(cue.end, cue.start + 0.5))}\n{text}\n')
    return '\n'.join(blocks).strip() + ('\n' if blocks else '')


def merge_ocr_samples(samples: list[tuple[float, str]], *, interval_seconds: float = OCR_INTERVAL_SECONDS) -> list[OcrSubtitleCue]:
    cues: list[OcrSubtitleCue] = []
    active_text = ''
    active_start = 0.0
    active_end = 0.0
    for timestamp, raw_text in samples:
        text = _normalize_ocr_text(raw_text)
        if not text:
            if active_text:
                cues.append(OcrSubtitleCue(active_start, active_end, active_text))
                active_text = ''
            continue
        if text == active_text:
            active_end = timestamp + interval_seconds
            continue
        if active_text:
            cues.append(OcrSubtitleCue(active_start, active_end, active_text))
        active_text = text
        active_start = timestamp
        active_end = timestamp + interval_seconds
    if active_text:
        cues.append(OcrSubtitleCue(active_start, active_end, active_text))
    return cues


def _extract_subtitle_frames(video_path: Path, frames_dir: Path, *, interval_seconds: float, max_frames: int) -> list[Path]:
    ffmpeg = resolve_tool_path('ffmpeg')
    fps = 1 / max(0.2, interval_seconds)
    # Crop the lower part of the frame where burned-in subtitles usually appear.
    # The crop keeps enough UI context for vertical short videos but avoids most top noise.
    vf = f'fps={fps},scale=960:-1,crop=iw:ih*0.45:0:ih*0.55'
    pattern = frames_dir / 'frame_%04d.png'
    completed = subprocess.run(
        [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-i', str(video_path), '-frames:v', str(max_frames), '-vf', vf, str(pattern)],
        text=True,
        capture_output=True,
        timeout=OCR_TIMEOUT_SECONDS,
        env={**os.environ, 'PATH': augmented_path()},
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or '字幕 OCR 抽帧失败')
    return sorted(frames_dir.glob('frame_*.png'))


def _ocr_frame(image_path: Path) -> str:
    tesseract = shutil.which('tesseract', path=augmented_path()) or 'tesseract'
    completed = subprocess.run(
        [tesseract, str(image_path), 'stdout', '-l', OCR_LANGUAGE, '--psm', '6'],
        text=True,
        capture_output=True,
        timeout=45,
        env={**os.environ, 'PATH': augmented_path()},
    )
    if completed.returncode != 0:
        return ''
    return completed.stdout or ''


def generate_ocr_subtitle_file(
    video_path: Path,
    output_path: Path,
    *,
    interval_seconds: float = OCR_INTERVAL_SECONDS,
    max_frames: int = OCR_MAX_FRAMES,
) -> Path | None:
    if not ocr_available():
        return None
    if not video_path.exists() or not video_path.is_file():
        return None
    with tempfile.TemporaryDirectory(prefix='streamdock_subtitle_ocr_') as tmp:
        frames_dir = Path(tmp)
        frames = _extract_subtitle_frames(video_path, frames_dir, interval_seconds=interval_seconds, max_frames=max_frames)
        samples: list[tuple[float, str]] = []
        for index, frame in enumerate(frames):
            timestamp = index * interval_seconds
            samples.append((timestamp, _ocr_frame(frame)))
        cues = merge_ocr_samples(samples, interval_seconds=interval_seconds)
    if not cues:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(cues_to_srt(cues), encoding='utf-8')
    return output_path if output_path.exists() and output_path.stat().st_size > 0 else None
