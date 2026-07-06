# File Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add StreamDock's first file conversion center with `/convert`, capability matrix, local stable/basic conversion execution, and vendor-only guidance.

**Architecture:** Keep media fetching in `fetchers/` and add an independent `converters/` package. `app.py` exposes conversion APIs, `templates/convert.html` renders the page, and `static/js/convert-*.js` handles file probing, conversion requests, logs, and results.

**Tech Stack:** FastAPI, Jinja2, Python stdlib (`csv`, `json`, `zipfile`, `tarfile`, `subprocess`), optional local libs (`Pillow`, `openpyxl`, `yaml`, `toml`), ffmpeg for audio/video, browser FormData APIs.

---

### Task 1: Conversion domain and registry

**Files:**
- Create: `converters/models.py`
- Create: `converters/registry.py`
- Create: `converters/__init__.py`
- Test: `tests/test_converters.py`

- [ ] Define capability levels `stable`, `basic`, `vendor` and conversion path metadata.
- [ ] Register all first-version capability paths from the approved design.
- [ ] Add tests proving representative stable/basic/vendor paths exist.

### Task 2: Local conversion adapters and pipeline

**Files:**
- Create: `converters/adapters/data.py`
- Create: `converters/adapters/image.py`
- Create: `converters/adapters/media.py`
- Create: `converters/adapters/subtitle.py`
- Create: `converters/adapters/archive.py`
- Create: `converters/adapters/document_basic.py`
- Create: `converters/pipeline.py`
- Test: `tests/test_converters.py`

- [ ] Implement data conversions for CSV/TSV/JSON/NDJSON/YAML/XML/TOML/XLSX where dependencies are available.
- [ ] Implement image conversions with Pillow when available.
- [ ] Implement audio/video conversions through ffmpeg.
- [ ] Implement subtitle and archive conversions with lightweight local code.
- [ ] Implement basic Markdown/HTML/TXT conversions with transparent quality notes.
- [ ] Return explicit errors for missing dependencies, unsupported paths, corrupted files, and vendor-only paths.

### Task 3: FastAPI routes

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

- [ ] Add `/convert` route.
- [ ] Add `/api/convert/capabilities`.
- [ ] Add `/api/convert/probe` using uploaded file name/extension.
- [ ] Add `/api/convert/run` accepting multipart file, output format, output directory.
- [ ] Add `/api/convert/select-output-dir` reusing existing directory selection.

### Task 4: Frontend page and assets

**Files:**
- Create: `templates/convert.html`
- Create: `static/css/convert.css`
- Create: `static/js/convert-capabilities.js`
- Create: `static/js/convert-form.js`
- Create: `static/js/convert-logs.js`
- Create: `static/js/convert-result.js`
- Modify: `templates/base.html`
- Test: `tests/test_app.py`

- [ ] Add top navigation entry “文件转换”.
- [ ] Render conversion workbench, capability groups, and vendor recommendation cards.
- [ ] Wire file selection, output format selection, output directory selection, conversion submit, logs, and result display.

### Task 5: Verification and cleanup

**Files:**
- Modify: `tests/test_app.py`
- Modify: `tests/test_converters.py`

- [ ] Add route/API/page tests for conversion module.
- [ ] Run focused tests for app and converters.
- [ ] Leave existing media parsing behavior untouched.
