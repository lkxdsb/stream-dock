from __future__ import annotations

import csv
import json
import tarfile
import zipfile
from pathlib import Path

from .registry import normalize_format


ZIP_DOCUMENT_MARKERS = {
    'docx': 'word/',
    'xlsx': 'xl/',
    'pptx': 'ppt/',
    'odt': 'content.xml',
    'ods': 'content.xml',
    'odp': 'content.xml',
    'epub': 'META-INF/container.xml',
}


def _zip_format(path: Path) -> str | None:
    if not zipfile.is_zipfile(path):
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            joined = '\n'.join(names)
            if any(name.startswith('word/') for name in names):
                return 'docx'
            if any(name.startswith('xl/') for name in names):
                return 'xlsx'
            if any(name.startswith('ppt/') for name in names):
                return 'pptx'
            if 'META-INF/container.xml' in names:
                return 'epub'
            if 'mimetype' in names:
                mimetype = archive.read('mimetype').decode('utf-8', errors='ignore')
                if 'opendocument.text' in mimetype:
                    return 'odt'
                if 'opendocument.spreadsheet' in mimetype:
                    return 'ods'
                if 'opendocument.presentation' in mimetype:
                    return 'odp'
            if joined:
                return 'zip'
    except (OSError, zipfile.BadZipFile):
        return None
    return 'zip'


def sniff_file_format(path: Path) -> str | None:
    """Best-effort content sniffing used to reject obvious extension spoofing."""
    header = path.read_bytes()[:8192]
    if not header:
        return None
    if header.startswith(b'%PDF-'):
        return 'pdf'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if header.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if header.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if header.startswith(b'BM'):
        return 'bmp'
    if header[:4] in {b'II*\x00', b'MM\x00*'}:
        return 'tiff'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return 'webp'
    if header.startswith(b'PK\x03\x04'):
        return _zip_format(path)
    if header.startswith(b'\x1f\x8b'):
        try:
            if tarfile.is_tarfile(path):
                return 'tar.gz'
        except (OSError, tarfile.TarError):
            pass
        return 'gz'
    if header.startswith(b'BZh'):
        return 'bz2'
    if header.startswith(b'Rar!'):
        return 'rar'
    if header.startswith(b'7z\xbc\xaf\x27\x1c'):
        return '7z'
    if header.startswith(b'{\\rtf'):
        return 'rtf'

    try:
        text = header.decode('utf-8-sig').strip()
    except UnicodeDecodeError:
        return None
    if not text:
        return None
    if text.startswith(('{', '[')):
        try:
            json.loads(text)
            return 'json'
        except json.JSONDecodeError:
            pass
    lowered = text.lower()
    if lowered.startswith(('<!doctype html', '<html')):
        return 'html'
    if text.startswith('<?xml') or (text.startswith('<') and text.endswith('>')):
        return 'xml'
    if '\t' in text.splitlines()[0]:
        return 'tsv'
    if ',' in text.splitlines()[0]:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=',')
            if dialect.delimiter == ',':
                return 'csv'
        except csv.Error:
            pass
    return 'txt'


def validate_declared_format(path: Path, declared: str) -> tuple[bool, str | None]:
    declared = normalize_format(declared)
    detected = sniff_file_format(path)
    if detected is None:
        return True, None

    text_family = {'txt', 'md', 'markdown', 'yaml', 'toml', 'lrc', 'srt', 'vtt', 'ass'}
    if declared in text_family and detected == 'txt':
        return True, detected
    # 单列 CSV/TSV 与纯文本在内容上无法可靠区分，保留扩展名声明。
    if declared in {'csv', 'tsv'} and detected == 'txt':
        return True, detected
    if declared in {'html', 'xml', 'svg'} and detected in {'html', 'xml'}:
        return True, detected
    if declared in {'jpg', 'jpeg'} and detected == 'jpg':
        return True, detected
    if declared == 'zip' and detected in {'zip', 'docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp', 'epub'}:
        return True, detected
    if declared == detected:
        return True, detected
    return False, detected
