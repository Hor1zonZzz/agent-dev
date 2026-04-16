"""Section-level editor for ``prompts/soul.md``.

Soul has 6 sections; only 4 are mutable by Anna's self-reflection:
``personality_traits`` / ``speaking_style`` / ``values`` / ``quirks``.
``Identity`` and ``Ground Rule`` are frozen — this module doesn't expose
them as valid targets, and the typing literal enforces that at the edge.

Each mutable section holds a bullet list. Empty sections carry the
placeholder ``尚未形成`` so the rendered prompt still reads naturally;
adding the first trait replaces the placeholder, removing the last one
restores it.

Writes are atomic (tmp + os.replace). Frozen section bodies pass
through byte-for-byte.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

SOUL_PATH = Path(__file__).resolve().parent.parent / "prompts" / "soul.md"

MutableSection = Literal[
    "personality_traits",
    "speaking_style",
    "values",
    "quirks",
]

_SECTION_TITLES: dict[str, str] = {
    "personality_traits": "Personality Traits",
    "speaking_style": "Speaking Style",
    "values": "Values & Beliefs",
    "quirks": "Quirks & Habits",
}

_EMPTY_PLACEHOLDER = "尚未形成"


class SoulEditError(ValueError):
    """Raised when a section is missing from soul.md or a target is invalid."""


@dataclass
class _Block:
    title: str   # full header line, e.g. "### Personality Traits"
    body: str    # everything until the next "### " header, newlines preserved

    def render(self) -> str:
        if self.body:
            return f"{self.title}\n{self.body}"
        return self.title


def _validate_section(section: str) -> MutableSection:
    if section not in _SECTION_TITLES:
        raise SoulEditError(
            f"unknown or frozen section {section!r}; "
            f"mutable sections are {list(_SECTION_TITLES)}"
        )
    return section  # type: ignore[return-value]


def _parse_blocks(text: str) -> tuple[str, list[_Block]]:
    """Split soul.md into (preamble, blocks). Preamble is everything before
    the first ``### `` header (typically the ``## Soul`` title line)."""
    lines = text.splitlines()
    first_idx: int | None = None
    for i, line in enumerate(lines):
        if line.startswith("### "):
            first_idx = i
            break
    if first_idx is None:
        return text.rstrip() + "\n", []

    preamble = "\n".join(lines[:first_idx]).rstrip()
    preamble_out = preamble + "\n\n" if preamble else ""

    blocks: list[_Block] = []
    current: _Block | None = None
    buffer: list[str] = []
    for line in lines[first_idx:]:
        if line.startswith("### "):
            if current is not None:
                current.body = "\n".join(buffer).strip("\n")
                blocks.append(current)
            current = _Block(title=line, body="")
            buffer = []
        else:
            buffer.append(line)
    if current is not None:
        current.body = "\n".join(buffer).strip("\n")
        blocks.append(current)

    return preamble_out, blocks


def _find_block(blocks: list[_Block], section: MutableSection) -> _Block:
    target = f"### {_SECTION_TITLES[section]}"
    for b in blocks:
        if b.title.strip() == target:
            return b
    raise SoulEditError(
        f"section {section!r} ({_SECTION_TITLES[section]!r}) not found in soul.md"
    )


def _parse_bullets(body: str) -> list[str]:
    stripped = body.strip()
    if not stripped or stripped == _EMPTY_PLACEHOLDER:
        return []
    items: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("- "):
            items.append(line[2:].strip())
        else:
            items.append(line)
    return items


def _render_bullets(items: list[str]) -> str:
    if not items:
        return _EMPTY_PLACEHOLDER
    return "\n".join(f"- {item}" for item in items)


def _render(preamble: str, blocks: list[_Block]) -> str:
    body = "\n\n".join(b.render() for b in blocks)
    return preamble + body + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-soul-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _rewrite_section(
    section: MutableSection,
    mutate: Callable[[list[str]], bool],
) -> bool:
    """Load soul.md, mutate the given section's bullet list, write back if
    changed. Returns True iff the file was rewritten."""
    text = SOUL_PATH.read_text(encoding="utf-8")
    preamble, blocks = _parse_blocks(text)
    block = _find_block(blocks, section)
    items = _parse_bullets(block.body)
    if not mutate(items):
        return False
    block.body = _render_bullets(items)
    _atomic_write(SOUL_PATH, _render(preamble, blocks))
    return True


# ── Public API ────────────────────────────────────────────────────────


def read_sections() -> dict[str, list[str]]:
    """Return a snapshot of traits for each mutable section. Missing sections
    (shouldn't happen with a canonical soul.md) default to empty lists."""
    text = SOUL_PATH.read_text(encoding="utf-8")
    _preamble, blocks = _parse_blocks(text)
    result: dict[str, list[str]] = {}
    for section in _SECTION_TITLES:
        try:
            block = _find_block(blocks, section)  # type: ignore[arg-type]
        except SoulEditError:
            result[section] = []
            continue
        result[section] = _parse_bullets(block.body)
    return result


def list_traits(section: str) -> list[str]:
    s = _validate_section(section)
    return read_sections()[s]


def add_trait(section: str, trait: str) -> bool:
    """Append a trait to the given section if not already present. Returns
    True if the file was modified, False if the trait was already there."""
    s = _validate_section(section)
    trait = trait.strip()
    if not trait:
        raise SoulEditError("trait must not be empty")

    def mutate(items: list[str]) -> bool:
        if trait in items:
            return False
        items.append(trait)
        return True

    return _rewrite_section(s, mutate)


def remove_trait(section: str, trait: str) -> bool:
    """Remove a trait from the given section. Returns True if removed, False
    if the trait wasn't present (idempotent no-op)."""
    s = _validate_section(section)
    trait = trait.strip()

    def mutate(items: list[str]) -> bool:
        if trait not in items:
            return False
        items.remove(trait)
        return True

    return _rewrite_section(s, mutate)
