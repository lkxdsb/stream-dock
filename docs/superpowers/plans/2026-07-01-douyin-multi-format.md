# Douyin Multi-Format Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the local Douyin tool from `m4a/mp3/mp4` export to `wav/flac/aac/ogg/opus/mkv/mov/webm` while keeping the current CLI and local web usage unchanged.

**Architecture:** Refactor `douyin_fetch.py` from hard-coded output branches into a format-registry-driven export pipeline. Keep capture/download logic intact, normalize downloaded assets into `source_video` / `source_audio`, then route export by format strategy: audio extract/transcode, stream mux, or WebM transcode. Update FastAPI validation and the HTML select list only after the backend registry is stable.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, Playwright, requests, ffmpeg/ffprobe, unittest, browser-cookie3.

---

## File Structure

- Modify: `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py`
  - Add output format registry and export helpers.
  - Keep capture logic stable; refactor only the output layer.
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/app.py`
  - Expand `FetchRequest.outputType` validation.
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/templates/index.html`
  - Add the new output format `<option>` entries.
- Create: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py`
  - Focused backend format registry + ffmpeg export regression tests.
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py`
  - Keep UI smoke tests and add assertions for the new format options.

## Task 1: Introduce the output format registry

**Files:**
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py`

- [ ] **Step 1: Write the failing registry tests**

```python
# /Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py
import unittest

from douyin_fetch import (
    OUTPUT_FORMATS,
    get_output_format_spec,
    is_audio_output,
    is_video_output,
)


class OutputFormatRegistryTests(unittest.TestCase):
    def test_registry_contains_all_expected_formats(self):
        self.assertEqual(
            set(OUTPUT_FORMATS),
            {'m4a', 'mp3', 'mp4', 'wav', 'flac', 'aac', 'ogg', 'opus', 'mkv', 'mov', 'webm'},
        )

    def test_audio_and_video_helpers_classify_formats(self):
        self.assertTrue(is_audio_output('wav'))
        self.assertTrue(is_audio_output('opus'))
        self.assertTrue(is_video_output('mkv'))
        self.assertTrue(is_video_output('webm'))
        self.assertFalse(is_video_output('flac'))

    def test_webm_spec_requires_transcode(self):
        spec = get_output_format_spec('webm')
        self.assertEqual(spec.kind, 'video')
        self.assertEqual(spec.mode, 'transcode')
        self.assertTrue(spec.needs_video_stream)
        self.assertTrue(spec.needs_audio_stream)
```

- [ ] **Step 2: Run the registry tests to verify they fail**

Run:
```bash
cd /Users/hjjtongxue/Documents/视频解析工具
source $(conda info --base)/etc/profile.d/conda.sh
conda activate jj
python -m unittest tests.test_douyin_formats -v
```

Expected: FAIL with `ImportError` or `AttributeError` because `OUTPUT_FORMATS`, `get_output_format_spec`, `is_audio_output`, and `is_video_output` do not exist yet.

- [ ] **Step 3: Implement the registry in `douyin_fetch.py`**

```python
# add near the top of /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class OutputFormatSpec:
    extension: str
    kind: str  # 'audio' | 'video'
    mode: str  # 'extract' | 'mux' | 'transcode'
    needs_video_stream: bool
    needs_audio_stream: bool


OUTPUT_FORMATS: dict[str, OutputFormatSpec] = {
    'm4a': OutputFormatSpec('m4a', 'audio', 'extract', False, True),
    'mp3': OutputFormatSpec('mp3', 'audio', 'transcode', False, True),
    'wav': OutputFormatSpec('wav', 'audio', 'transcode', False, True),
    'flac': OutputFormatSpec('flac', 'audio', 'transcode', False, True),
    'aac': OutputFormatSpec('aac', 'audio', 'transcode', False, True),
    'ogg': OutputFormatSpec('ogg', 'audio', 'transcode', False, True),
    'opus': OutputFormatSpec('opus', 'audio', 'transcode', False, True),
    'mp4': OutputFormatSpec('mp4', 'video', 'mux', True, False),
    'mkv': OutputFormatSpec('mkv', 'video', 'mux', True, False),
    'mov': OutputFormatSpec('mov', 'video', 'mux', True, False),
    'webm': OutputFormatSpec('webm', 'video', 'transcode', True, True),
}

SUPPORTED_OUTPUT_TYPES = set(OUTPUT_FORMATS)


def get_output_format_spec(output_type: str) -> OutputFormatSpec:
    try:
        return OUTPUT_FORMATS[output_type]
    except KeyError as exc:
        raise ValueError(f'Unsupported output type: {output_type}') from exc


def is_audio_output(output_type: str) -> bool:
    return get_output_format_spec(output_type).kind == 'audio'


def is_video_output(output_type: str) -> bool:
    return get_output_format_spec(output_type).kind == 'video'
```

- [ ] **Step 4: Run the registry tests to verify they pass**

Run:
```bash
python -m unittest tests.test_douyin_formats.OutputFormatRegistryTests -v
```

Expected: PASS with 3 tests.

- [ ] **Step 5: Commit**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py
git commit -m "feat: add output format registry"
```

## Task 2: Refactor audio export around normalized local sources

**Files:**
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py`

- [ ] **Step 1: Write failing audio export tests**

```python
# append to /Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py
import subprocess
import tempfile
from pathlib import Path

from douyin_fetch import export_media


class AudioExportTests(unittest.TestCase):
    def _make_audio_fixture(self, temp_path: Path) -> Path:
        audio_file = temp_path / 'audio.m4a'
        subprocess.run(
            [
                'ffmpeg', '-y',
                '-f', 'lavfi',
                '-i', 'sine=frequency=1000:duration=1',
                '-c:a', 'aac',
                str(audio_file),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return audio_file

    def test_wav_export_creates_audio_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_file = self._make_audio_fixture(temp_path)
            output_dir = temp_path / 'out'
            output_dir.mkdir()
            final_path = export_media(
                source_video=None,
                source_audio=audio_file,
                output_dir=output_dir,
                base_name='demo',
                output_type='wav',
            )
            self.assertEqual(final_path.suffix, '.wav')
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(final_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(probe.stdout.strip(), 'audio')

    def test_opus_export_creates_audio_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_file = self._make_audio_fixture(temp_path)
            output_dir = temp_path / 'out'
            output_dir.mkdir()
            final_path = export_media(
                source_video=None,
                source_audio=audio_file,
                output_dir=output_dir,
                base_name='demo',
                output_type='opus',
            )
            self.assertEqual(final_path.suffix, '.opus')
```

- [ ] **Step 2: Run the audio export tests to verify they fail**

Run:
```bash
python -m unittest tests.test_douyin_formats.AudioExportTests -v
```

Expected: FAIL because `export_media()` does not exist yet.

- [ ] **Step 3: Implement normalized audio export helpers**

```python
# in /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py

def resolve_audio_source(source_video: Path | None, source_audio: Path | None) -> Path:
    if source_audio is not None:
        return source_audio
    if source_video is not None:
        return source_video
    raise ValueError('No source available for audio export')


def transcode_audio(source_path: Path, final_path: Path, output_type: str) -> Path:
    command_map = {
        'mp3': ['ffmpeg', '-y', '-i', str(source_path), '-vn', '-acodec', 'libmp3lame', '-q:a', '2', str(final_path)],
        'wav': ['ffmpeg', '-y', '-i', str(source_path), '-vn', '-acodec', 'pcm_s16le', str(final_path)],
        'flac': ['ffmpeg', '-y', '-i', str(source_path), '-vn', '-acodec', 'flac', str(final_path)],
        'aac': ['ffmpeg', '-y', '-i', str(source_path), '-vn', '-c:a', 'aac', '-b:a', '192k', str(final_path)],
        'ogg': ['ffmpeg', '-y', '-i', str(source_path), '-vn', '-c:a', 'libvorbis', '-q:a', '5', str(final_path)],
        'opus': ['ffmpeg', '-y', '-i', str(source_path), '-vn', '-c:a', 'libopus', '-b:a', '160k', str(final_path)],
    }
    run_ffmpeg(command_map[output_type])
    return final_path


def export_audio(source_video: Path | None, source_audio: Path | None, final_path: Path, output_type: str) -> Path:
    audio_source = resolve_audio_source(source_video, source_audio)
    if output_type == 'm4a':
        run_ffmpeg(['ffmpeg', '-y', '-i', str(audio_source), '-vn', '-c:a', 'copy', str(final_path)])
        return final_path
    return transcode_audio(audio_source, final_path, output_type)
```

- [ ] **Step 4: Introduce the `export_media()` dispatcher and rerun tests**

```python
# in /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py

def export_media(
    *,
    source_video: Path | None,
    source_audio: Path | None,
    output_dir: Path,
    base_name: str,
    output_type: str,
) -> Path:
    spec = get_output_format_spec(output_type)
    final_path = output_dir / f'{base_name}.{spec.extension}'
    if spec.kind == 'audio':
        return export_audio(source_video, source_audio, final_path, output_type)
    raise ValueError(f'Video export not implemented yet for: {output_type}')
```

Run:
```bash
python -m unittest tests.test_douyin_formats.AudioExportTests -v
```

Expected: PASS with 2 tests.

- [ ] **Step 5: Commit**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py
git commit -m "feat: add multi-format audio export"
```

## Task 3: Add video container export for mp4/mkv/mov/webm

**Files:**
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py`

- [ ] **Step 1: Write failing video export tests**

```python
# append to /Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py
class VideoExportTests(unittest.TestCase):
    def _make_av_fixture(self, temp_path: Path) -> tuple[Path, Path]:
        video_file = temp_path / 'video.mp4'
        audio_file = temp_path / 'audio.m4a'
        subprocess.run(
            ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=320x240:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video_file)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=1', '-c:a', 'aac', str(audio_file)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return video_file, audio_file

    def test_mkv_export_contains_audio_and_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_file, audio_file = self._make_av_fixture(temp_path)
            output_dir = temp_path / 'out'
            output_dir.mkdir()
            final_path = export_media(
                source_video=video_file,
                source_audio=audio_file,
                output_dir=output_dir,
                base_name='demo',
                output_type='mkv',
            )
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(final_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual({line.strip() for line in probe.stdout.splitlines() if line.strip()}, {'video', 'audio'})

    def test_webm_export_contains_audio_and_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_file, audio_file = self._make_av_fixture(temp_path)
            output_dir = temp_path / 'out'
            output_dir.mkdir()
            final_path = export_media(
                source_video=video_file,
                source_audio=audio_file,
                output_dir=output_dir,
                base_name='demo',
                output_type='webm',
            )
            self.assertEqual(final_path.suffix, '.webm')
```

- [ ] **Step 2: Run the video export tests to verify they fail**

Run:
```bash
python -m unittest tests.test_douyin_formats.VideoExportTests -v
```

Expected: FAIL with `ValueError: Video export not implemented yet`.

- [ ] **Step 3: Implement mux and WebM transcode helpers**

```python
# in /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py

def validate_output_request(*, media_kind: str, output_type: str) -> None:
    spec = get_output_format_spec(output_type)
    if spec.kind == 'video' and media_kind != 'video':
        raise ValueError(f'Only audio stream found; cannot export a real {output_type} video')


def mux_streams(video_file: Path, audio_file: Path | None, final_path: Path) -> Path:
    if audio_file is None:
        shutil.copyfile(video_file, final_path)
        return final_path
    run_ffmpeg([
        'ffmpeg', '-y',
        '-i', str(video_file),
        '-i', str(audio_file),
        '-c:v', 'copy',
        '-c:a', 'copy',
        str(final_path),
    ])
    return final_path


def transcode_to_webm(video_file: Path, audio_file: Path | None, final_path: Path) -> Path:
    command = ['ffmpeg', '-y', '-i', str(video_file)]
    if audio_file is not None:
        command.extend(['-i', str(audio_file)])
    command.extend([
        '-c:v', 'libvpx-vp9',
        '-b:v', '0',
        '-crf', '32',
        '-c:a', 'libopus',
        '-b:a', '160k',
        str(final_path),
    ])
    run_ffmpeg(command)
    return final_path


def export_video(source_video: Path | None, source_audio: Path | None, final_path: Path, output_type: str) -> Path:
    if source_video is None:
        raise ValueError(f'No video stream available for {output_type} export')
    if output_type in {'mp4', 'mkv', 'mov'}:
        return mux_streams(source_video, source_audio, final_path)
    if output_type == 'webm':
        return transcode_to_webm(source_video, source_audio, final_path)
    raise ValueError(f'Unsupported video output type: {output_type}')
```

- [ ] **Step 4: Update `export_media()` and rerun tests**

```python
# replace export_media() in /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py

def export_media(
    *,
    source_video: Path | None,
    source_audio: Path | None,
    output_dir: Path,
    base_name: str,
    output_type: str,
) -> Path:
    spec = get_output_format_spec(output_type)
    final_path = output_dir / f'{base_name}.{spec.extension}'
    if spec.kind == 'audio':
        return export_audio(source_video, source_audio, final_path, output_type)
    return export_video(source_video, source_audio, final_path, output_type)
```

Run:
```bash
python -m unittest tests.test_douyin_formats.VideoExportTests -v
```

Expected: PASS with 2 tests.

- [ ] **Step 5: Commit**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py
git commit -m "feat: add multi-format video export"
```

## Task 4: Wire the new formats into CLI and local web UI

**Files:**
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/app.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/templates/index.html`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py`

- [ ] **Step 1: Write failing UI/API tests for the new options**

```python
# append to /Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py
from app import FetchRequest


class OutputTypeValidationTests(unittest.TestCase):
    def test_fetch_request_accepts_new_formats(self):
        for output_type in ['wav', 'flac', 'aac', 'ogg', 'opus', 'mkv', 'mov', 'webm']:
            payload = FetchRequest(link='https://v.douyin.com/demo/', outputPath='/tmp/demo', outputType=output_type)
            self.assertEqual(payload.outputType, output_type)


class HomePageOptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_page_lists_new_output_options(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/')
        text = response.text
        for marker in ['value="wav"', 'value="flac"', 'value="aac"', 'value="ogg"', 'value="opus"', 'value="mkv"', 'value="mov"', 'value="webm"']:
            self.assertIn(marker, text)
```

- [ ] **Step 2: Run the UI/API tests to verify they fail**

Run:
```bash
python -m unittest tests.test_app.OutputTypeValidationTests tests.test_app.HomePageOptionTests -v
```

Expected: FAIL because `FetchRequest` still only allows `m4a|mp3|mp4`, and the HTML still only shows 3 options.

- [ ] **Step 3: Update CLI choices, FastAPI validation, and HTML options**

```python
# /Users/hjjtongxue/Documents/视频解析工具/app.py
class FetchRequest(BaseModel):
    link: str = Field(min_length=1)
    outputPath: str = Field(min_length=1)
    outputType: str = Field(pattern=r'^(m4a|mp3|mp4|wav|flac|aac|ogg|opus|mkv|mov|webm)$')
```

```html
<!-- replace the select body in /Users/hjjtongxue/Documents/视频解析工具/templates/index.html -->
<select id="outputType" name="outputType">
  <optgroup label="音频">
    <option value="m4a">m4a</option>
    <option value="mp3">mp3</option>
    <option value="wav">wav</option>
    <option value="flac">flac</option>
    <option value="aac">aac</option>
    <option value="ogg">ogg</option>
    <option value="opus">opus</option>
  </optgroup>
  <optgroup label="视频">
    <option value="mp4">mp4</option>
    <option value="mkv">mkv</option>
    <option value="mov">mov</option>
    <option value="webm">webm</option>
  </optgroup>
</select>
```

```python
# /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py
# keep build_parser() using choices=sorted(SUPPORTED_OUTPUT_TYPES)
```

- [ ] **Step 4: Run the UI/API tests to verify they pass**

Run:
```bash
python -m unittest tests.test_app -v
```

Expected: PASS, including the original homepage smoke test plus the new validation/option tests.

- [ ] **Step 5: Commit**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py /Users/hjjtongxue/Documents/视频解析工具/app.py /Users/hjjtongxue/Documents/视频解析工具/templates/index.html /Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py
git commit -m "feat: expose multi-format export in local ui"
```

## Task 5: End-to-end regression verification with real samples

**Files:**
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py` only if verification exposes a real bug.
- Test: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py`
- Test: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py`

- [ ] **Step 1: Run the full automated test suite**

Run:
```bash
cd /Users/hjjtongxue/Documents/视频解析工具
source $(conda info --base)/etc/profile.d/conda.sh
conda activate jj
python -m unittest tests.test_douyin_formats tests.test_app -v
```

Expected: PASS with 0 failures.

- [ ] **Step 2: Verify new audio formats with a real Douyin sample**

Run:
```bash
mkdir -p /Users/hjjtongxue/Documents/视频解析工具/output_multiformat_verify
python douyin_fetch.py \
  --link "https://v.douyin.com/Tw-kxBn3n6w/" \
  --outputPath "/Users/hjjtongxue/Documents/视频解析工具/output_multiformat_verify" \
  --outputType wav
python douyin_fetch.py \
  --link "https://v.douyin.com/Tw-kxBn3n6w/" \
  --outputPath "/Users/hjjtongxue/Documents/视频解析工具/output_multiformat_verify" \
  --outputType flac
python douyin_fetch.py \
  --link "https://v.douyin.com/Tw-kxBn3n6w/" \
  --outputPath "/Users/hjjtongxue/Documents/视频解析工具/output_multiformat_verify" \
  --outputType opus
```

Expected: each command prints `[douyin-fetch] output file:` and writes a file with the matching extension.

- [ ] **Step 3: Verify new video formats with a real Douyin sample**

Run:
```bash
python douyin_fetch.py \
  --link "https://v.douyin.com/Tw-kxBn3n6w/" \
  --outputPath "/Users/hjjtongxue/Documents/视频解析工具/output_multiformat_verify" \
  --outputType mkv
python douyin_fetch.py \
  --link "https://v.douyin.com/Tw-kxBn3n6w/" \
  --outputPath "/Users/hjjtongxue/Documents/视频解析工具/output_multiformat_verify" \
  --outputType mov
python douyin_fetch.py \
  --link "https://v.douyin.com/Tw-kxBn3n6w/" \
  --outputPath "/Users/hjjtongxue/Documents/视频解析工具/output_multiformat_verify" \
  --outputType webm
```

Expected: each command completes with exit code 0.

- [ ] **Step 4: Probe real video outputs to confirm track layout**

Run:
```bash
ffprobe -v error -show_entries stream=codec_type -of csv=p=0 \
  "/Users/hjjtongxue/Documents/视频解析工具/output_multiformat_verify/朝看天色暮看云广场舞背面完整版 @小寒六六教程号 #原创编舞 @舞清秋🍒广场舞 #小寒六六编舞 #小寒六六 #广场舞dou起来 #零基础学舞.mkv"
ffprobe -v error -show_entries stream=codec_type -of csv=p=0 \
  "/Users/hjjtongxue/Documents/视频解析工具/output_multiformat_verify/朝看天色暮看云广场舞背面完整版 @小寒六六教程号 #原创编舞 @舞清秋🍒广场舞 #小寒六六编舞 #小寒六六 #广场舞dou起来 #零基础学舞.mov"
ffprobe -v error -show_entries stream=codec_type -of csv=p=0 \
  "/Users/hjjtongxue/Documents/视频解析工具/output_multiformat_verify/朝看天色暮看云广场舞背面完整版 @小寒六六教程号 #原创编舞 @舞清秋🍒广场舞 #小寒六六编舞 #小寒六六 #广场舞dou起来 #零基础学舞.webm"
```

Expected:
- `mkv` prints both `video` and `audio`
- `mov` prints both `video` and `audio`
- `webm` prints both `video` and `audio`

- [ ] **Step 5: Commit final verification-safe state**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py /Users/hjjtongxue/Documents/视频解析工具/app.py /Users/hjjtongxue/Documents/视频解析工具/templates/index.html /Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py
git commit -m "feat: complete multi-format export support"
```
