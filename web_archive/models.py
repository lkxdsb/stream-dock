from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


@dataclass
class WebArchiveResult:
    url: str
    title: str
    output_dir: str
    markdown_path: str
    image_count: int = 0
    extract_mode: str = 'requests'
    logs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            'url': self.url,
            'title': self.title,
            'outputDir': self.output_dir,
            'markdownPath': self.markdown_path,
            'imageCount': self.image_count,
            'extractMode': self.extract_mode,
            'logs': list(self.logs),
        }


class ExtractRequest(BaseModel):
    url: str = Field(min_length=1)
    outputPath: str = Field(min_length=1)

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise ValueError('请输入有效的网页链接（需以 http:// 或 https:// 开头）')
        return v