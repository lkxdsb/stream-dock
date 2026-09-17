from __future__ import annotations

import multiprocessing as mp
import os
from pathlib import Path
from queue import Empty

from .engine_limits import conversion_engine_slot
from .models import ConversionResult
from .pipeline import convert_file


def _apply_resource_limits(timeout_seconds: int) -> None:
    """Apply hard Unix child-process limits before invoking conversion engines."""
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows fallback
        return
    limits = (
        (getattr(resource, 'RLIMIT_CPU', None), max(5, int(os.getenv('STREAMDOCK_CONVERT_CPU_LIMIT_SECONDS', str(timeout_seconds))))),
        (getattr(resource, 'RLIMIT_AS', None), max(256, int(os.getenv('STREAMDOCK_CONVERT_MEMORY_LIMIT_MB', '4096'))) * 1024 * 1024),
        (getattr(resource, 'RLIMIT_FSIZE', None), max(16, int(os.getenv('STREAMDOCK_CONVERT_OUTPUT_LIMIT_MB', '2048'))) * 1024 * 1024),
    )
    for resource_key, value in limits:
        if resource_key is None:
            continue
        try:
            current_soft, current_hard = resource.getrlimit(resource_key)
            hard = value if current_hard < 0 else min(value, current_hard)
            resource.setrlimit(resource_key, (min(value, hard), hard))
        except (OSError, ValueError):
            continue


def _convert_worker(queue, args: tuple[str, str, str, str, str, str, int | None, dict | None, dict | None, int]) -> None:
    input_path, input_name, source, target, output_dir, naming_strategy, image_quality, media_options, archive_options, timeout_seconds = args
    try:
        _apply_resource_limits(timeout_seconds)
        result = convert_file(
            Path(input_path),
            input_name,
            source,
            target,
            Path(output_dir),
            naming_strategy=naming_strategy,
            image_quality=image_quality,
            media_options=media_options,
            archive_options=archive_options,
        )
        queue.put(result.to_dict())
    except BaseException as exc:  # pragma: no cover - process boundary guard
        queue.put({'success': False, 'outputPath': None, 'logs': [], 'error': str(exc), 'vendorRecommendations': []})


def convert_file_with_timeout(
    input_path: Path,
    input_name: str,
    source: str,
    target: str,
    output_dir: Path,
    *,
    timeout_seconds: int,
    naming_strategy: str = 'append',
    image_quality: int | None = None,
    media_options: dict | None = None,
    archive_options: dict | None = None,
) -> ConversionResult:
    method = 'fork' if 'fork' in mp.get_all_start_methods() else 'spawn'
    context = mp.get_context(method)
    queue = context.Queue(maxsize=1)
    try:
        with conversion_engine_slot(source, target) as (engine, limit):
            process = context.Process(
                target=_convert_worker,
                args=(queue, (str(input_path), input_name, source, target, str(output_dir), naming_strategy, image_quality, media_options, archive_options, timeout_seconds)),
                daemon=True,
            )
            process.start()
            process.join(timeout_seconds)
            if process.is_alive():
                process.terminate()
                process.join(3)
                return ConversionResult(False, error=f'转换超时（{timeout_seconds} 秒），已终止任务')
            try:
                data = queue.get_nowait()
            except Empty:
                if process.exitcode and process.exitcode < 0:
                    return ConversionResult(False, error=f'{engine} 转换子进程被系统终止，可能超出 CPU、内存或输出大小配额')
                return ConversionResult(False, error='转换子进程未返回结果')
            data.setdefault('logs', [])
            data['logs'] = [f'引擎并发槽：{engine} {limit}', *list(data['logs'])]
    except RuntimeError as exc:
        return ConversionResult(False, error=str(exc))
    return ConversionResult(
        bool(data.get('success')),
        output_path=Path(data['outputPath']) if data.get('outputPath') else None,
        logs=list(data.get('logs') or []),
        error=data.get('error'),
        vendor_recommendations=list(data.get('vendorRecommendations') or []),
        validation=dict(data.get('validation') or {}) or None,
    )
