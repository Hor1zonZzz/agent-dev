"""Edit a prompt template file — restricted to the prompts/ directory."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from core.tool import Tool

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_ALLOWED_FILES = {"soul.md", "guidelines.md", "user_profile.md", "mood.md"}


class EditPromptParams(BaseModel):
    filename: str = Field(
        description=(
            f"The prompt file to edit. Allowed values: {', '.join(sorted(_ALLOWED_FILES))}"
        ),
    )
    old_text: str = Field(description="The exact text to find in the file.")
    new_text: str = Field(description="The replacement text.")


def _edit_prompt(filename: str, old_text: str, new_text: str) -> str:
    if filename not in _ALLOWED_FILES:
        return f"Error: '{filename}' is not an allowed file. Choose from: {', '.join(sorted(_ALLOWED_FILES))}"

    path = _PROMPTS_DIR / filename
    if not path.exists():
        return f"Error: '{filename}' does not exist."

    content = path.read_text(encoding="utf-8")

    if old_text not in content:
        return f"Error: old_text not found in '{filename}'."

    if content.count(old_text) > 1:
        return f"Error: old_text matches {content.count(old_text)} locations in '{filename}'. Provide more context to make it unique."

    content = content.replace(old_text, new_text, 1)
    path.write_text(content, encoding="utf-8")
    return f"Updated '{filename}' successfully."


edit_prompt = Tool(
    name="edit_prompt",
    description=(
        "Edit a prompt template file by replacing exact text. "
        "Only files in the prompts/ directory are allowed: "
        f"{', '.join(sorted(_ALLOWED_FILES))}."
    ),
    params=EditPromptParams,
    fn=_edit_prompt,
)
