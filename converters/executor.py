from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
from queue import Empty

from .models import ConversionResult
from .pipeline import convert_file


def _convert_worker(queue, args: tuple[str, str, str, str, str, str]) -> None:
    input_path, input_name, source, target, output_dir, naming_strategy = args
    try:
        result = convert_file(
            Path(input_path),
            input_name,
            source,
            target,
            Path(output_dir),
            naming_strategy=naming_strategy,
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
) -> ConversionResult:
    method = 'fork' if 'fork' in mp.get_all_start_methods() else 'spawn'
    context = mp.get_context(method)
    queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_convert_worker,
        args=(queue, (str(input_path), input_name, source, target, str(output_dir), naming_strategy)),
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
        return ConversionResult(False, error='转换子进程未返回结果')
    return ConversionResult(
        bool(data.get('success')),
        output_path=Path(data['outputPath']) if data.get('outputPath') else None,
        logs=list(data.get('logs') or []),
        error=data.get('error'),
        vendor_recommendations=list(data.get('vendorRecommendations') or []),
        validation=dict(data.get('validation') or {}) or None,
    )
