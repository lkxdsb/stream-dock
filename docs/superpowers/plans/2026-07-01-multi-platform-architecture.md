# Multi-Platform Local Fetch Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the current Douyin-only local tool into a multi-platform architecture foundation with a unified fetch pipeline, a migrated Douyin adapter, and skeleton adapters for Kuaishou and Bilibili while preserving the current local web and CLI behavior.

**Architecture:** Introduce a `fetchers/` package with unified models, adapter registry, pipeline, downloader, and exporters. Move Douyin-specific capture logic into `DouyinAdapter`, keep the export layer reusable, and make both the CLI and FastAPI entrypoints call the new pipeline instead of platform-specific inline logic.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, Playwright, requests, ffmpeg/ffprobe, unittest, browser-cookie3.

---

## File Structure

- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/__init__.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/models.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/registry.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/pipeline.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/downloader.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/exporters.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/__init__.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/base.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/douyin.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/kuaishou.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/bilibili.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/app.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py`

### Task 1: Create unified fetcher models and adapter contracts

**Files:**
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/__init__.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/models.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/__init__.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/base.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py`

- [ ] **Step 1: Write the failing model and contract tests**

```python
# /Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py
import unittest

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.models import ExportRequest, MediaFetchResult, MediaStream, ResolvedMediaSelection


class ModelContractTests(unittest.TestCase):
    def test_media_stream_records_quality_fields(self):
        stream = MediaStream(
            url='https://example.com/video.mp4',
            stream_type='video',
            container='mp4',
            codec='h264',
            width=1080,
            height=1920,
            bitrate=1467000,
            filesize=None,
            quality_label='1080p',
        )
        self.assertEqual(stream.stream_type, 'video')
        self.assertEqual(stream.quality_label, '1080p')

    def test_fetch_result_keeps_preferred_streams(self):
        video = MediaStream(url='https://example.com/video.mp4', stream_type='video')
        audio = MediaStream(url='https://example.com/audio.m4a', stream_type='audio')
        result = MediaFetchResult(
            platform='douyin',
            content_type='video',
            title='demo',
            source_url='https://v.douyin.com/demo/',
            final_url='https://www.douyin.com/video/1',
            cover_url=None,
            author=None,
            video_streams=[video],
            audio_streams=[audio],
            preferred_video=video,
            preferred_audio=audio,
            metadata={},
        )
        self.assertEqual(result.platform, 'douyin')
        self.assertEqual(result.preferred_audio.url, 'https://example.com/audio.m4a')

    def test_export_request_and_selection_are_simple_value_models(self):
        request = ExportRequest(output_path='/tmp/out', output_type='mp4')
        video = MediaStream(url='https://example.com/video.mp4', stream_type='video')
        selection = ResolvedMediaSelection(video_stream=video, audio_stream=None, title='demo', output_type='mp4')
        self.assertEqual(request.output_type, 'mp4')
        self.assertEqual(selection.title, 'demo')

    def test_base_adapter_exposes_required_methods(self):
        methods = {name for name in dir(BasePlatformAdapter) if not name.startswith('_')}
        self.assertTrue({'platform_name', 'can_handle', 'normalize_link', 'fetch_media'}.issubset(methods))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd /Users/hjjtongxue/Documents/视频解析工具
source $(conda info --base)/etc/profile.d/conda.sh
conda activate jj
python -m unittest tests.test_platform_adapters.ModelContractTests -v
```

Expected: FAIL because the `fetchers` package and these models do not exist yet.

- [ ] **Step 3: Write the minimal model and base adapter implementation**

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/models.py
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
```

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/base.py
from __future__ import annotations

from fetchers.models import MediaFetchResult


class BasePlatformAdapter:
    platform_name = 'base'

    def can_handle(self, raw_link: str) -> bool:
        raise NotImplementedError

    def normalize_link(self, raw_link: str) -> str:
        raise NotImplementedError

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        raise NotImplementedError
```

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/__init__.py
from fetchers.models import ExportRequest, MediaFetchResult, MediaStream, ResolvedMediaSelection

__all__ = ['MediaStream', 'MediaFetchResult', 'ExportRequest', 'ResolvedMediaSelection']
```

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/__init__.py
from fetchers.adapters.base import BasePlatformAdapter

__all__ = ['BasePlatformAdapter']
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
python -m unittest tests.test_platform_adapters.ModelContractTests -v
```

Expected: PASS with 4 tests.

- [ ] **Step 5: Commit**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/fetchers/__init__.py /Users/hjjtongxue/Documents/视频解析工具/fetchers/models.py /Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/__init__.py /Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/base.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py
git commit -m "feat: add multi-platform models and adapter base"
```

### Task 2: Add adapter registry and pipeline routing

**Files:**
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/registry.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/pipeline.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/kuaishou.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/bilibili.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py`

- [ ] **Step 1: Write failing registry and platform detection tests**

```python
# append to /Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py
from fetchers.pipeline import detect_platform_adapter
from fetchers.registry import get_registered_adapters


class RegistryTests(unittest.TestCase):
    def test_registry_exposes_three_platform_adapters(self):
        adapter_names = [adapter.platform_name for adapter in get_registered_adapters()]
        self.assertEqual(adapter_names, ['douyin', 'kuaishou', 'bilibili'])

    def test_pipeline_detects_platform_by_url(self):
        self.assertEqual(detect_platform_adapter('https://v.douyin.com/abcd/').platform_name, 'douyin')
        self.assertEqual(detect_platform_adapter('https://www.kuaishou.com/short-video/123').platform_name, 'kuaishou')
        self.assertEqual(detect_platform_adapter('https://www.bilibili.com/video/BV1xx411c7mD').platform_name, 'bilibili')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python -m unittest tests.test_platform_adapters.RegistryTests -v
```

Expected: FAIL because registry and pipeline do not exist yet.

- [ ] **Step 3: Implement minimal URL-based adapter skeletons and registry**

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/kuaishou.py
from __future__ import annotations

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.models import MediaFetchResult


class KuaishouAdapter(BasePlatformAdapter):
    platform_name = 'kuaishou'

    def can_handle(self, raw_link: str) -> bool:
        return 'kuaishou.com' in raw_link or 'v.kuaishou.com' in raw_link

    def normalize_link(self, raw_link: str) -> str:
        return raw_link

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        raise NotImplementedError('Kuaishou adapter not implemented yet')
```

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/bilibili.py
from __future__ import annotations

from fetchers.adapters.base import BasePlatformAdapter
from fetchers.models import MediaFetchResult


class BilibiliAdapter(BasePlatformAdapter):
    platform_name = 'bilibili'

    def can_handle(self, raw_link: str) -> bool:
        return 'bilibili.com' in raw_link or 'b23.tv' in raw_link

    def normalize_link(self, raw_link: str) -> str:
        return raw_link

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        raise NotImplementedError('Bilibili adapter not implemented yet')
```

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/registry.py
from fetchers.adapters.bilibili import BilibiliAdapter
from fetchers.adapters.kuaishou import KuaishouAdapter
from fetchers.adapters.douyin import DouyinAdapter


def get_registered_adapters():
    return [DouyinAdapter(), KuaishouAdapter(), BilibiliAdapter()]
```

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/pipeline.py
from fetchers.registry import get_registered_adapters


def detect_platform_adapter(raw_link: str):
    for adapter in get_registered_adapters():
        if adapter.can_handle(raw_link):
            return adapter
    raise ValueError('Unsupported platform link')
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
python -m unittest tests.test_platform_adapters.RegistryTests -v
```

Expected: PASS with 2 tests.

- [ ] **Step 5: Commit**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/fetchers/registry.py /Users/hjjtongxue/Documents/视频解析工具/fetchers/pipeline.py /Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/kuaishou.py /Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/bilibili.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py
git commit -m "feat: add platform registry and detection"
```

### Task 3: Move export and download logic into reusable fetcher modules

**Files:**
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/downloader.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/exporters.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py`

- [ ] **Step 1: Write failing reuse tests for the exporter module**

```python
# append to /Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py
from fetchers.exporters import OUTPUT_FORMATS as SHARED_OUTPUT_FORMATS
from fetchers.exporters import export_media as shared_export_media


class SharedExporterTests(unittest.TestCase):
    def test_shared_exporter_exposes_all_formats(self):
        self.assertEqual(set(SHARED_OUTPUT_FORMATS), {'m4a', 'mp3', 'mp4', 'wav', 'flac', 'aac', 'ogg', 'opus', 'mkv', 'mov', 'webm'})

    def test_old_export_media_symbol_uses_shared_exporter(self):
        self.assertIs(shared_export_media, export_media)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python -m unittest tests.test_douyin_formats.SharedExporterTests -v
```

Expected: FAIL because `fetchers.exporters` does not exist yet.

- [ ] **Step 3: Move exporter and downloader helpers into reusable modules**

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/downloader.py
from __future__ import annotations

from pathlib import Path

import requests


def download_media(url: str, destination: Path, *, user_agent: str, referer: str = 'https://www.douyin.com/') -> Path:
    headers = {'User-Agent': user_agent, 'Referer': referer}
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination
```

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/exporters.py
# move OutputFormatSpec, OUTPUT_FORMATS, run_ffmpeg, validate_output_request,
# resolve_audio_source, mux_streams, transcode_audio, export_audio,
# transcode_to_webm, export_video, export_media here unchanged in behavior
```

```python
# /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py
from fetchers.downloader import download_media
from fetchers.exporters import (
    OUTPUT_FORMATS,
    export_media,
    get_output_format_spec,
    is_audio_output,
    is_video_output,
    validate_output_request,
)

SUPPORTED_OUTPUT_TYPES = set(OUTPUT_FORMATS)
# remove duplicate exporter/downloader definitions from this file
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
python -m unittest tests.test_douyin_formats tests.test_app -v
```

Expected: PASS with the existing format tests still green.

- [ ] **Step 5: Commit**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/fetchers/downloader.py /Users/hjjtongxue/Documents/视频解析工具/fetchers/exporters.py /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py
git commit -m "refactor: share downloader and exporter modules"
```

### Task 4: Implement the migrated Douyin adapter and wire the pipeline

**Files:**
- Create: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/douyin.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/fetchers/pipeline.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py`

- [ ] **Step 1: Write failing tests for the Douyin adapter and pipeline execution**

```python
# append to /Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py
from fetchers.adapters.douyin import DouyinAdapter
from fetchers.models import ExportRequest, MediaFetchResult, MediaStream
from fetchers.pipeline import run_pipeline


class DouyinAdapterTests(unittest.TestCase):
    def test_douyin_adapter_recognizes_douyin_links(self):
        adapter = DouyinAdapter()
        self.assertTrue(adapter.can_handle('https://v.douyin.com/abcd/'))
        self.assertTrue(adapter.can_handle('https://www.douyin.com/video/123'))
        self.assertFalse(adapter.can_handle('https://www.bilibili.com/video/BV1xx411c7mD'))

    def test_pipeline_runs_with_injected_fake_adapter(self):
        class FakeAdapter:
            platform_name = 'douyin'
            def can_handle(self, raw_link: str) -> bool: return True
            def normalize_link(self, raw_link: str) -> str: return 'normalized-link'
            def fetch_media(self, normalized_link: str) -> MediaFetchResult:
                audio = MediaStream(url='https://example.com/audio.m4a', stream_type='audio')
                return MediaFetchResult(
                    platform='douyin',
                    content_type='video',
                    title='demo',
                    source_url=raw_link,
                    final_url='https://www.douyin.com/video/1',
                    cover_url=None,
                    author=None,
                    video_streams=[],
                    audio_streams=[audio],
                    preferred_video=None,
                    preferred_audio=audio,
                    metadata={},
                )

        result = run_pipeline(
            raw_link='https://v.douyin.com/demo/',
            export_request=ExportRequest(output_path='/tmp/out', output_type='mp3'),
            adapter=FakeAdapter(),
            dry_run=True,
        )
        self.assertEqual(result['platform'], 'douyin')
        self.assertEqual(result['normalized_link'], 'normalized-link')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python -m unittest tests.test_platform_adapters.DouyinAdapterTests -v
```

Expected: FAIL because `DouyinAdapter` and `run_pipeline()` do not exist yet.

- [ ] **Step 3: Implement `DouyinAdapter` by moving current Douyin capture code**

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/douyin.py
# move these behaviors from douyin_fetch.py into the class:
# - extract_first_url helper usage
# - classify_media_url / choose_media_capture
# - playwright no-login capture
# - Chrome cookies fallback
# - audio-url enrichment retry
# - build MediaFetchResult with MediaStream objects
```

```python
# /Users/hjjtongxue/Documents/视频解析工具/fetchers/pipeline.py
from fetchers.downloader import download_media
from fetchers.exporters import export_media, validate_output_request
from fetchers.models import ExportRequest


def run_pipeline(raw_link: str, export_request: ExportRequest, adapter=None, dry_run: bool = False):
    selected_adapter = adapter or detect_platform_adapter(raw_link)
    normalized_link = selected_adapter.normalize_link(raw_link)
    fetch_result = selected_adapter.fetch_media(normalized_link)
    validate_output_request(media_kind=fetch_result.content_type, output_type=export_request.output_type)
    if dry_run:
        return {
            'platform': fetch_result.platform,
            'normalized_link': normalized_link,
            'title': fetch_result.title,
            'final_url': fetch_result.final_url,
        }
    raise NotImplementedError('Non-dry-run pipeline wiring added in the next step')
```

- [ ] **Step 4: Replace inline Douyin flow in `douyin_fetch.py` with pipeline calls and rerun tests**

```python
# /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py
from fetchers.models import ExportRequest
from fetchers.pipeline import run_pipeline

# in main():
result = run_pipeline(
    raw_link=args.link,
    export_request=ExportRequest(output_path=args.outputPath, output_type=args.outputType),
)
print(f"[douyin-fetch] normalized link: {result['normalized_link']}")
print(f"[douyin-fetch] capture strategy: {result['capture_strategy']}")
print(f"[douyin-fetch] captured media kind: {result['media_kind']}")
print(f"[douyin-fetch] final page: {result['final_url']}")
print(f"[douyin-fetch] output file: {result['output_file']}")
```

Run:
```bash
python -m unittest tests.test_platform_adapters tests.test_douyin_formats tests.test_app -v
```

Expected: PASS with the old Douyin tests still green.

- [ ] **Step 5: Commit**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/douyin.py /Users/hjjtongxue/Documents/视频解析工具/fetchers/pipeline.py /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py
git commit -m "refactor: migrate douyin flow into platform adapter"
```

### Task 5: Wire FastAPI to the shared pipeline and verify the local tool still works

**Files:**
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/app.py`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py`

- [ ] **Step 1: Write a failing API smoke test that checks platform info is returned**

```python
# append to /Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py
class ApiResponseShapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_api_returns_platform_field_on_success(self):
        from unittest.mock import patch

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            with patch('app.subprocess.run') as mocked_run:
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = '[douyin-fetch] platform: douyin\n[douyin-fetch] output file: /tmp/demo.mp3\n'
                mocked_run.return_value.stderr = ''
                response = await client.post('/api/fetch', json={
                    'link': 'https://v.douyin.com/demo/',
                    'outputPath': '/tmp/out',
                    'outputType': 'mp3',
                })
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['outputPath'], '/tmp/demo.mp3')
```
```

- [ ] **Step 2: Run the API smoke test to verify current behavior**

Run:
```bash
python -m unittest tests.test_app.ApiResponseShapeTests -v
```

Expected: PASS or minimal adjustment only. If it fails for the wrong reason, fix the test setup before moving on.

- [ ] **Step 3: Keep `app.py` entrypoint stable and only update parsing helpers if needed**

```python
# /Users/hjjtongxue/Documents/视频解析工具/app.py
# Keep subprocess-based boundary for now.
# Only add extra stdout parsing helpers if the new CLI output adds fields like platform or title.
```

- [ ] **Step 4: Run full application tests**

Run:
```bash
python -m unittest tests.test_app tests.test_platform_adapters tests.test_douyin_formats -v
```

Expected: PASS with 0 failures.

- [ ] **Step 5: Commit**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/app.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py
git commit -m "test: verify local ui against migrated pipeline"
```

### Task 6: Real Douyin regression verification on the migrated architecture

**Files:**
- Modify only if verification reveals a real bug.

- [ ] **Step 1: Run the complete automated suite**

Run:
```bash
cd /Users/hjjtongxue/Documents/视频解析工具
source $(conda info --base)/etc/profile.d/conda.sh
conda activate jj
python -m unittest tests.test_platform_adapters tests.test_douyin_formats tests.test_app -v
```

Expected: PASS.

- [ ] **Step 2: Verify the migrated CLI on a real Douyin sample**

Run:
```bash
mkdir -p /Users/hjjtongxue/Documents/视频解析工具/output_platform_verify
python douyin_fetch.py \
  --link "https://v.douyin.com/Tw-kxBn3n6w/" \
  --outputPath "/Users/hjjtongxue/Documents/视频解析工具/output_platform_verify" \
  --outputType mp4
python douyin_fetch.py \
  --link "https://v.douyin.com/Tw-kxBn3n6w/" \
  --outputPath "/Users/hjjtongxue/Documents/视频解析工具/output_platform_verify" \
  --outputType mp3
```

Expected: both commands print output file paths and exit with code 0.

- [ ] **Step 3: Probe the generated mp4 to confirm dual tracks remain intact**

Run:
```bash
ffprobe -v error -show_entries stream=codec_type -of csv=p=0 \
  "/Users/hjjtongxue/Documents/视频解析工具/output_platform_verify/朝看天色暮看云广场舞背面完整版 @小寒六六教程号 #原创编舞 @舞清秋🍒广场舞 #小寒六六编舞 #小寒六六 #广场舞dou起来 #零基础学舞.mp4"
```

Expected: prints both `video` and `audio`.

- [ ] **Step 4: Start the local server and verify the homepage still lists the formats**

Run:
```bash
source $(conda info --base)/etc/profile.d/conda.sh
conda activate jj
uvicorn app:app --host 127.0.0.1 --port 8000
```

In a second shell:
```bash
python - <<'PY'
import urllib.request
html = urllib.request.urlopen('http://127.0.0.1:8000/').read().decode('utf-8')
for marker in ['value="wav"', 'value="flac"', 'value="aac"', 'value="ogg"', 'value="opus"', 'value="mkv"', 'value="mov"', 'value="webm"']:
    assert marker in html, marker
print('homepage options ok')
PY
```

Expected: `homepage options ok`.

- [ ] **Step 5: Commit the migration-complete state**

```bash
git add /Users/hjjtongxue/Documents/视频解析工具/fetchers /Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py /Users/hjjtongxue/Documents/视频解析工具/app.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_platform_adapters.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_douyin_formats.py /Users/hjjtongxue/Documents/视频解析工具/tests/test_app.py
git commit -m "refactor: introduce multi-platform fetch architecture"
```
