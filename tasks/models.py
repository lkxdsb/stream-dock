from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from error_catalog import classify_error

SENSITIVE_PAYLOAD_KEYS = {'cookie', 'token', 'secret', 'password', 'credential'}


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(marker in normalized_key for marker in SENSITIVE_PAYLOAD_KEYS):
                redacted[key] = '[REDACTED]' if item else item
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


class TaskKind(str, Enum):
    CONVERT = 'convert'
    MEDIA = 'media'
    PDF = 'pdf'


class TaskStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    SKIPPED = 'skipped'
    CANCELLED = 'cancelled'


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskItem:
    id: str
    kind: TaskKind
    title: str
    payload: dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    stage: str = '等待中'
    progress: float | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            'id': self.id,
            'kind': self.kind.value,
            'title': self.title,
            'payload': redact_payload(self.payload),
            'status': self.status.value,
            'logs': list(self.logs),
            'result': dict(self.result) if self.result is not None else None,
            'error': self.error,
            'stage': self.stage,
            'progress': self.progress,
            'createdAt': self.created_at,
            'updatedAt': self.updated_at,
        }
        if self.error:
            payload['errorInfo'] = classify_error(self.error)
        return payload
