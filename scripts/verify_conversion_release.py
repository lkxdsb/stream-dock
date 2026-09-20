#!/usr/bin/env python3
"""Verify pinned M7 conversion evidence and emit one auditable release report."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / 'scripts' / 'conversion_release_contract.json'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AssertionError(f'missing evidence report: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def tool_version(command: str, *args: str) -> str | None:
    executable = shutil.which(command)
    if not executable:
        return None
    try:
        result = subprocess.run([executable, *args], capture_output=True, text=True, timeout=20)
        value = (result.stdout or result.stderr).strip().splitlines()
        return value[0] if value else None
    except Exception:
        return None


def source_revision() -> str | None:
    if os.getenv('GITHUB_SHA'):
        return os.environ['GITHUB_SHA']
    head = ROOT / '.git' / 'HEAD'
    if not head.is_file():
        return None
    value = head.read_text(encoding='utf-8').strip()
    if value.startswith('ref: '):
        ref = ROOT / '.git' / value[5:]
        return ref.read_text(encoding='utf-8').strip() if ref.is_file() else None
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument('--matrix', type=Path, default=ROOT / 'report_figures' / 'conversion_matrix_real_latest.json')
    parser.add_argument('--robustness', type=Path, default=ROOT / 'report_figures' / 'conversion_robustness_latest.json')
    parser.add_argument('--complex', dest='complex_report', type=Path, default=ROOT / 'report_figures' / 'conversion_complex_corpus_latest.json')
    parser.add_argument('--report', type=Path, default=ROOT / 'report_figures' / 'conversion_release_latest.json')
    args = parser.parse_args()

    contract = load(args.contract)
    matrix = load(args.matrix)
    robustness = load(args.robustness)
    complex_report = load(args.complex_report)
    failures: list[str] = []

    expected_matrix = set(contract['matrixRoutes'])
    matrix_rows = matrix.get('results') or []
    actual_matrix = {f"{row.get('source')}->{row.get('target')}" for row in matrix_rows}
    if expected_matrix != actual_matrix:
        failures.append(f'matrix route mismatch missing={sorted(expected_matrix - actual_matrix)} unexpected={sorted(actual_matrix - expected_matrix)}')
    failed_matrix = [f"{row.get('source')}->{row.get('target')}" for row in matrix_rows if row.get('status') != 'PASS']
    if failed_matrix:
        failures.append(f'matrix non-pass routes={failed_matrix}')

    required_robustness = set(contract['robustnessCases']['required'])
    if sys.platform == 'darwin':
        required_robustness.update(contract['robustnessCases'].get('darwinRequired') or [])
    robustness_rows = robustness.get('results') or []
    actual_robustness = {str(row.get('name')) for row in robustness_rows}
    missing_robustness = required_robustness - actual_robustness
    if missing_robustness:
        failures.append(f'robustness cases silently missing={sorted(missing_robustness)}')
    failed_robustness = [str(row.get('name')) for row in robustness_rows if row.get('status') != 'PASS']
    if failed_robustness:
        failures.append(f'robustness non-pass cases={failed_robustness}')

    expected_complex = {
        (item['fixture'], item['route']): item['expectedStatus']
        for item in contract['publicComplexCases']
    }
    public_rows = [row for row in (complex_report.get('results') or []) if row.get('provenance') == 'public']
    actual_complex = {(row.get('fixture'), f"{row.get('source')}->{row.get('target', '-')}"): row.get('status') for row in public_rows}
    if set(expected_complex) != set(actual_complex):
        failures.append(
            f'complex case mismatch missing={sorted(set(expected_complex) - set(actual_complex))} '
            f'unexpected={sorted(set(actual_complex) - set(expected_complex))}'
        )
    wrong_status = [f'{fixture} {route}: {actual_complex.get((fixture, route))} != {status}' for (fixture, route), status in expected_complex.items() if actual_complex.get((fixture, route)) != status]
    if wrong_status:
        failures.append(f'complex status mismatch={wrong_status}')
    local_bad = [row.get('fixture') for row in (complex_report.get('results') or []) if row.get('provenance') == 'user-provided' and row.get('status') not in {'PASS', 'SAFE_REJECTION', 'NO_EXECUTABLE_ROUTE'}]
    if local_bad:
        failures.append(f'user-provided complex cases failed={local_bad}')

    evidence = {
        'matrix': {'path': str(args.matrix), 'sha256': sha256(args.matrix), 'routes': len(actual_matrix), 'passed': len(matrix_rows) - len(failed_matrix)},
        'robustness': {'path': str(args.robustness), 'sha256': sha256(args.robustness), 'requiredCases': len(required_robustness), 'executed': len(robustness_rows)},
        'complex': {'path': str(args.complex_report), 'sha256': sha256(args.complex_report), 'publicCases': len(public_rows), 'localCases': len((complex_report.get('results') or [])) - len(public_rows)},
    }
    report = {
        'schemaVersion': 1,
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'sourceRevision': source_revision(),
        'contract': {'path': str(args.contract), 'sha256': sha256(args.contract)},
        'environment': {
            'platform': platform.platform(), 'python': sys.version.split()[0],
            'ffmpeg': tool_version('ffmpeg', '-version'),
            'libreoffice': tool_version('soffice', '--version'),
            'bsdtar': tool_version('bsdtar', '--version'),
        },
        'evidence': evidence,
        'status': 'PASS' if not failures else 'FAIL',
        'failures': failures,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"CONVERSION_RELEASE={report['status']} matrix={len(actual_matrix)}/{len(expected_matrix)} robustness={len(actual_robustness)}/{len(required_robustness)} complex={len(actual_complex)}/{len(expected_complex)}")
    for failure in failures:
        print(f'FAIL {failure}')
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
