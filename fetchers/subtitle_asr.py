from __future__ import annotations

import importlib.util
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from runtime_checks import augmented_path, resolve_tool_path
from fetchers.subtitle_ocr import OcrSubtitleCue, cues_to_srt
from subtitles.chinese import normalize_chinese_asr

ASR_MODEL = os.getenv('STREAMDOCK_SUBTITLE_ASR_MODEL', 'small')
ASR_LANGUAGE = os.getenv('STREAMDOCK_SUBTITLE_ASR_LANG', 'zh')
ASR_TIMEOUT_SECONDS = int(os.getenv('STREAMDOCK_SUBTITLE_ASR_TIMEOUT_SECONDS', '900'))
ASR_MIN_CUES = int(os.getenv('STREAMDOCK_SUBTITLE_ASR_MIN_CUES', '1'))


class SubtitleQualityError(ValueError):
    """Recognized text is damaged; never publish it as a usable subtitle."""


def validate_asr_cues(cues: list[OcrSubtitleCue]) -> None:
    for index, cue in enumerate(cues, start=1):
        if not (math.isfinite(cue.start) and math.isfinite(cue.end)
                and 0 <= cue.start < cue.end):
            raise SubtitleQualityError(f'字幕片段 {index} 的时间轴无效')
        if '\ufffd' in cue.text or any(ord(c) < 32 and c not in '\n\r\t' for c in cue.text):
            raise SubtitleQualityError(f'字幕片段 {index} 含有损坏字符，请更换识别模型或使用画面字幕识别')
        if index > 1 and cue.start < cues[index - 2].end:
            raise SubtitleQualityError(f'字幕片段 {index} 时间轴重叠，请重新识别或编辑时间轴')


def normalize_asr_boundaries(cues: list[OcrSubtitleCue]) -> list[OcrSubtitleCue]:
    result = list(cues)
    for index in range(1, len(result)):
        previous, current = result[index - 1], result[index]
        if 0 < previous.end - current.start <= .25 and current.start > previous.start:
            result[index - 1] = replace(previous, end=current.start)
    return result


@dataclass(frozen=True)
class AsrEngineStatus:
    available: bool
    engine: str | None = None
    detail: str | None = None


def asr_engine_status() -> AsrEngineStatus:
    """Return the best local speech-to-subtitle engine currently available."""
    if importlib.util.find_spec('faster_whisper') is not None:
        return AsrEngineStatus(True, 'faster-whisper', 'faster-whisper Python 包可用')
    if importlib.util.find_spec('whisper') is not None:
        return AsrEngineStatus(True, 'openai-whisper', 'whisper Python 包可用')
    whisper_bin = shutil.which('whisper', path=augmented_path())
    if whisper_bin:
        return AsrEngineStatus(True, 'whisper-cli', whisper_bin)
    return AsrEngineStatus(False, None, '未安装 faster-whisper/openai-whisper/whisper CLI')


def asr_available() -> bool:
    return asr_engine_status().available and bool(shutil.which('ffmpeg', path=augmented_path()))


def _extract_audio(video_path: Path, audio_path: Path) -> None:
    ffmpeg = resolve_tool_path('ffmpeg')
    completed = subprocess.run(
        [
            ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-i', str(video_path),
            '-vn', '-ac', '1', '-ar', '16000', '-f', 'wav', str(audio_path),
        ],
        text=True,
        capture_output=True,
        timeout=180,
        env={**os.environ, 'PATH': augmented_path()},
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or '语音字幕音频提取失败')


def _segments_to_cues(segments: Iterable[Any]) -> list[OcrSubtitleCue]:
    cues: list[OcrSubtitleCue] = []
    for item in segments:
        if isinstance(item, dict):
            start = float(item.get('start') or 0)
            end = float(item.get('end') or 0)
            text = str(item.get('text') or '').strip()
        else:
            start = float(getattr(item, 'start', 0) or 0)
            end = float(getattr(item, 'end', 0) or 0)
            text = str(getattr(item, 'text', '') or '').strip()
        if text and end > start:
            cues.append(OcrSubtitleCue(start=start, end=end, text=text))
    return cues


def _transcribe_with_faster_whisper(audio_path: Path, *, model_name: str, language: str | None) -> list[OcrSubtitleCue]:
    from faster_whisper import WhisperModel  # type: ignore

    model = WhisperModel(model_name, device=os.getenv('STREAMDOCK_SUBTITLE_ASR_DEVICE', 'cpu'), compute_type=os.getenv('STREAMDOCK_SUBTITLE_ASR_COMPUTE_TYPE', 'int8'))
    segments, _info = model.transcribe(str(audio_path), language=language or None, vad_filter=True, beam_size=5)
    return [replace(cue, text=normalize_chinese_asr(cue.text, getattr(_info, 'language', language)))
            for cue in _segments_to_cues(segments)]


def _transcribe_with_openai_whisper(audio_path: Path, *, model_name: str, language: str | None) -> list[OcrSubtitleCue]:
    import whisper  # type: ignore

    model = whisper.load_model(model_name)
    result = model.transcribe(str(audio_path), language=language or None, verbose=False)
    return [replace(cue, text=normalize_chinese_asr(cue.text, result.get('language') or language))
            for cue in _segments_to_cues(result.get('segments') or [])]


def _transcribe_with_whisper_cli(audio_path: Path, output_dir: Path, *, model_name: str, language: str | None) -> list[OcrSubtitleCue]:
    whisper_bin = shutil.which('whisper', path=augmented_path())
    if not whisper_bin:
        return []
    command = [
        whisper_bin, str(audio_path), '--model', model_name, '--output_format', 'srt', '--output_dir', str(output_dir), '--fp16', 'False'
    ]
    if language:
        # OpenAI whisper CLI accepts language names/codes; zh works in recent versions.
        command.extend(['--language', language])
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=ASR_TIMEOUT_SECONDS,
        env={**os.environ, 'PATH': augmented_path()},
    )
    if completed.returncode != 0:
        return []
    srt_path = next(output_dir.glob('*.srt'), None)
    if not srt_path or not srt_path.exists():
        return []
    return _parse_srt_cues(srt_path.read_text(encoding='utf-8', errors='strict'))


def _parse_srt_time(value: str) -> float:
    hours, minutes, rest = value.strip().split(':')
    seconds, millis = rest.split(',')
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def _parse_srt_cues(text: str) -> list[OcrSubtitleCue]:
    cues: list[OcrSubtitleCue] = []
    for block in text.replace('\r\n', '\n').split('\n\n'):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or '-->' not in lines[1]:
            continue
        left, right = [part.strip() for part in lines[1].split('-->', 1)]
        body = '\n'.join(lines[2:]).strip()
        try:
            start = _parse_srt_time(left)
            end = _parse_srt_time(right)
        except Exception:
            continue
        if body and end > start:
            cues.append(OcrSubtitleCue(start, end, body))
    return cues


def generate_asr_subtitle_file(
    video_path: Path,
    output_path: Path,
    *,
    model_name: str = ASR_MODEL,
    language: str | None = ASR_LANGUAGE,
) -> Path | None:
    """Generate a complete speech transcript subtitle from the media audio.

    This is intentionally optional: it uses the best locally installed Whisper engine and
    returns None when no engine is available, so platform-native subtitle downloads remain
    the first-choice path.
    """
    status = asr_engine_status()
    if not status.available:
        return None
    if not shutil.which('ffmpeg', path=augmented_path()):
        return None
    if not video_path.exists() or not video_path.is_file():
        return None

    with tempfile.TemporaryDirectory(prefix='streamdock_subtitle_asr_') as tmp:
        tmp_path = Path(tmp)
        audio_path = tmp_path / 'audio.wav'
        _extract_audio(video_path, audio_path)
        cues: list[OcrSubtitleCue] = []
        if status.engine == 'faster-whisper':
            cues = _transcribe_with_faster_whisper(audio_path, model_name=model_name, language=language)
        elif status.engine == 'openai-whisper':
            cues = _transcribe_with_openai_whisper(audio_path, model_name=model_name, language=language)
        elif status.engine == 'whisper-cli':
            cues = _transcribe_with_whisper_cli(audio_path, tmp_path, model_name=model_name, language=language)
    if len(cues) < ASR_MIN_CUES:
        return None
    cues = normalize_asr_boundaries([replace(cue, text=normalize_chinese_asr(cue.text, language)) for cue in cues])
    validate_asr_cues(cues)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(cues_to_srt(cues), encoding='utf-8')
    return output_path if output_path.exists() and output_path.stat().st_size > 0 else None
