# StreamDock conversion quality gates

File-conversion changes are accepted only after a real input file travels through the production converter and the output is reopened by an independent parser or target engine. HTTP success, a non-empty file, mocks, and unit tests are not substitutes for this gate.

## Required local gates

```bash
python -m pytest -q
python scripts/test_conversion_robustness.py
python scripts/test_conversion_fuzz.py --iterations 100
python scripts/test_conversion_matrix_real.py
python scripts/fetch_complex_conversion_corpus.py
python scripts/test_conversion_complex_corpus.py
```

- `test_conversion_robustness.py` covers high-risk semantic fixtures: Chinese, emoji, RTL, Unicode RTF, Office workbook structure, DOCX headers/footers/comments/table/image/TOC, APNG/GIF/TIFF frames, image quality, AMR, cover art, chapters, metadata, two audio tracks, two subtitle tracks, hardware encoding, encrypted ZIP, 7Z, RAR, split RAR, archive attributes, and malicious archives.
- `test_conversion_fuzz.py` generates deterministic random CSV/JSON/XLSX and RGBA image files, performs real round trips, and verifies malformed ZIP/PNG plus XXE rejection.
- `test_conversion_matrix_real.py` generates a valid real fixture for every executable non-PDF capability, runs every route, reopens structured/document/image outputs, fully decodes media, checks audio signal and video-frame variance, and writes a route-level JSON report.
- `fetch_complex_conversion_corpus.py` downloads pinned public FFmpeg, LibreOffice, Pillow, and IDPF/W3C fixtures into the git-ignored `.streamdock-complex-corpus/` directory and rejects any SHA-256 drift.
- `test_conversion_complex_corpus.py` supplements the full matrix with real user files and public complex files. It currently exercises binary Office, ODF, AMR speech, HEVC/AAC video, large multi-sheet XLSX, multi-frame/metadata-bearing images, and a multi-document EPUB. Every successful output is reopened independently and checked for structure, duration/dimensions, decodability, and semantic overlap. Expected fidelity guards such as multi-frame-to-single-image and multi-sheet-to-flat-table rejection are reported separately as `SAFE_REJECTION`.

The committed binary fixtures in `tests/fixtures/real/` are tiny public archive fixtures used for real 7Z, RAR, Unicode-path, metadata, and split-volume checks. Their provenance is recorded in that directory.

Generated reports are written to `report_figures/`:

- `conversion_robustness_latest.json`
- `conversion_fuzz_latest.json`
- `conversion_matrix_real_latest.json`
- `conversion_complex_corpus_latest.json`

The local-only `.streamdock-complex-corpus/local_sources.json` may reference user-provided files by absolute path. Those originals are never copied into the repository, and the local manifest is ignored by git. The committed public-corpus manifest records URL, license, expected SHA-256, and the complex features used by the test.

## Explicit degradation and safety policy

- Multi-frame input is never silently reduced to the first frame. Supported APNG/GIF/TIFF paths retain all frames; unsupported single-image targets return a clear error.
- CSV/JSON/TSV cannot represent multiple worksheets, formatting, charts, merges, or hidden state. Multiple non-empty worksheets are rejected; other structural downgrades are logged. XLS/ODS to XLSX is verified for sheets, formulas, styles, merges, hidden rows/columns, charts, Unicode and RTL.
- ZipCrypto ZIP passwords are accepted only for the current request and are never persisted. Unsupported encryption produces an actionable error.
- RAR split volumes must be uploaded together. They are collapsed into one task and validated for a contiguous part sequence.
- Office macros, OOXML external relationships, SVG scripts/external resources, and XML external entities are rejected before an engine opens the file. LibreOffice uses an isolated temporary profile.
- Direct HTTP media downloads retain a `.download` partial and resume with `Range`; arbitrary document/media encoders restart from retained input because their output bitstreams are not safely resumable.
- Conversion subprocesses have wall-clock, CPU, address-space and output-file limits. Engine-specific bounded semaphores prevent unbounded FFmpeg, LibreOffice, Pillow, archive, and data conversion concurrency.
