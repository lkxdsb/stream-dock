#!/usr/bin/env python3
"""Deterministic real-file property/fuzz checks for StreamDock converters."""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from converters.pipeline import convert_file  # noqa: E402


TOKENS = ['中文', '😀', 'مرحبا', 'שלום', 'comma,value', 'quote"value', 'line\nbreak', '©€∑']


def require_result(result, route: str) -> Path:
    if not result.success or not result.output_path:
        raise AssertionError(f'{route} failed: {result.error}')
    return result.output_path


def run(seed: int, iterations: int, workdir: Path) -> dict[str, object]:
    from PIL import Image

    rng = random.Random(seed)
    passed = 0
    failures: list[dict[str, object]] = []
    for index in range(iterations):
        case = workdir / f'case-{index:04d}'; case.mkdir(parents=True)
        output = case / 'out'; output.mkdir()
        try:
            rows = []
            for row_index in range(rng.randint(2, 8)):
                rows.append({
                    'id': str(row_index),
                    'text': rng.choice(TOKENS) + rng.choice(TOKENS),
                    'number': str(rng.randint(-100000, 100000)),
                })
            source = case / 'random.csv'
            with source.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=['id', 'text', 'number']); writer.writeheader(); writer.writerows(rows)
            json_path = require_result(convert_file(source, source.name, 'csv', 'json', output), 'csv->json')
            decoded = json.loads(json_path.read_text(encoding='utf-8'))
            if decoded != rows:
                raise AssertionError(f'CSV/JSON mismatch: {decoded!r} != {rows!r}')
            xlsx_path = require_result(convert_file(json_path, json_path.name, 'json', 'xlsx', output), 'json->xlsx')
            csv_path = require_result(convert_file(xlsx_path, xlsx_path.name, 'xlsx', 'csv', output), 'xlsx->csv')
            with csv_path.open(encoding='utf-8-sig', newline='') as handle:
                roundtrip = list(csv.DictReader(handle))
            if roundtrip != rows:
                raise AssertionError(f'XLSX roundtrip mismatch: {roundtrip!r} != {rows!r}')

            width, height = rng.randint(8, 80), rng.randint(8, 80)
            pixels = bytes(rng.randrange(256) for _ in range(width * height * 4))
            png = case / 'random.png'; Image.frombytes('RGBA', (width, height), pixels).save(png)
            webp = require_result(convert_file(png, png.name, 'png', 'webp', output, image_quality=rng.randint(25, 95)), 'png->webp')
            with Image.open(webp) as decoded_image:
                decoded_image.load()
                if decoded_image.size != (width, height) or decoded_image.getbbox() is None:
                    raise AssertionError('decoded WebP dimensions/content invalid')
            passed += 1
        except Exception as exc:
            failures.append({'case': index, 'error': str(exc)})

    malformed = workdir / 'malformed'; malformed.mkdir()
    malformed_cases = [
        ('broken.zip', 'zip', 'folder', b'PK\x03\x04broken'),
        ('broken.png', 'png', 'jpg', b'\x89PNG\r\n\x1a\nbroken'),
        ('xxe.xml', 'xml', 'json', b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'),
    ]
    for filename, source_format, target_format, payload in malformed_cases:
        path = malformed / filename; path.write_bytes(payload)
        result = convert_file(path, filename, source_format, target_format, malformed / 'out')
        if result.success:
            failures.append({'case': filename, 'error': 'malformed input unexpectedly succeeded'})
        else:
            passed += 1
    return {'seed': seed, 'iterations': iterations, 'passed': passed, 'failed': len(failures), 'failures': failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=20260917)
    parser.add_argument('--iterations', type=int, default=40)
    parser.add_argument('--workdir', type=Path)
    parser.add_argument('--report', type=Path, default=ROOT / 'report_figures' / 'conversion_fuzz_latest.json')
    args = parser.parse_args()
    context = None
    if args.workdir:
        workdir = args.workdir.expanduser().resolve(); workdir.mkdir(parents=True, exist_ok=True)
    else:
        context = tempfile.TemporaryDirectory(prefix='streamdock-fuzz-'); workdir = Path(context.name)
    try:
        report = run(args.seed, args.iterations, workdir)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'REAL_CONVERSION_FUZZ={"passed" if not report["failed"] else "failed"} {report}')
        return 0 if not report['failed'] else 1
    finally:
        if context:
            context.cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
