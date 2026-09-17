"""Bounded file retention helpers for high-volume operational logs."""

import os
from pathlib import Path


def rotate_file(path: Path, max_bytes: int, backup_count: int) -> None:
    if not path.exists() or path.stat().st_size < max_bytes:
        return
    for index in range(backup_count - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        target = path.with_name(f"{path.name}.{index + 1}")
        if source.exists():
            if target.exists():
                target.unlink()
            source.replace(target)
    first_backup = path.with_name(f"{path.name}.1")
    if first_backup.exists():
        first_backup.unlink()
    path.replace(first_backup)


def append_line(path: Path, line: str, max_bytes: int, backup_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate_file(path, max_bytes, backup_count)
    with path.open("a", encoding="utf-8") as output:
        output.write(line)


def file_metrics(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"bytes": 0}
    return {"bytes": os.path.getsize(path)}
