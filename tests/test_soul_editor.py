"""Soul section editor tests.

Run:  uv run python -m pytest tests/test_soul_editor.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes import soul_editor
from hermes.soul_editor import (
    SoulEditError,
    add_trait,
    list_traits,
    read_sections,
    remove_trait,
)


CANONICAL_SOUL = """\
## Soul

### Identity
- Name: Anna

### Ground Rule
You are not an assistant, not a customer service bot, not a search engine. Just be yourself — talk like a real person, naturally and honestly.

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
def soul_path(tmp_path, monkeypatch) -> Path:
    p = tmp_path / "soul.md"
    p.write_text(CANONICAL_SOUL, encoding="utf-8")
    monkeypatch.setattr(soul_editor, "SOUL_PATH", p)
    return p


# ---- read_sections --------------------------------------------------------


def test_read_sections_empty_all(soul_path: Path):
    sections = read_sections()
    assert set(sections) == {
        "personality_traits", "speaking_style", "values", "quirks"
    }
    for traits in sections.values():
        assert traits == []


def test_list_traits_empty(soul_path: Path):
    assert list_traits("personality_traits") == []


# ---- add_trait ------------------------------------------------------------


def test_add_first_trait_replaces_placeholder(soul_path: Path):
    changed = add_trait("personality_traits", "说话直接")
    assert changed is True
    content = soul_path.read_text(encoding="utf-8")
    assert "尚未形成" in content  # still in the other 3 sections
    assert "- 说话直接" in content
    assert list_traits("personality_traits") == ["说话直接"]


def test_add_second_trait_appends(soul_path: Path):
    add_trait("personality_traits", "说话直接")
    add_trait("personality_traits", "偶尔毒舌")
    assert list_traits("personality_traits") == ["说话直接", "偶尔毒舌"]


def test_add_duplicate_is_noop(soul_path: Path):
    assert add_trait("quirks", "爱喝热茶") is True
    assert add_trait("quirks", "爱喝热茶") is False
    assert list_traits("quirks") == ["爱喝热茶"]


def test_add_strips_whitespace(soul_path: Path):
    add_trait("speaking_style", "  简短  ")
    assert list_traits("speaking_style") == ["简短"]


def test_add_empty_trait_raises(soul_path: Path):
    with pytest.raises(SoulEditError):
        add_trait("values", "   ")


# ---- remove_trait ---------------------------------------------------------


def test_remove_existing_trait(soul_path: Path):
    add_trait("quirks", "爱喝热茶")
    add_trait("quirks", "熬夜")
    changed = remove_trait("quirks", "爱喝热茶")
    assert changed is True
    assert list_traits("quirks") == ["熬夜"]


def test_remove_missing_trait_returns_false(soul_path: Path):
    assert remove_trait("quirks", "nope") is False


def test_remove_last_trait_restores_placeholder(soul_path: Path):
    add_trait("values", "真诚")
    assert list_traits("values") == ["真诚"]
    remove_trait("values", "真诚")
    assert list_traits("values") == []
    content = soul_path.read_text(encoding="utf-8")
    # Placeholder should be back — so the prompt still reads naturally.
    assert "### Values & Beliefs\n尚未形成" in content


# ---- frozen sections ------------------------------------------------------


def test_frozen_section_add_rejected(soul_path: Path):
    with pytest.raises(SoulEditError):
        add_trait("identity", "anything")


def test_unknown_section_rejected(soul_path: Path):
    with pytest.raises(SoulEditError):
        add_trait("bogus_section", "anything")


def test_ground_rule_preserved_through_edits(soul_path: Path):
    add_trait("personality_traits", "说话直接")
    add_trait("quirks", "熬夜")
    remove_trait("quirks", "熬夜")
    content = soul_path.read_text(encoding="utf-8")
    assert "You are not an assistant" in content
    assert "Just be yourself" in content
    assert "- Name: Anna" in content


def test_section_ordering_preserved(soul_path: Path):
    add_trait("quirks", "熬夜")
    add_trait("personality_traits", "说话直接")
    content = soul_path.read_text(encoding="utf-8")
    order = [
        content.index("### Identity"),
        content.index("### Ground Rule"),
        content.index("### Personality Traits"),
        content.index("### Speaking Style"),
        content.index("### Values & Beliefs"),
        content.index("### Quirks & Habits"),
    ]
    assert order == sorted(order)


# ---- roundtrip ------------------------------------------------------------


def test_noop_roundtrip_preserves_bytes(soul_path: Path):
    """Reading and then writing without changes should not mutate the file."""
    before = soul_path.read_text(encoding="utf-8")
    # add_trait with an existing dupe is a no-op; forces read but no write
    add_trait("quirks", "x")      # write 1
    remove_trait("quirks", "x")   # write 2 back to placeholder state
    after = soul_path.read_text(encoding="utf-8")
    assert before == after
