"""Stable media-probe failures; internal causes stay out of public responses."""

from __future__ import annotations


class MediaProbeError(RuntimeError):
    def __init__(self, code: str, stage: str, message: str, *, retryable: bool = False,
                 platform: str | None = None, causes: list[str] | None = None,
                 retry_after: int | None = None, action: str | None = None):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable
        self.platform = platform
        self.causes = causes or []
        self.retry_after = retry_after
        self.action = action
