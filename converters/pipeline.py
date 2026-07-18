from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .adapters.archive import convert_archive
from .adapters.data import convert_data
from .adapters.document_basic import convert_document_basic
from .adapters.image import convert_image
from .adapters.media import convert_media
from .adapters.subtitle import convert_subtitle
from .models import ConversionLevel, ConversionResult
from .registry import find_capability, normalize_format
from runtime_checks import cleanup_partial, commit_partial, partial_output_path, prepare_output_directory, validate_general_output

DATA_FORMATS = {'csv', 'tsv', 'xlsx', 'json', 'ndjson', 'yaml', 'xml', 'toml', 'txt'}
IMAGE_FORMATS = {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tiff', 'gif', 'ico', 'ppm', 'pgm', 'pbm', 'pnm'}
MEDIA_FORMATS = {'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', 'opus', 'aiff', 'wma', 'amr', 'mp4', 'mov', 'mkv', 'webm', 'avi', 'flv', 'm4v', '3gp', 'ts'}
SUBTITLE_FORMATS = {'srt', 'vtt', 'ass', 'lrc'}
ARCHIVE_FORMATS = {'zip', 'tar', 'tar.gz', 'gz', 'bz2', 'folder'}
DOCUMENT_FORMATS = {
    'md', 'markdown', 'html', 'txt', 'rtf',
    'doc', 'docx', 'odt',
    'ppt', 'pptx', 'odp',
    'xls', 'xlsx', 'ods',
    'svg', 'epub', 'pdf', 'png', 'jpg',
}


def build_output_path(input_name: str, output_dir: Path, target: str, naming_strategy: str = 'append') -> Path:
    stem = Path(input_name).name
    if stem.endswith('.tar.gz'):
        stem = stem[:-7]
    else:
        stem = Path(stem).stem
    suffix = '' if target == 'folder' else f'.{target}'
    if naming_strategy in {'keep', 'overwrite', 'skip'}:
        filename = f'{stem}{suffix}'
    elif naming_strategy == 'timestamp':
        from datetime import datetime
        filename = f'{stem}_{datetime.now().strftime("%Y%m%d_%H%M%S")}{suffix}'
    else:
        filename = f'{stem}_converted{suffix}'
    candidate = output_dir / filename
    if candidate.exists() and naming_strategy == 'skip':
        raise FileExistsError(f'输出文件已存在，已按设置跳过：{candidate.name}')
    if naming_strategy == 'overwrite':
        return candidate
    if not candidate.exists():
        return candidate
    index = 2
    collision_stem = filename[:-len(suffix)] if suffix and filename.endswith(suffix) else filename
    while True:
        candidate = output_dir / f'{collision_stem}_{index}{suffix}'
        if not candidate.exists():
            return candidate
        index += 1


def convert_file(input_path: Path, input_name: str, source: str, target: str, output_dir: Path, *, naming_strategy: str = 'append') -> ConversionResult:
    source = normalize_format(source)
    target = normalize_format(target)
    capability = find_capability(source, target)
    if capability is None:
        return ConversionResult(False, error=f'暂不支持 {source.upper()} → {target.upper()} 转换路径')
    if capability.level == ConversionLevel.VENDOR:
        return ConversionResult(False, error='该转换属于推荐厂商能力，不执行本地转换', vendor_recommendations=list(capability.vendors))

    logs = [f'转换路径：{source.upper()} → {target.upper()}', f'能力等级：{capability.level.value}']
    partial_path: Path | None = None

    try:
        prepare_output_directory(output_dir)
        output_path = build_output_path(input_name, output_dir, target, naming_strategy=naming_strategy)
        if source == 'gif' and target == 'png':
            # GIF → PNG 会导出多帧，因此输出是一个帧目录而不是单个 PNG 文件。
            # 复用 folder 命名逻辑，避免生成看似单文件的 “*.png” 目录。
            output_path = build_output_path(input_name, output_dir, 'folder', naming_strategy=naming_strategy)
        partial_path = partial_output_path(output_path)
        cleanup_partial(partial_path)
        if source in {'csv', 'tsv', 'json', 'ndjson', 'yaml', 'xml', 'toml'} or (source == 'xlsx' and target in {'csv', 'json', 'tsv'}) or (source == 'txt' and target in {'csv', 'xlsx'}):
            logs += convert_data(source, target, input_path, partial_path)
        elif source in IMAGE_FORMATS and target in IMAGE_FORMATS:
            logs += convert_image(source, target, input_path, partial_path)
        elif source in MEDIA_FORMATS and target in MEDIA_FORMATS | {'gif'}:
            logs += convert_media(source, target, input_path, partial_path)
        elif source in SUBTITLE_FORMATS or (source == 'txt' and target == 'srt'):
            logs += convert_subtitle(source, target, input_path, partial_path)
        elif source in ARCHIVE_FORMATS or target in ARCHIVE_FORMATS:
            logs += convert_archive(source, target, input_path, partial_path)
        else:
            logs += convert_document_basic(source, target, input_path, partial_path)
        validation_target = 'folder' if source == 'gif' and target == 'png' else target
        validation = validate_general_output(partial_path, target=validation_target)
        commit_partial(partial_path, output_path)
    except Exception as exc:
        if partial_path is not None:
            cleanup_partial(partial_path)
        return ConversionResult(False, output_path=None, logs=logs, error=str(exc))

    return ConversionResult(
        True,
        output_path=output_path,
        logs=logs + [f'输出校验通过：{validation.get("sizeLabel", "-")}', f'输出文件：{output_path}'],
        validation=validation,
    )


def convert_upload_bytes(data: bytes, filename: str, source: str, target: str, output_dir: Path) -> ConversionResult:
    with tempfile.TemporaryDirectory(prefix='streamdock_convert_') as tmp_dir:
        tmp_path = Path(tmp_dir) / Path(filename).name
        tmp_path.write_bytes(data)
        return convert_file(tmp_path, filename, source, target, output_dir)
