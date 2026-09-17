#!/usr/bin/env python3
"""Run every route reachable from curated complex real-world fixtures.

Unlike unit tests, this runner uses user-provided documents and pinned public
corpus files, invokes the production conversion pipeline, reopens every output
with an independent parser/tool, and performs a small content-quality check.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from converters.adapters.document_basic import _rtf_to_text  # noqa: E402
from converters.models import ConversionLevel  # noqa: E402
from converters.pipeline import convert_file  # noqa: E402
from converters.registry import list_capabilities  # noqa: E402
from runtime_checks import augmented_path, validate_media_output  # noqa: E402

os.environ["PATH"] = augmented_path()
PUBLIC_MANIFEST = ROOT / "scripts" / "complex_conversion_corpus_sources.json"
DEFAULT_LOCAL_MANIFEST = ROOT / ".streamdock-complex-corpus" / "local_sources.json"
IMAGE_TARGETS = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "gif", "ico", "ppm", "pgm", "pbm", "pnm"}
MEDIA_TARGETS = {"mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "mp4", "mov", "mkv", "webm", "avi", "flv", "m4v", "3gp", "ts"}
TEXT_TARGETS = {"txt", "md", "markdown", "html", "rtf"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strip_markup(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def extract_text(path: Path, fmt: str, scratch: Path) -> str:
    fmt = fmt.lower()
    if fmt in {"txt", "md", "markdown", "csv", "tsv", "json", "html", "rtf"}:
        raw = path.read_text(encoding="utf-8", errors="strict")
        if fmt == "html":
            return strip_markup(raw)
        if fmt == "rtf":
            return _rtf_to_text(raw)
        return raw
    if fmt == "docx":
        from docx import Document
        document = Document(path)
        return "\n".join([p.text for p in document.paragraphs] + [c.text for t in document.tables for r in t.rows for c in r.cells])
    if fmt == "pptx":
        from pptx import Presentation
        presentation = Presentation(path)
        return "\n".join(shape.text for slide in presentation.slides for shape in slide.shapes if hasattr(shape, "text"))
    if fmt == "xlsx":
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=False)
        try:
            return "\n".join(str(cell.value) for sheet in workbook.worksheets for row in sheet.iter_rows() for cell in row if cell.value is not None)
        finally:
            workbook.close()
    if fmt == "epub":
        with zipfile.ZipFile(path) as archive:
            chunks = []
            for name in archive.namelist():
                if name.lower().endswith((".xhtml", ".html", ".htm")):
                    chunks.append(strip_markup(archive.read(name).decode("utf-8", errors="ignore")))
            return "\n".join(chunks)
    if fmt in {"odt", "ods", "odp"}:
        with zipfile.ZipFile(path) as archive:
            return strip_markup(archive.read("content.xml").decode("utf-8", errors="ignore"))
    if fmt in {"doc", "xls", "ppt"}:
        modern = {"doc": "docx", "xls": "xlsx", "ppt": "pptx"}[fmt]
        converted = scratch / f"source-{sha256(path)[:12]}.{modern}"
        if not converted.exists():
            profile = scratch / f"lo-profile-{sha256(path)[:12]}"
            profile.mkdir(exist_ok=True)
            process = subprocess.run(
                ["soffice", "--headless", f"-env:UserInstallation={profile.resolve().as_uri()}", "--convert-to", modern, "--outdir", str(scratch), str(path)],
                capture_output=True, text=True, timeout=120,
            )
            produced = scratch / f"{path.stem}.{modern}"
            if process.returncode != 0 or not produced.exists():
                raise AssertionError(process.stderr.strip() or "LibreOffice source extraction failed")
            produced.replace(converted)
        return extract_text(converted, modern, scratch)
    return ""


def meaningful_tokens(value: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[\w\u3400-\u9fff]{3,}", value) if not token.isdigit()}


def validate_text_quality(source_text: str, output_text: str) -> dict[str, Any]:
    if not output_text.strip() or "\ufffd" in output_text:
        raise AssertionError("empty text or Unicode replacement character in output")
    source_tokens = meaningful_tokens(source_text)
    output_tokens = meaningful_tokens(output_text)
    overlap = source_tokens & output_tokens
    required = min(5, max(1, math.ceil(len(source_tokens) * 0.4)))
    if source_tokens and len(overlap) < required:
        raise AssertionError(f"semantic token overlap too small: {len(overlap)}/{len(source_tokens)}")
    return {"sourceTokens": len(source_tokens), "outputTokens": len(output_tokens), "sharedTokens": len(overlap)}


def validate_image(source: Path, output: Path, target: str) -> dict[str, Any]:
    from PIL import Image, ImageStat
    with Image.open(source) as before:
        before_size = before.size
        before_frames = int(getattr(before, "n_frames", 1))
    outputs = [output]
    if output.is_dir():
        outputs = sorted(path for path in output.rglob("*") if path.is_file())
    if not outputs:
        raise AssertionError("image conversion produced no files")
    frames = 0
    for item in outputs:
        with Image.open(item) as image:
            # ICO encoders choose one of the conventional icon sizes and may
            # downscale large source art while preserving its aspect ratio.
            if target == "ico":
                before_ratio = before_size[0] / before_size[1]
                output_ratio = image.size[0] / image.size[1]
                if max(image.size) > 256 or abs(before_ratio - output_ratio) > 0.03:
                    raise AssertionError(f"invalid ICO resize: {before_size} -> {image.size}")
            elif image.size != before_size:
                raise AssertionError(f"image dimensions changed: {before_size} -> {image.size}")
            frames += int(getattr(image, "n_frames", 1))
            image.seek(0); image.load()
            if not any(high > low for low, high in ImageStat.Stat(image.convert("RGB")).extrema):
                raise AssertionError("blank or solid image output")
    if before_frames > 1 and target in {"png", "gif"} and frames < before_frames:
        raise AssertionError(f"animation frames lost: {before_frames} -> {frames}")
    return {"size": before_size, "sourceFrames": before_frames, "outputFrames": frames, "files": len(outputs)}


def media_duration(path: Path) -> float:
    process = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return float(process.stdout.strip())


def validate_media(source: Path, output: Path, target: str) -> dict[str, Any]:
    expected_kind = "video" if target in {"mp4", "mov", "mkv", "webm", "avi", "flv", "m4v", "3gp", "ts"} else "audio"
    report = validate_media_output(output, expected_kind=expected_kind)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"], capture_output=True, timeout=180, check=True)
    before = media_duration(source); after = media_duration(output)
    if abs(before - after) > max(1.0, before * 0.04):
        raise AssertionError(f"duration drift too large: {before:.3f}s -> {after:.3f}s")
    return {"sourceDuration": before, "outputDuration": after, **report}


def validate_structured(output: Path, target: str, source_text: str, scratch: Path) -> dict[str, Any]:
    if target in TEXT_TARGETS:
        return validate_text_quality(source_text, extract_text(output, target, scratch))
    if target == "docx":
        from docx import Document
        document = Document(output)
        if not document.paragraphs and not document.tables:
            raise AssertionError("empty DOCX structure")
        return {"paragraphs": len(document.paragraphs), "tables": len(document.tables), **validate_text_quality(source_text, extract_text(output, target, scratch))}
    if target == "pptx":
        from pptx import Presentation
        presentation = Presentation(output)
        if not presentation.slides:
            raise AssertionError("empty PPTX structure")
        shapes = sum(len(slide.shapes) for slide in presentation.slides)
        if shapes == 0:
            raise AssertionError("PPTX contains no shapes")
        quality = validate_text_quality(source_text, extract_text(output, target, scratch)) if meaningful_tokens(source_text) else {}
        return {"slides": len(presentation.slides), "shapes": shapes, **quality}
    if target == "xlsx":
        from openpyxl import load_workbook
        workbook = load_workbook(output, read_only=False, data_only=False)
        try:
            formulas = sum(1 for sheet in workbook for row in sheet.iter_rows() for cell in row if isinstance(cell.value, str) and cell.value.startswith("="))
            return {"sheets": len(workbook.sheetnames), "formulas": formulas, **validate_text_quality(source_text, extract_text(output, target, scratch))}
        finally:
            workbook.close()
    if target in {"csv", "tsv", "json"}:
        raw = output.read_text(encoding="utf-8", errors="strict")
        if target == "json":
            json.loads(raw)
        else:
            rows = list(csv.reader(raw.splitlines(), delimiter="\t" if target == "tsv" else ","))
            if not rows:
                raise AssertionError("empty table output")
        return validate_text_quality(source_text, raw)
    if output.stat().st_size == 0:
        raise AssertionError("empty output")
    return {"bytes": output.stat().st_size}


def load_fixtures(corpus_root: Path, local_manifest: Path | None) -> list[dict[str, Any]]:
    manifest = json.loads(PUBLIC_MANIFEST.read_text(encoding="utf-8"))
    fixtures = []
    for item in manifest["fixtures"]:
        fixture = dict(item); fixture["path"] = str(corpus_root / item["relativePath"]); fixture["provenance"] = "public"
        fixtures.append(fixture)
    if local_manifest and local_manifest.exists():
        for item in json.loads(local_manifest.read_text(encoding="utf-8"))["fixtures"]:
            fixture = dict(item); fixture["provenance"] = "user-provided"
            fixtures.append(fixture)
    return fixtures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, default=ROOT / ".streamdock-complex-corpus")
    parser.add_argument("--local-manifest", type=Path, default=DEFAULT_LOCAL_MANIFEST)
    parser.add_argument("--report", type=Path, default=ROOT / "report_figures" / "conversion_complex_corpus_latest.json")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    fixtures = load_fixtures(args.corpus_root, args.local_manifest)
    context = tempfile.TemporaryDirectory(prefix="streamdock-complex-corpus-")
    workdir = Path(context.name); scratch = workdir / "scratch"; scratch.mkdir(); outputs = workdir / "outputs"; outputs.mkdir()
    rows: list[dict[str, Any]] = []
    try:
        for fixture in fixtures:
            source = fixture["format"].lower(); source_path = Path(fixture["path"]).expanduser().resolve()
            if not source_path.exists():
                rows.append({"fixture": fixture["id"], "source": source, "status": "MISSING", "error": str(source_path)}); continue
            if fixture.get("sha256") and sha256(source_path) != fixture["sha256"]:
                rows.append({"fixture": fixture["id"], "source": source, "status": "HASH_MISMATCH"}); continue
            routes = [cap for cap in list_capabilities() if cap.source == source and cap.level != ConversionLevel.VENDOR and "pdf" not in (cap.source, cap.target) and (cap.source, cap.target) != ("pptx", "png")]
            if not routes:
                rows.append({"fixture": fixture["id"], "source": source, "status": "NO_EXECUTABLE_ROUTE", "sha256": sha256(source_path), "bytes": source_path.stat().st_size}); continue
            source_text = "" if source in {"amr", "mp4", "png", "jpg", "jpeg", "gif", "tiff"} else extract_text(source_path, source, scratch)
            for capability in routes:
                target = capability.target; started = time.perf_counter(); case_dir = outputs / f"{len(rows):03d}-{fixture['id']}-{target}"; case_dir.mkdir()
                row: dict[str, Any] = {"fixture": fixture["id"], "provenance": fixture["provenance"], "source": source, "target": target, "status": "FAIL", "inputSha256": sha256(source_path), "inputBytes": source_path.stat().st_size}
                try:
                    result = convert_file(source_path, source_path.name, source, target, case_dir, image_quality=88)
                    if not result.success or not result.output_path:
                        error = result.error or "conversion produced no output"
                        if any(marker in error for marker in ("无法完整保留所有帧", "多个非空工作表")):
                            row.update(status="SAFE_REJECTION", error=error)
                        else:
                            raise AssertionError(error)
                    else:
                        output = result.output_path
                        if source in {"png", "jpg", "jpeg", "gif", "tiff"} and target in IMAGE_TARGETS:
                            validation = validate_image(source_path, output, target)
                        elif source in {"amr", "mp4"} and target in MEDIA_TARGETS:
                            validation = validate_media(source_path, output, target)
                        else:
                            validation = validate_structured(output, target, source_text, scratch)
                        row.update(status="PASS", outputPath=str(output), validation=validation)
                except Exception as exc:
                    row["error"] = str(exc)
                row["elapsedSeconds"] = round(time.perf_counter() - started, 3); rows.append(row)
        counts = {status: sum(row["status"] == status for row in rows) for status in sorted({row["status"] for row in rows})}
        report = {"generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "workdir": str(workdir), "counts": counts, "results": rows}
        args.report.parent.mkdir(parents=True, exist_ok=True); args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("COMPLEX_CORPUS=" + ", ".join(f"{key}={value}" for key, value in counts.items()))
        for row in rows:
            if row["status"] not in {"PASS", "SAFE_REJECTION", "NO_EXECUTABLE_ROUTE"}:
                print(f"{row['status']} {row['fixture']} {row.get('source')}->{row.get('target', '-')}: {row.get('error', '')}")
        if args.keep:
            print(f"WORKDIR={workdir}"); context.cleanup = lambda: None  # type: ignore[method-assign]
        return 0 if not any(row["status"] in {"FAIL", "MISSING", "HASH_MISMATCH"} for row in rows) else 1
    finally:
        context.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
