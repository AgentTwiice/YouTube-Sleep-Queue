"""Crash-safe helpers for mutable local application state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(
    destination: str | os.PathLike[str],
    content: str,
    *,
    encoding: str = "utf-8",
    mode: int | None = None,
) -> None:
    """Write text through a unique same-directory file and atomically replace it."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        if mode is not None:
            os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        _sync_directory(path.parent)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def atomic_write_json(
    destination: str | os.PathLike[str],
    value: Any,
    *,
    mode: int | None = None,
) -> None:
    """Serialize JSON deterministically and write it atomically."""
    atomic_write_text(
        destination,
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        mode=mode,
    )


def preserve_corrupt_file(path: str | os.PathLike[str]) -> Path:
    """Atomically retain a malformed state file under a unique diagnostic name."""
    source = Path(path)
    for counter in range(1, 10_000):
        candidate = source.with_name(f"{source.name}.corrupt.{counter}")
        if not candidate.exists():
            os.replace(source, candidate)
            return candidate
    raise OSError(f"Could not allocate a backup name for corrupt file: {source}")


def _sync_directory(directory: Path) -> None:
    """Best-effort directory sync on platforms that support directory handles."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
