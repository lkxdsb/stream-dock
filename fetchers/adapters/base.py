from __future__ import annotations

from fetchers.models import MediaFetchResult


class BasePlatformAdapter:
    platform_name = "base"

    def can_handle(self, raw_link: str) -> bool:
        raise NotImplementedError

    def normalize_link(self, raw_link: str) -> str:
        raise NotImplementedError

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        raise NotImplementedError
