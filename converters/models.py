from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


VERIFIED_CONVERSION_ROUTES = {
    'csv:json', 'epub:html', 'lrc:srt', 'md:docx', 'md:html', 'md:pdf',
    'png:ico', 'rtf:txt', 'txt:docx', 'gz:folder',
}


class ConversionLevel(str, Enum):
    STABLE = 'stable'
    BASIC = 'basic'
    VENDOR = 'vendor'


@dataclass(frozen=True)
class ConversionCapability:
    source: str
    target: str
    level: ConversionLevel
    category: str
    title: str
    description: str
    engine: str
    notes: str = ''
    vendors: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f'{self.source.lower()}:{self.target.lower()}'

    def to_dict(self) -> dict[str, object]:
        return {
            'source': self.source,
            'target': self.target,
            'level': self.level.value,
            'category': self.category,
            'title': self.title,
            'description': self.description,
            'engine': self.engine,
            'notes': self.notes,
            'vendors': list(self.vendors),
            'key': self.key,
            'verification': (
                'verified' if self.key in VERIFIED_CONVERSION_ROUTES
                else 'engine' if self.level == ConversionLevel.STABLE
                else 'best-effort' if self.level == ConversionLevel.BASIC
                else 'vendor'
            ),
        }


@dataclass
class ConversionResult:
    success: bool
    output_path: Path | None = None
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    vendor_recommendations: list[str] = field(default_factory=list)
    validation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            'success': self.success,
            'outputPath': str(self.output_path) if self.output_path else None,
            'logs': self.logs,
            'error': self.error,
            'vendorRecommendations': self.vendor_recommendations,
            'validation': dict(self.validation) if self.validation else None,
        }
