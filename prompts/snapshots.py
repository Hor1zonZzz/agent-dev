"""Snapshot prompt files before self-edits for audit / rollback.

Any tool that mutates a file under ``prompts/`` calls :func:`snapshot` first.
The snapshot goes to ``history/prompts_snapshots/<YYYYMMDD_HHMMSS>/<file.md>``
so each reflection run's "before" state is recoverable.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

SNAPSHOT_ROOT = (
    Path(__file__).resolve().parent.parent / "history" / "prompts_snapshots"
)


def snapshot(*files: Path) -> Path:
    """Copy each existing file into a fresh timestamped directory. Returns the
    directory path. Missing files are silently skipped so callers don't need
    to pre-check existence."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = SNAPSHOT_ROOT / ts
    target.mkdir(parents=True, exist_ok=True)
    for src in files:
        if src.exists():
            shutil.copy2(src, target / src.name)
    return target
