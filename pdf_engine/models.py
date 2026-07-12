from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PdfParseMode(str, Enum):
    AUTO = 'auto'
    FAST = 'fast'
    OCR = 'ocr'
    PRECISE = 'precise'


@dataclass(frozen=True)
class PdfAnalysis:
    filename: str
    size_bytes: int
    page_count: int | None
    has_native_text: bool | None
    recommended_mode: PdfParseMode
    reason: str


@dataclass(frozen=True)
class PdfParseResult:
    provider: str
    mode: PdfParseMode
    output_dir: str
    files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

