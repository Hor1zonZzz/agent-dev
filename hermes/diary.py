"""Atomic append to Anna's daily diary file.

Writing is atomic (tmp file + os.replace) so Anna side can read mid-write
without seeing partial content.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

# Single source of truth: defined in ``core/diary.py`` (Anna reads),
# re-exported here for ``hermes/`` writers. Keeps the path in one place.
from core.diary import DIARY_DIR


def append_entry(title: str, content: str) -> Path:
    """Append a diary entry to today's file with timestamped header."""
    DIARY_DIR.mkdir(parents=True, exist_ok=True)
    path = DIARY_DIR / f"{datetime.now().date().isoformat()}.md"

    now = datetime.now().strftime("%H:%M")
    entry = f"## {now}  {title}\n{content.strip()}\n\n"

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    new_content = existing + entry

    fd, tmp_path = tempfile.mkstemp(dir=DIARY_DIR, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return path
