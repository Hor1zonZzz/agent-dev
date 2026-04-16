"""Candidate pool for Anna's soul edits.

The reflector agent doesn't modify ``soul.md`` directly — it proposes
edits here. Each proposal is keyed by ``(op, section, trait)``. Repeat
proposals increment ``count`` and append evidence. When ``count`` reaches
the op's threshold, the edit is applied to ``soul.md`` and the candidate
is archived under ``graduated/``.

Design choices:
- Two ops only: ``add`` and ``remove``. "Revising" a trait is modeled as
  ``remove old`` + ``add new`` — two independent votes, cleaner tallying.
- Both thresholds default to 3. ``remove`` is not lower than ``add``:
  removing a real trait is the worse failure mode, so it deserves at
  least as much evidence.
- Candidates that go ``EXPIRE_DAYS`` without reinforcement are moved to
  ``expired/`` — keeps the pool from accreting stale proposals forever.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from hermes import soul_editor

POOL_DIR = Path(__file__).resolve().parent.parent / "history" / "soul_candidates"
PENDING_PATH = POOL_DIR / "pending.json"
GRADUATED_DIR = POOL_DIR / "graduated"
EXPIRED_DIR = POOL_DIR / "expired"

ADD_THRESHOLD = 3
REMOVE_THRESHOLD = 3
EXPIRE_DAYS = 30

Op = Literal["add", "remove"]


@dataclass
class Evidence:
    date: str   # ISO YYYY-MM-DD, the day the proposal was made
    text: str


@dataclass
class Candidate:
    id: str
    op: Op
    section: str     # one of soul_editor.MutableSection values
    trait: str
    count: int
    first_seen: str  # ISO timestamp
    last_seen: str   # ISO timestamp
    evidences: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        data = dict(d)
        ev = data.pop("evidences", []) or []
        evidences = [Evidence(**e) for e in ev]
        return cls(evidences=evidences, **data)


@dataclass
class ProposeResult:
    candidate: Candidate
    graduated: bool   # True iff this proposal caused it to land in soul.md
    was_new: bool     # True iff this is the first time the key appears
    threshold: int
    file_changed: bool   # True iff soul.md was actually modified on graduation


def _candidate_id(op: Op, section: str, trait: str) -> str:
    key = f"{op}|{section}|{trait.strip()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _threshold(op: Op) -> int:
    return ADD_THRESHOLD if op == "add" else REMOVE_THRESHOLD


def _load_pending() -> list[Candidate]:
    if not PENDING_PATH.exists():
        return []
    raw = PENDING_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    data = json.loads(raw)
    return [Candidate.from_dict(d) for d in data]


def _save_pending(candidates: list[Candidate]) -> None:
    POOL_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        [c.to_dict() for c in candidates],
        ensure_ascii=False,
        indent=2,
    )
    fd, tmp = tempfile.mkstemp(dir=POOL_DIR, prefix=".tmp-pending-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, PENDING_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _archive(candidate: Candidate, folder: Path, *, today: str | None = None) -> Path:
    """Append the candidate's dict form to ``folder/<today>.json`` (a JSON
    array). Creates the file if absent. Not atomic, but the archive isn't
    read concurrently by anything performance-sensitive."""
    folder.mkdir(parents=True, exist_ok=True)
    today = today or date.today().isoformat()
    path = folder / f"{today}.json"
    existing: list[dict] = []
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            existing = json.loads(raw)
    existing.append(candidate.to_dict())
    path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# ── Public API ────────────────────────────────────────────────────────


def load_pending() -> list[Candidate]:
    """Read the current pool — used by the reflector to show Anna what she's
    already proposed so she can reinforce instead of duplicate-voting."""
    return _load_pending()


def propose(
    op: Op,
    section: str,
    trait: str,
    evidence: str,
    *,
    now: datetime | None = None,
) -> ProposeResult:
    """Record one proposal. If the threshold is met, apply to soul.md and
    archive the candidate to ``graduated/``."""
    if op not in ("add", "remove"):
        raise ValueError(f"op must be 'add' or 'remove', got {op!r}")
    # Will raise SoulEditError if the section is frozen or unknown.
    soul_editor._validate_section(section)

    trait = trait.strip()
    if not trait:
        raise ValueError("trait must not be empty")
    evidence = evidence.strip()
    if not evidence:
        raise ValueError("evidence must not be empty")

    now = now or datetime.now()
    now_iso = now.isoformat(timespec="seconds")
    today_iso = now.date().isoformat()

    cid = _candidate_id(op, section, trait)
    candidates = _load_pending()
    existing = next((c for c in candidates if c.id == cid), None)
    was_new = existing is None

    if existing is None:
        candidate = Candidate(
            id=cid,
            op=op,
            section=section,
            trait=trait,
            count=1,
            first_seen=now_iso,
            last_seen=now_iso,
            evidences=[Evidence(date=today_iso, text=evidence)],
        )
        candidates.append(candidate)
    else:
        existing.count += 1
        existing.last_seen = now_iso
        existing.evidences.append(Evidence(date=today_iso, text=evidence))
        candidate = existing

    threshold = _threshold(op)
    graduated = candidate.count >= threshold
    file_changed = False

    if graduated:
        if op == "add":
            file_changed = soul_editor.add_trait(section, trait)
        else:
            file_changed = soul_editor.remove_trait(section, trait)
        candidates = [c for c in candidates if c.id != cid]
        _archive(candidate, GRADUATED_DIR, today=today_iso)

    _save_pending(candidates)
    return ProposeResult(
        candidate=candidate,
        graduated=graduated,
        was_new=was_new,
        threshold=threshold,
        file_changed=file_changed,
    )


def expire_stale(*, now: datetime | None = None) -> list[Candidate]:
    """Move candidates whose ``last_seen`` is older than ``EXPIRE_DAYS`` to
    ``expired/``. Returns the list removed."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=EXPIRE_DAYS)
    candidates = _load_pending()
    kept: list[Candidate] = []
    expired: list[Candidate] = []
    for c in candidates:
        try:
            last = datetime.fromisoformat(c.last_seen)
        except ValueError:
            kept.append(c)
            continue
        if last < cutoff:
            expired.append(c)
        else:
            kept.append(c)
    if expired:
        today_iso = now.date().isoformat()
        for c in expired:
            _archive(c, EXPIRED_DIR, today=today_iso)
        _save_pending(kept)
    return expired


def summarize_pending() -> str:
    """Render the pool as a short markdown block for the reflector's trigger
    message. Empty pool returns the empty string."""
    candidates = _load_pending()
    if not candidates:
        return ""
    lines = ["## 待毕业候选（已提过但还没定性）"]
    for c in candidates:
        lines.append(
            f"- [{c.op}→{c.section}] {c.trait}  ({c.count}/{_threshold(c.op)})"
        )
    return "\n".join(lines)
