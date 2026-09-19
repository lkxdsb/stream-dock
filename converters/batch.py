from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Sequence

from .models import ConversionCapability, ConversionResult
from .pipeline import convert_file
from .registry import find_capability, infer_input_format, normalize_format


MAX_SPLIT_RAR_PARTS = 1000


@dataclass(frozen=True)
class BatchInput:
    filename: str
    source: str
    input_path: Path | None = None

    def to_dict(self) -> dict[str, str]:
        return {'filename': self.filename, 'source': self.source}


@dataclass(frozen=True)
class BatchRouteValidation:
    success: bool
    source: str | None = None
    target: str | None = None
    capability: ConversionCapability | None = None
    files: tuple[BatchInput, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            'success': self.success,
            'source': self.source,
            'target': self.target,
            'capability': self.capability.to_dict() if self.capability else None,
            'files': [item.to_dict() for item in self.files],
            'error': self.error,
        }


@dataclass(frozen=True)
class BatchConversionRow:
    filename: str
    source: str
    target: str
    success: bool
    output_path: str | None
    logs: list[str]
    error: str | None
    validation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            'filename': self.filename,
            'source': self.source,
            'target': self.target,
            'success': self.success,
            'outputPath': self.output_path,
            'logs': self.logs,
            'error': self.error,
            'validation': dict(self.validation) if self.validation else None,
        }


def make_batch_inputs(filenames: Sequence[str], input_type: str | None = None) -> tuple[BatchInput, ...]:
    items: list[BatchInput] = []
    override = normalize_format(input_type) if input_type else None
    for filename in filenames:
        clean_name = Path(filename or 'input').name or 'input'
        source = override or infer_input_format(clean_name)
        items.append(BatchInput(filename=clean_name, source=source))
    return tuple(items)


def collapse_split_archive_inputs(inputs: Sequence[BatchInput]) -> tuple[BatchInput, ...]:
    """Collapse uploaded RAR volumes to one conversion job per complete set."""
    pattern = re.compile(r'^(?P<base>.+)\.part(?P<number>\d+)\.rar$', re.I)
    matches = [(item, pattern.match(item.filename)) for item in inputs]
    if not any(match for _, match in matches):
        return tuple(inputs)
    if any(match is None for _, match in matches):
        raise RuntimeError('分卷 RAR 请一次只上传同组 .partN.rar 文件')
    groups: dict[str, list[tuple[int, BatchInput]]] = {}
    for item, match in matches:
        assert match is not None
        number = int(match.group('number'))
        if number < 1 or number > MAX_SPLIT_RAR_PARTS:
            raise RuntimeError(f'分卷 RAR 卷号超出本次上传范围：part{number}')
        groups.setdefault(match.group('base').lower(), []).append((number, item))
    primaries: list[BatchInput] = []
    for base, parts in groups.items():
        parts.sort(key=lambda pair: pair[0])
        numbers = [number for number, _ in parts]
        if not numbers or numbers[0] != 1 or any(current != previous + 1 for previous, current in zip(numbers, numbers[1:])):
            raise RuntimeError(f'分卷 RAR {base} 不完整，缺少卷或卷号未从 1 开始连续')
        primaries.append(parts[0][1])
    return tuple(primaries)


def validate_batch_route(filenames: Sequence[str], target: str, input_type: str | None = None) -> BatchRouteValidation:
    if not filenames:
        return BatchRouteValidation(False, target=normalize_format(target), error='请先选择至少一个文件')

    files = make_batch_inputs(filenames, input_type=input_type)
    sources = {item.source for item in files}
    target = normalize_format(target)

    if len(sources) != 1:
        return BatchRouteValidation(
            success=False,
            target=target,
            files=files,
            error='批量转换第一版要求所有文件使用同一种输入格式',
        )

    source = next(iter(sources))
    capability = find_capability(source, target)
    if capability is None:
        return BatchRouteValidation(
            success=False,
            source=source,
            target=target,
            files=files,
            error=f'暂不支持 {source.upper()} → {target.upper()} 批量转换路径',
        )

    return BatchRouteValidation(True, source=source, target=target, capability=capability, files=files)


def convert_batch_files(
    inputs: Sequence[BatchInput],
    target: str,
    output_dir: Path,
    *,
    timeout_seconds: int | None = None,
    naming_strategy: str = 'append',
    image_quality: int | None = None,
    media_options: dict | None = None,
    archive_options: dict | None = None,
) -> dict[str, object]:
    target = normalize_format(target)
    rows: list[BatchConversionRow] = []
    logs = [f'批量转换任务：{len(inputs)} 个文件', f'目标格式：{target.upper()}']

    for index, item in enumerate(inputs, start=1):
        if item.input_path is None:
            result = ConversionResult(False, error='缺少临时输入文件')
        elif timeout_seconds:
            from .executor import convert_file_with_timeout
            result = convert_file_with_timeout(
                item.input_path,
                item.filename,
                item.source,
                target,
                output_dir,
                timeout_seconds=timeout_seconds,
                naming_strategy=naming_strategy,
                image_quality=image_quality,
                media_options=media_options,
                archive_options=archive_options,
            )
        else:
            result = convert_file(
                item.input_path,
                item.filename,
                item.source,
                target,
                output_dir,
                naming_strategy=naming_strategy,
                image_quality=image_quality,
                media_options=media_options,
                archive_options=archive_options,
            )
        rows.append(
            BatchConversionRow(
                filename=item.filename,
                source=item.source,
                target=target,
                success=result.success,
                output_path=str(result.output_path) if result.output_path else None,
                logs=result.logs,
                error=result.error,
                validation=result.validation,
            )
        )
        status_text = '完成' if result.success else '失败'
        logs.append(f'[{index}/{len(inputs)}] {item.filename}：{status_text}')
        if result.error:
            logs.append(f'  {result.error}')

    success_count = sum(1 for row in rows if row.success)
    return {
        'success': success_count == len(rows),
        'total': len(rows),
        'successCount': success_count,
        'failedCount': len(rows) - success_count,
        'results': [row.to_dict() for row in rows],
        'logs': logs,
    }
