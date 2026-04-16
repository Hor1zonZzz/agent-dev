"""Sidecar metadata helpers for conversation histories."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from loguru import logger


def meta_path(history_path: Path) -> Path:
    return history_path.with_suffix(".meta.json")


def load_meta(history_path: Path) -> dict:
    path = meta_path(history_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read meta at {}, ignoring", path)
        return {}


def save_meta(history_path: Path, meta: dict) -> None:
    path = meta_path(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_iso(history_path: Path, key: str) -> datetime | None:
    value = load_meta(history_path).get(key)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _set_iso(history_path: Path, key: str, when: datetime | None = None) -> None:
    meta = load_meta(history_path)
    meta[key] = (when or datetime.now()).isoformat()
    save_meta(history_path, meta)


def get_last_activity(history_path: Path) -> datetime | None:
    return _get_iso(history_path, "last_activity_at")


def update_last_activity(history_path: Path, when: datetime | None = None) -> None:
    _set_iso(history_path, "last_activity_at", when)


def get_last_anna_message(history_path: Path) -> datetime | None:
    return _get_iso(history_path, "last_anna_message_at")


def update_last_anna_message(history_path: Path, when: datetime | None = None) -> None:
    _set_iso(history_path, "last_anna_message_at", when)


def get_next_proactive_at(history_path: Path) -> datetime | None:
    return _get_iso(history_path, "next_proactive_at")


def update_next_proactive_at(history_path: Path, when: datetime) -> None:
    _set_iso(history_path, "next_proactive_at", when)


def update_dispatch_info(
    history_path: Path,
    user_id: str,
    context_token: str | None,
) -> None:
    meta = load_meta(history_path)
    meta["user_id"] = user_id
    if context_token is not None:
        meta["context_token"] = context_token
    save_meta(history_path, meta)


def get_dispatch_info(history_path: Path) -> tuple[str | None, str | None]:
    meta = load_meta(history_path)
    return meta.get("user_id"), meta.get("context_token")
