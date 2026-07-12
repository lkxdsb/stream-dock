from __future__ import annotations

from pathlib import Path
from typing import Callable
import subprocess

from pdf_engine.models import PdfAnalysis, PdfParseMode, PdfParseResult
from pdf_engine.providers.mineru import MinerUProvider


def analyze_pdf(path: Path) -> PdfAnalysis:
    if path.suffix.lower() != '.pdf' or path.read_bytes()[:5] != b'%PDF-':
        raise ValueError('请选择有效的 PDF 文件')
    page_count: int | None = None
    has_native_text: bool | None = None
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        samples = [str(page.extract_text() or '').strip() for page in reader.pages[:5]]
        has_native_text = sum(len(item) for item in samples) >= 80
    except Exception:
        pass

    mode = PdfParseMode.FAST if has_native_text else PdfParseMode.OCR if has_native_text is False else PdfParseMode.AUTO
    reason = (
        '检测到可提取文本，建议快速解析'
        if has_native_text else '未检测到足够的原生文本，建议 OCR 解析'
        if has_native_text is False else '无法完成文本覆盖检测，建议自动判断'
    )
    return PdfAnalysis(path.name, path.stat().st_size, page_count, has_native_text, mode, reason)


def parse_pdf(
    path: Path,
    output_dir: Path,
    mode: PdfParseMode,
    provider: MinerUProvider | None = None,
    process_callback: Callable[[subprocess.Popen[str]], None] | None = None,
) -> PdfParseResult:
    analyze_pdf(path)
    return (provider or MinerUProvider()).parse(path, output_dir, mode, process_callback=process_callback)
