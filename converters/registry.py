from __future__ import annotations

from pathlib import Path

from .models import ConversionCapability, ConversionLevel


def _cap(source: str, target: str, level: ConversionLevel, category: str, engine: str, description: str, notes: str = '', vendors: tuple[str, ...] = ()) -> ConversionCapability:
    return ConversionCapability(
        source=source,
        target=target,
        level=level,
        category=category,
        title=f'{source.upper()} → {target.upper()}',
        description=description,
        engine=engine,
        notes=notes,
        vendors=vendors,
    )


STABLE_DATA = [
    ('csv', 'xlsx'), ('csv', 'json'), ('csv', 'tsv'), ('csv', 'txt'),
    ('tsv', 'csv'), ('tsv', 'xlsx'), ('tsv', 'json'),
    ('xlsx', 'csv'), ('xlsx', 'json'), ('xlsx', 'tsv'),
    ('json', 'csv'), ('json', 'xlsx'), ('json', 'txt'),
    ('txt', 'csv'), ('txt', 'xlsx'),
    ('ndjson', 'json'), ('ndjson', 'csv'),
    ('yaml', 'json'), ('json', 'yaml'),
    ('xml', 'json'), ('json', 'xml'),
    ('toml', 'json'), ('json', 'toml'),
]
STABLE_IMAGE = [
    ('png', 'jpg'), ('png', 'webp'), ('png', 'bmp'), ('png', 'tiff'),
    ('png', 'ico'), ('png', 'ppm'),
    ('jpg', 'png'), ('jpg', 'webp'), ('jpg', 'bmp'), ('jpg', 'tiff'),
    ('jpg', 'ico'),
    ('jpeg', 'png'), ('jpeg', 'webp'),
    ('webp', 'png'), ('webp', 'jpg'),
    ('bmp', 'png'), ('bmp', 'jpg'),
    ('tiff', 'png'), ('tiff', 'jpg'),
    ('ico', 'png'), ('ico', 'jpg'),
    ('ppm', 'png'), ('ppm', 'jpg'),
    ('pgm', 'png'), ('pbm', 'png'), ('pnm', 'png'),
    ('gif', 'png'), ('png', 'gif'),
]
STABLE_AUDIO = [
    ('mp3', 'wav'), ('mp3', 'm4a'), ('mp3', 'aac'), ('mp3', 'flac'), ('mp3', 'ogg'), ('mp3', 'opus'),
    ('wav', 'mp3'), ('wav', 'm4a'), ('wav', 'flac'), ('wav', 'ogg'),
    ('m4a', 'mp3'), ('m4a', 'wav'), ('m4a', 'aac'),
    ('aac', 'mp3'), ('aac', 'wav'),
    ('flac', 'mp3'), ('flac', 'wav'),
    ('ogg', 'mp3'), ('opus', 'mp3'),
    ('aiff', 'mp3'), ('aiff', 'wav'),
    ('wma', 'mp3'), ('wma', 'wav'),
    ('amr', 'mp3'), ('amr', 'wav'),
]
STABLE_VIDEO = [
    ('mp4', 'mp3'), ('mp4', 'wav'), ('mp4', 'm4a'),
    ('mov', 'mp4'), ('mkv', 'mp4'), ('webm', 'mp4'),
    ('avi', 'mp4'), ('flv', 'mp4'), ('m4v', 'mp4'), ('3gp', 'mp4'), ('ts', 'mp4'),
    ('mp4', 'gif'), ('mov', 'gif'), ('webm', 'gif'),
    ('avi', 'gif'), ('flv', 'gif'),
    ('mp4', 'webm'), ('mov', 'webm'), ('mkv', 'webm'), ('webm', 'mp4'),
]
STABLE_SUBTITLE = [('srt', 'vtt'), ('vtt', 'srt'), ('ass', 'srt'), ('ass', 'vtt'), ('txt', 'srt'), ('lrc', 'srt'), ('lrc', 'vtt')]
STABLE_ARCHIVE = [
    ('zip', 'tar'), ('tar', 'zip'), ('tar.gz', 'zip'),
    ('zip', 'folder'), ('tar', 'folder'), ('tar.gz', 'folder'), ('gz', 'folder'), ('bz2', 'folder'),
    ('folder', 'zip'), ('folder', 'tar.gz'),
]
BASIC_LIGHT_DOCS = [
    ('md', 'html'), ('md', 'txt'), ('md', 'docx'), ('md', 'pdf'),
    ('markdown', 'html'), ('markdown', 'txt'), ('markdown', 'docx'), ('markdown', 'pdf'),
    ('html', 'txt'), ('html', 'md'), ('html', 'docx'), ('html', 'pdf'),
    ('txt', 'html'), ('txt', 'md'), ('txt', 'docx'), ('txt', 'rtf'), ('txt', 'pdf'),
    ('rtf', 'txt'), ('rtf', 'html'), ('rtf', 'docx'),
]
BASIC_OFFICE_DOCS = [
    ('docx', 'txt'), ('docx', 'html'), ('docx', 'md'), ('docx', 'rtf'), ('docx', 'pdf'),
    ('doc', 'docx'), ('doc', 'txt'), ('doc', 'html'),
    ('odt', 'docx'), ('odt', 'txt'), ('odt', 'html'),
    ('ppt', 'pptx'), ('odp', 'pptx'),
    ('pptx', 'pdf'), ('pptx', 'png'),
    ('xls', 'xlsx'), ('xls', 'csv'),
    ('ods', 'xlsx'), ('ods', 'csv'),
    ('xlsx', 'pdf'), ('xlsx', 'html'),
]
BASIC_EBOOK_DOCS = [
    ('epub', 'txt'), ('epub', 'html'), ('epub', 'md'), ('epub', 'pdf'),
]
BASIC_VECTOR_DOCS = [
    ('svg', 'png'), ('svg', 'jpg'), ('svg', 'pdf'),
]
VENDOR_ONLY = [
    ('pdf', 'docx'), ('pdf', 'xlsx'), ('pdf', 'pptx'),
    ('scan-pdf', 'docx'), ('scan-pdf', 'xlsx'),
    ('image-ocr', 'docx'), ('image-ocr', 'xlsx'),
    ('complex-docx', 'pdf'), ('complex-pptx', 'pdf'),
    ('cad', 'pdf'), ('cad', 'png'),
    ('psd', 'png'), ('ai', 'pdf'), ('sketch', 'figma'), ('figma', 'pdf'),
]


CAPABILITIES: tuple[ConversionCapability, ...] = tuple(
    [_cap(a, b, ConversionLevel.STABLE, '数据表格', 'python/openpyxl', '结构化数据本地转换，适合表格和配置数据。') for a, b in STABLE_DATA]
    + [_cap(a, b, ConversionLevel.STABLE, '图片', 'pillow', '常规图片格式本地转换，透明背景转 JPG 默认白底。') for a, b in STABLE_IMAGE]
    + [_cap(a, b, ConversionLevel.STABLE, '音频', 'ffmpeg', '成熟音频编码转换，使用本机 ffmpeg。') for a, b in STABLE_AUDIO]
    + [_cap(a, b, ConversionLevel.STABLE, '视频', 'ffmpeg', '常规视频封装、转码、音频提取和 GIF 导出。') for a, b in STABLE_VIDEO]
    + [_cap(a, b, ConversionLevel.STABLE, '字幕', 'local', '字幕文本格式转换，复杂样式会降级为文本。') for a, b in STABLE_SUBTITLE]
    + [_cap(a, b, ConversionLevel.STABLE, '压缩包', 'python-archive', '普通压缩包转换与解压，第一版不支持加密压缩包。') for a, b in STABLE_ARCHIVE]
    + [_cap(a, b, ConversionLevel.BASIC, '轻文档', 'python-docx/markdown/reportlab', 'Markdown、HTML、TXT、RTF 与 DOCX 的基础本地转换。', '适合普通文本型文档，复杂样式会降级。') for a, b in BASIC_LIGHT_DOCS]
    + [_cap(a, b, ConversionLevel.BASIC, 'Office 基础', 'python-docx/libreoffice', '常见 Office 与开放文档格式基础转换。', '依赖本机 LibreOffice；复杂排版、公式、批注、动画可能有损。') for a, b in BASIC_OFFICE_DOCS]
    + [_cap(a, b, ConversionLevel.BASIC, '电子书', 'ebooklib', 'EPUB 内容抽取为 HTML、TXT、Markdown 等轻文档格式。', '适合非 DRM 的普通 EPUB；复杂目录和脚注可能简化。') for a, b in BASIC_EBOOK_DOCS]
    + [_cap(a, b, ConversionLevel.BASIC, '矢量图文档', 'cairosvg', 'SVG 与常见图片/文档格式基础转换。', '复杂 SVG 滤镜效果可能与浏览器渲染不同。') for a, b in BASIC_VECTOR_DOCS]
    + [_cap(a, b, ConversionLevel.VENDOR, '专业转换建议', 'vendor-only', '该转换对高保真或 OCR 能力要求较高，建议使用专业工具完成。', vendors=('Adobe Acrobat', 'Microsoft 365', 'WPS', 'ABBYY FineReader', 'Smallpdf', 'iLovePDF', 'CloudConvert', 'Convertio')) for a, b in VENDOR_ONLY]
)

_BY_KEY = {cap.key: cap for cap in CAPABILITIES}

_EXTENSION_ALIASES = {
    'jpeg': 'jpg',
    'htm': 'html',
    'markdown': 'md',
    'yml': 'yaml',
    'tgz': 'tar.gz',
}


def normalize_format(value: str) -> str:
    value = value.strip().lower().lstrip('.')
    if value.endswith('.tar.gz'):
        return 'tar.gz'
    return _EXTENSION_ALIASES.get(value, value)


def infer_input_format(filename: str) -> str:
    lower = Path(filename).name.lower()
    if lower.endswith('.tar.gz'):
        return 'tar.gz'
    if lower.endswith('.ndjson'):
        return 'ndjson'
    return normalize_format(Path(lower).suffix)


def list_capabilities() -> list[ConversionCapability]:
    return list(CAPABILITIES)


def find_capability(source: str, target: str) -> ConversionCapability | None:
    return _BY_KEY.get(f'{normalize_format(source)}:{normalize_format(target)}')


def targets_for_source(source: str) -> list[ConversionCapability]:
    source = normalize_format(source)
    return [cap for cap in CAPABILITIES if normalize_format(cap.source) == source]
