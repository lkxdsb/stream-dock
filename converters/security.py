from __future__ import annotations

import re
import zipfile
from pathlib import Path


XML_DECLARATION_LIMIT = 2 * 1024 * 1024
OOXML_FORMATS = {'docx', 'pptx', 'xlsx', 'odt', 'ods', 'odp', 'epub'}
_DANGEROUS_XML = re.compile(br'<!ENTITY\s|<!DOCTYPE[^>]+(?:SYSTEM|PUBLIC)', re.I | re.S)
_SCRIPT = re.compile(br'<\s*script\b|\son[a-z]+\s*=', re.I)
_EXTERNAL_REFERENCE = re.compile(br'(?:href|src|xlink:href)\s*=\s*["\']\s*(?:https?:|file:|ftp:|javascript:)', re.I)


def _read_prefix(path: Path) -> bytes:
    with path.open('rb') as handle:
        return handle.read(XML_DECLARATION_LIMIT)


def _reject_dangerous_xml(content: bytes, label: str) -> None:
    if _DANGEROUS_XML.search(content):
        raise RuntimeError(f'{label} 包含 XML 外部实体或外部 DOCTYPE，已隔离拒绝')


def _scan_zip_xml(path: Path, source: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            lowered = [name.lower() for name in names]
            if any(name.endswith('vbaproject.bin') or '/macros/' in name for name in lowered):
                raise RuntimeError(f'{source.upper()} 包含宏代码，已隔离拒绝')
            if any('/externallinks/' in name for name in lowered):
                raise RuntimeError(f'{source.upper()} 包含外部工作簿链接，已隔离拒绝')
            for name in names:
                lower = name.lower()
                if not lower.endswith(('.xml', '.rels', '.xhtml', '.html', '.svg')):
                    continue
                content = archive.read(name)[:XML_DECLARATION_LIMIT]
                _reject_dangerous_xml(content, f'{source.upper()} 内部文档 {name}')
                if lower.endswith('.rels') and re.search(br'TargetMode\s*=\s*["\']External["\']', content, re.I):
                    raise RuntimeError(f'{source.upper()} 包含外部链接关系，已隔离拒绝：{name}')
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f'{source.upper()} 文件结构损坏，无法安全读取') from exc


def validate_conversion_input_security(source: str, path: Path) -> None:
    """Reject active/external content before any conversion engine opens it."""
    source = source.lower()
    if source in {'xml', 'svg'}:
        content = _read_prefix(path)
        _reject_dangerous_xml(content, source.upper())
        if source == 'svg':
            if _SCRIPT.search(content):
                raise RuntimeError('SVG 包含脚本或事件处理器，已隔离拒绝')
            if _EXTERNAL_REFERENCE.search(content):
                raise RuntimeError('SVG 包含外部资源引用，已隔离拒绝')
    elif source in OOXML_FORMATS:
        _scan_zip_xml(path, source)
