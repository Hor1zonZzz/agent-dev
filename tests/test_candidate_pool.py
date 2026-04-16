"""Candidate pool tests — propose / graduate / expire lifecycle.

Run:  uv run python -m pytest tests/test_candidate_pool.py -v
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hermes import candidate_pool, soul_editor


CANONICAL_SOUL = """\
## Soul

### Identity
- Name: Anna

### Ground Rule
You are not an assistant, not a customer service bot, not a search engine.

### Personality Traits
尚未形成

### Speaking Style
尚未形成

### Values & Beliefs
尚未形成

### Quirks & Habits
尚未形成
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    soul = tmp_path / "soul.md"
    soul.write_text(CANONICAL_SOUL, encoding="utf-8")
    monkeypatch.setattr(soul_editor, "SOUL_PATH", soul)

    pool_dir = tmp_path / "soul_candidates"
    monkeypatch.setattr(candidate_pool, "POOL_DIR", pool_dir)
    monkeypatch.setattr(candidate_pool, "PENDING_PATH", pool_dir / "pending.json")
    monkeypatch.setattr(candidate_pool, "GRADUATED_DIR", pool_dir / "graduated")
    monkeypatch.setattr(candidate_pool, "EXPIRED_DIR", pool_dir / "expired")

    return {"soul": soul, "pool": pool_dir}


# ---- propose: first-time, accumulation, graduation -----------------------


def test_propose_new_candidate_count_one(env):
    r = candidate_pool.propose(
        "add", "personality_traits", "说话直接", "用户说我很直接"
    )
    assert r.was_new is True
    assert r.graduated is False
    assert r.candidate.count == 1
    assert r.threshold == candidate_pool.ADD_THRESHOLD

    pending = candidate_pool.load_pending()
    assert len(pending) == 1
    assert pending[0].trait == "说话直接"
    assert len(pending[0].evidences) == 1


def test_propose_same_twice_accumulates(env):
    candidate_pool.propose("add", "personality_traits", "说话直接", "e1")
    r2 = candidate_pool.propose("add", "personality_traits", "说话直接", "e2")

    assert r2.was_new is False
    assert r2.graduated is False
    assert r2.candidate.count == 2
    assert len(r2.candidate.evidences) == 2
    # Still in pending, not yet in soul.md
    assert soul_editor.list_traits("personality_traits") == []


def test_propose_add_graduates_at_threshold(env):
    for i in range(candidate_pool.ADD_THRESHOLD - 1):
        r = candidate_pool.propose(
            "add", "personality_traits", "说话直接", f"evidence-{i}"
        )
        assert r.graduated is False

    r_final = candidate_pool.propose(
        "add", "personality_traits", "说话直接", "final"
    )
    assert r_final.graduated is True
    assert r_final.file_changed is True
    assert soul_editor.list_traits("personality_traits") == ["说话直接"]
    # Candidate drained from pending
    assert candidate_pool.load_pending() == []
    # Archived under graduated/
    graduated_dir = env["pool"] / "graduated"
    assert graduated_dir.exists()
    files = list(graduated_dir.glob("*.json"))
    assert len(files) == 1
    archived = json.loads(files[0].read_text(encoding="utf-8"))
    assert archived[0]["trait"] == "说话直接"
    assert archived[0]["count"] == candidate_pool.ADD_THRESHOLD


def test_propose_remove_graduates_at_threshold(env):
    # Seed the trait that we'll try to remove.
    soul_editor.add_trait("quirks", "爱撒娇")
    assert soul_editor.list_traits("quirks") == ["爱撒娇"]

    for _ in range(candidate_pool.REMOVE_THRESHOLD - 1):
        r = candidate_pool.propose("remove", "quirks", "爱撒娇", "反例")
        assert r.graduated is False
    # Trait still there before the last vote
    assert soul_editor.list_traits("quirks") == ["爱撒娇"]

    r_final = candidate_pool.propose("remove", "quirks", "爱撒娇", "反例-final")
    assert r_final.graduated is True
    assert r_final.file_changed is True
    assert soul_editor.list_traits("quirks") == []


def test_propose_remove_nonexistent_graduates_but_no_change(env):
    """Removing a trait that isn't in soul.md still graduates (the vote was
    valid) but file_changed reports False — the edit was a no-op."""
    for _ in range(candidate_pool.REMOVE_THRESHOLD):
        candidate_pool.propose("remove", "quirks", "不存在的", "e")
    pending = candidate_pool.load_pending()
    assert pending == []
    assert soul_editor.list_traits("quirks") == []


def test_propose_duplicate_key_after_graduation_starts_fresh(env):
    # Graduate once
    for _ in range(candidate_pool.ADD_THRESHOLD):
        candidate_pool.propose(
            "add", "personality_traits", "说话直接", "e"
        )
    assert soul_editor.list_traits("personality_traits") == ["说话直接"]

    # Propose again — starts a brand new candidate at count=1
    r = candidate_pool.propose(
        "add", "personality_traits", "说话直接", "again"
    )
    assert r.was_new is True
    assert r.graduated is False
    assert r.candidate.count == 1


# ---- invalid inputs -------------------------------------------------------


def test_propose_invalid_op_raises(env):
    with pytest.raises(ValueError):
        candidate_pool.propose("revise", "quirks", "x", "e")  # type: ignore[arg-type]


def test_propose_frozen_section_raises(env):
    with pytest.raises(soul_editor.SoulEditError):
        candidate_pool.propose("add", "identity", "x", "e")


def test_propose_empty_trait_raises(env):
    with pytest.raises(ValueError):
        candidate_pool.propose("add", "quirks", "   ", "e")


def test_propose_empty_evidence_raises(env):
    with pytest.raises(ValueError):
        candidate_pool.propose("add", "quirks", "x", "   ")


# ---- expire_stale ---------------------------------------------------------


def test_expire_removes_old_candidates(env):
    t_old = datetime(2026, 1, 1, 12, 0, 0)
    candidate_pool.propose("add", "quirks", "熬夜", "e", now=t_old)

    t_now = t_old + timedelta(days=candidate_pool.EXPIRE_DAYS + 1)
    expired = candidate_pool.expire_stale(now=t_now)

    assert len(expired) == 1
    assert expired[0].trait == "熬夜"
    assert candidate_pool.load_pending() == []
    files = list((env["pool"] / "expired").glob("*.json"))
    assert len(files) == 1


def test_expire_keeps_recent_candidates(env):
    t_recent = datetime(2026, 4, 1, 12, 0, 0)
    candidate_pool.propose("add", "quirks", "熬夜", "e", now=t_recent)

    t_now = t_recent + timedelta(days=5)
    expired = candidate_pool.expire_stale(now=t_now)

    assert expired == []
    assert len(candidate_pool.load_pending()) == 1


def test_expire_mixed(env):
    t_old = datetime(2026, 1, 1, 12, 0, 0)
    t_recent = datetime(2026, 4, 10, 12, 0, 0)
    candidate_pool.propose("add", "quirks", "旧的", "e", now=t_old)
    candidate_pool.propose("add", "quirks", "新的", "e", now=t_recent)

    t_now = t_recent + timedelta(days=5)
    expired = candidate_pool.expire_stale(now=t_now)

    assert len(expired) == 1
    assert expired[0].trait == "旧的"
    pending = candidate_pool.load_pending()
    assert [c.trait for c in pending] == ["新的"]


# ---- summarize_pending ---------------------------------------------------


def test_summarize_empty(env):
    assert candidate_pool.summarize_pending() == ""


def test_summarize_non_empty(env):
    candidate_pool.propose("add", "personality_traits", "说话直接", "e1")
    candidate_pool.propose("add", "personality_traits", "说话直接", "e2")
    candidate_pool.propose("remove", "quirks", "爱撒娇", "e1")

    summary = candidate_pool.summarize_pending()
    assert "待毕业候选" in summary
    assert "说话直接" in summary
    assert "(2/3)" in summary
    assert "爱撒娇" in summary
    assert "(1/3)" in summary
