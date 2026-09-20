from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import ConversionCapability


ROOT = Path(__file__).resolve().parents[1]
RELEASE_CONTRACT = ROOT / 'scripts' / 'conversion_release_contract.json'
RELEASE_REPORT = ROOT / 'report_figures' / 'conversion_release_latest.json'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def release_contract() -> dict[str, Any]:
    return json.loads(RELEASE_CONTRACT.read_text(encoding='utf-8'))


def release_route_keys() -> set[str]:
    return {route.replace('->', ':') for route in release_contract()['matrixRoutes']}


def _current_revision() -> str | None:
    if os.getenv('GITHUB_SHA'):
        return os.environ['GITHUB_SHA']
    git_dir = ROOT / '.git'
    head = git_dir / 'HEAD'
    if not head.is_file():
        return None
    value = head.read_text(encoding='utf-8').strip()
    if not value.startswith('ref: '):
        return value
    ref_name = value[5:]
    ref = git_dir / ref_name
    if ref.is_file():
        return ref.read_text(encoding='utf-8').strip()
    packed = git_dir / 'packed-refs'
    if packed.is_file():
        for line in packed.read_text(encoding='utf-8', errors='replace').splitlines():
            if line and not line.startswith(('#', '^')):
                revision, _, name = line.partition(' ')
                if name == ref_name:
                    return revision
    return None


def release_status(report_path: Path = RELEASE_REPORT) -> dict[str, Any]:
    contract = release_contract()
    base = {
        'schemaVersion': 1,
        'contractSha256': _sha256(RELEASE_CONTRACT),
        'expectedRoutes': len(contract['matrixRoutes']),
        'expectedRobustnessCases': len(contract['robustnessCases']['required']),
        'expectedPublicComplexCases': len(contract['publicComplexCases']),
    }
    if not report_path.is_file():
        return {**base, 'status': 'unknown', 'current': False, 'detail': '当前安装还没有生成发布验收报告'}
    try:
        report = json.loads(report_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return {**base, 'status': 'invalid', 'current': False, 'detail': f'发布验收报告无法读取：{exc}'}
    current_revision = _current_revision()
    report_revision = report.get('sourceRevision')
    current = bool(current_revision and report_revision and current_revision == report_revision)
    verdict = str(report.get('status') or 'unknown').lower()
    status = verdict if current or verdict == 'fail' else 'stale'
    evidence = report.get('evidence') or {}
    safe_evidence = {
        name: {key: value for key, value in dict(evidence.get(name) or {}).items() if key != 'path'}
        for name in ('matrix', 'robustness', 'complex')
    }
    return {
        **base,
        'status': status,
        'current': current,
        'detail': '当前版本发布门禁已通过' if status == 'pass' else '验收报告不属于当前代码版本' if status == 'stale' else '发布门禁未通过' if status == 'fail' else base.get('detail', '发布验收状态未知'),
        'generatedAt': report.get('generatedAt'),
        'sourceRevision': report_revision,
        'currentRevision': current_revision,
        # Evidence reports contain local absolute paths for offline audit.  The
        # HTTP-facing summary deliberately exposes counts/hashes only.
        'evidence': safe_evidence,
        'failures': list(report.get('failures') or []),
    }


def _dependencies(capability: 'ConversionCapability') -> list[str]:
    source, target, category = capability.source, capability.target, capability.category
    if capability.level.value == 'vendor':
        return ['external-professional-tool']
    if category in {'音频', '视频'}:
        return ['ffmpeg', 'ffprobe']
    if category == '图片':
        return ['pillow']
    if category == '矢量图文档':
        return ['cairosvg', 'pillow' if target == 'jpg' else 'python']
    if category == '电子书':
        return ['ebooklib']
    if category == '压缩包':
        values = ['python-archive']
        if source in {'7z', 'rar'}:
            values.append('libarchive')
        if source == 'rar':
            values.append('rarfile')
        return values
    if category == 'Office 基础':
        if source == 'docx' and target in {'txt', 'html', 'md', 'rtf'}:
            return ['python-docx']
        return ['libreoffice']
    if category == '数据表格':
        values = ['python']
        if 'xlsx' in {source, target}:
            values.append('openpyxl')
        if 'yaml' in {source, target}:
            values.append('pyyaml')
        return values
    if category == '轻文档':
        values = ['python']
        if 'docx' in {source, target}:
            values.append('python-docx')
        if target == 'pdf':
            values.append('reportlab')
        return values
    return ['python']


def capability_contract(capability: 'ConversionCapability') -> dict[str, Any]:
    category, source, target = capability.category, capability.source, capability.target
    output_shape = 'directory' if target == 'folder' else 'directory-or-files' if source in {'gif', 'tiff'} and target == 'png' else 'single-file'
    preserves: list[str]
    losses: list[str]
    validator: str
    if category == '数据表格':
        preserves = ['unicode', 'cell-values', 'row-order']
        losses = ['styles-and-formulas-may-flatten'] if target not in {'xlsx'} else []
        validator = 'target-parser-and-cell-readback'
    elif category in {'图片', '矢量图文档'}:
        preserves = ['dimensions', 'decodable-pixels']
        losses = ['metadata-or-alpha-when-target-unsupported']
        validator = 'pillow-full-decode'
    elif category in {'音频', '视频'}:
        preserves = ['decodable-streams', 'duration', 'signal']
        losses = ['codec-generation-loss', 'unsupported-container-metadata']
        validator = 'ffprobe-and-ffmpeg-full-decode'
    elif category == '字幕':
        preserves = ['cue-text', 'timeline', 'unicode']
        losses = ['advanced-styling']
        validator = 'subtitle-parser-and-timeline-readback'
    elif category == '压缩包':
        preserves = ['member-paths', 'member-bytes']
        losses = ['container-specific-attributes']
        validator = 'archive-open-crc-and-member-hash'
    elif category in {'轻文档', 'Office 基础', '电子书'}:
        preserves = ['unicode', 'visible-text']
        losses = ['complex-layout', 'unsupported-comments-or-animation']
        validator = 'independent-document-parser-and-semantic-recall'
    else:
        preserves = ['readable-output']
        losses = ['format-specific-features']
        validator = 'target-parser'
    constraints = ['valid-declared-source-format', 'configured-resource-budgets']
    if source in {'zip', 'tar', 'tar.gz', '7z', 'rar', 'gz', 'bz2'}:
        constraints.append('safe-member-paths-and-expansion-limits')
    return {
        'dependencies': _dependencies(capability),
        'inputConstraints': constraints,
        'outputShape': output_shape,
        'preserves': preserves,
        'allowedLosses': losses,
        'validator': validator,
        'releaseGate': capability.key in release_route_keys(),
    }
