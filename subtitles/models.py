from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SubtitleCue:
    id: str
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SubtitleDocument:
    filename: str
    format: str
    cues: list[SubtitleCue]

    @property
    def duration(self) -> float:
        return max((cue.end for cue in self.cues), default=0.0)

    def to_dict(self) -> dict[str, object]:
        return {
            'filename': self.filename,
            'format': self.format,
            'duration': self.duration,
            'cueCount': len(self.cues),
            'cues': [cue.to_dict() for cue in self.cues],
        }
