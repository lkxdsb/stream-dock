"""Explicit, offline Chinese script conversion; never alter cue timings."""
from functools import lru_cache
from threading import Lock

_lock = Lock()


@lru_cache(maxsize=1)
def _converter():
    try:
        from opencc import OpenCC
    except ImportError as exc:
        raise ValueError('简体中文转换依赖缺失，请安装 requirements.txt 中的 opencc') from exc
    return OpenCC('t2s')


def to_simplified(text: str) -> str:
    with _lock:
        return _converter().convert(text)


def normalize_chinese_asr(text: str, language: str | None) -> str:
    code = str(language or '').lower().replace('_', '-')
    return to_simplified(text) if code == 'chinese' or code.split('-')[0] == 'zh' else text
