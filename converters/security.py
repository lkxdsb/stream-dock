from __future__ import annotations

import re
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree


XML_DECLARATION_LIMIT = 2 * 1024 * 1024
OOXML_FORMATS = {'docx', 'pptx', 'xlsx', 'odt', 'ods', 'odp', 'epub'}
_DANGEROUS_XML = re.compile(br'<!ENTITY\s|<!DOCTYPE[^>]+(?:SYSTEM|PUBLIC)', re.I | re.S)
_SCRIPT = re.compile(br'<\s*script\b|\son[a-z]+\s*=', re.I)
_EXTERNAL_REFERENCE = re.compile(br'(?:href|src|xlink:href)\s*=\s*["\']\s*(?:https?:|file:|ftp:|javascript:)', re.I)
_CSS_EXTERNAL_REFERENCE = re.compile(r'url\(\s*["\']?\s*(?:https?:|file:|ftp:|javascript:|//)', re.I)


def _read_prefix(path: Path) -> bytes:
    with path.open('rb') as handle:
        return handle.read(XML_DECLARATION_LIMIT)


def _reject_dangerous_xml(content: bytes, label: str) -> None:
    if _DANGEROUS_XML.search(content):
        raise RuntimeError(f'{label} 包含 XML 外部实体或外部 DOCTYPE，已隔离拒绝')


def _read_zip_member_prefix(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    with archive.open(info, 'r') as member:
        return member.read(XML_DECLARATION_LIMIT)


def _reject_svg_external_references(content: bytes) -> None:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise RuntimeError('SVG XML 结构损坏，已隔离拒绝') from exc
    for element in root.iter():
        for raw_name, raw_value in element.attrib.items():
            name = raw_name.rsplit('}', 1)[-1].lower()
            value = str(raw_value or '').strip()
            lowered = value.lower()
            if name in {'href', 'src'}:
                parsed = urlsplit(value)
                if parsed.scheme.lower() in {'http', 'https', 'file', 'ftp', 'javascript'} or value.startswith('//'):
                    raise RuntimeError('SVG 包含外部资源引用，已隔离拒绝')
            if name == 'style' and _CSS_EXTERNAL_REFERENCE.search(lowered):
                raise RuntimeError('SVG 包含外部资源引用，已隔离拒绝')
        if element.tag.rsplit('}', 1)[-1].lower() == 'style' and _CSS_EXTERNAL_REFERENCE.search(element.text or ''):
            raise RuntimeError('SVG 包含外部资源引用，已隔离拒绝')


def _scan_zip_xml(path: Path, source: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            lowered = [name.lower() for name in names]
            if any(name.endswith('vbaproject.bin') or '/macros/' in name for name in lowered):
                raise RuntimeError(f'{source.upper()} 包含宏代码，已隔离拒绝')
            if any('/externallinks/' in name for name in lowered):
                raise RuntimeError(f'{source.upper()} 包含外部工作簿链接，已隔离拒绝')
            for info in archive.infolist():
                name = info.filename
                lower = name.lower()
                if not lower.endswith(('.xml', '.rels', '.xhtml', '.html', '.svg')):
                    continue
                content = _read_zip_member_prefix(archive, info)
                _reject_dangerous_xml(content, f'{source.upper()} 内部文档 {name}')
                if lower.endswith('.rels'):
                    if info.file_size > XML_DECLARATION_LIMIT:
                        raise RuntimeError(f'{source.upper()} 外部关系文件过大，无法执行有界安全扫描：{name}')
                    if re.search(br'TargetMode\s*=\s*["\']External["\']', content, re.I):
                        raise RuntimeError(f'{source.upper()} 包含外部链接关系，已隔离拒绝：{name}')
                if lower.endswith('.svg'):
                    if info.file_size > XML_DECLARATION_LIMIT:
                        raise RuntimeError(f'{source.upper()} 内嵌 SVG 过大，无法执行有界安全扫描：{name}')
                    if _SCRIPT.search(content):
                        raise RuntimeError(f'{source.upper()} 内嵌 SVG 包含脚本或事件处理器，已隔离拒绝：{name}')
                    _reject_svg_external_references(content)
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f'{source.upper()} 文件结构损坏，无法安全读取') from exc


def validate_conversion_input_security(source: str, path: Path) -> None:
    """Reject active/external content before any conversion engine opens it."""
    source = source.lower()
    if source in {'xml', 'svg'}:
        if source == 'svg' and path.stat().st_size > XML_DECLARATION_LIMIT:
            raise RuntimeError(f'{source.upper()} 文件过大，无法执行有界安全扫描')
        content = _read_prefix(path)
        _reject_dangerous_xml(content, source.upper())
        if source == 'svg':
            if _SCRIPT.search(content):
                raise RuntimeError('SVG 包含脚本或事件处理器，已隔离拒绝')
            if _EXTERNAL_REFERENCE.search(content):
                raise RuntimeError('SVG 包含外部资源引用，已隔离拒绝')
            _reject_svg_external_references(content)
    elif source in OOXML_FORMATS:
        _scan_zip_xml(path, source)
