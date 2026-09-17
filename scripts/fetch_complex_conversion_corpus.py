#!/usr/bin/env python3
"""Download and verify the public complex-file conversion corpus.

Downloaded files are data only, are never executed, and live under the ignored
``.streamdock-complex-corpus`` directory.  The manifest pins every SHA-256 so a
changed upstream file cannot silently alter a quality run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / "scripts" / "complex_conversion_corpus_sources.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        request = Request(url, headers={"User-Agent": "StreamDock-complex-fixture-fetcher/1.0"})
        try:
            with urlopen(request, timeout=120) as response:
                shutil.copyfileobj(response, temporary, length=1024 * 1024)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
    temporary_path.replace(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / ".streamdock-complex-corpus")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    failures: list[str] = []
    for fixture in manifest["fixtures"]:
        path = args.root / fixture["relativePath"]
        if args.refresh or not path.exists():
            print(f"download {fixture['id']}: {fixture['url']}")
            fetch(fixture["url"], path)
        actual = sha256(path)
        if actual != fixture["sha256"]:
            failures.append(f"{fixture['id']}: expected {fixture['sha256']}, got {actual}")
        else:
            print(f"verified {fixture['id']}: {path} ({path.stat().st_size} bytes)")
    if failures:
        for failure in failures:
            print(f"ERROR {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
