from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pdf_engine.models import PdfParseMode, PdfParseResult


class DocumentParserProvider(Protocol):
    name: str

    def health(self) -> dict[str, object]: ...

    def parse(self, input_path: Path, output_dir: Path, mode: PdfParseMode) -> PdfParseResult: ...

