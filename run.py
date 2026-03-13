"""
Minimal port of agent-clip's `run` tool framework.

Core concepts:
- Registry: command name → handler mapping. LLM can ONLY call registered commands.
- Chain parser: supports &&, ||, ;, | operators with quote-aware tokenization.
- Single `run` MCP tool: the only tool exposed to the LLM.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Tokenizer — split by whitespace, respecting single/double quotes
# ---------------------------------------------------------------------------

def tokenize(input_str: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    in_quote = False
    quote_char = ""

    for ch in input_str:
        if in_quote:
            if ch == quote_char:
                in_quote = False
            else:
                current.append(ch)
            continue

        if ch in ("'", '"'):
            in_quote = True
            quote_char = ch
            continue

        if ch in (" ", "\t"):
            if current:
                tokens.append("".join(current))
                current.clear()
            continue

        current.append(ch)

    if current:
        tokens.append("".join(current))

    return tokens


# ---------------------------------------------------------------------------
# Chain parser — &&, ||, ;, |
# ---------------------------------------------------------------------------

class Op(Enum):
    NONE = auto()
    AND = auto()   # &&
    OR = auto()    # ||
    SEQ = auto()   # ;
    PIPE = auto()  # |


@dataclass
class Segment:
    raw: str
    op: Op = Op.NONE


def parse_chain(input_str: str) -> list[Segment]:
    segments: list[Segment] = []
    current: list[str] = []
    chars = list(input_str)
    n = len(chars)
    i = 0

    while i < n:
        ch = chars[i]

        # handle quotes
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            i += 1
            while i < n and chars[i] != quote:
                current.append(chars[i])
                i += 1
            if i < n:
                current.append(chars[i])
            i += 1
            continue

        # &&
        if ch == "&" and i + 1 < n and chars[i + 1] == "&":
            segments.append(Segment(raw="".join(current).strip(), op=Op.AND))
            current.clear()
            i += 2
            continue

        # ;
        if ch == ";":
            segments.append(Segment(raw="".join(current).strip(), op=Op.SEQ))
            current.clear()
            i += 1
            continue

        # ||
        if ch == "|" and i + 1 < n and chars[i + 1] == "|":
            segments.append(Segment(raw="".join(current).strip(), op=Op.OR))
            current.clear()
            i += 2
            continue

        # | (single pipe)
        if ch == "|":
            segments.append(Segment(raw="".join(current).strip(), op=Op.PIPE))
            current.clear()
            i += 1
            continue

        current.append(ch)
        i += 1

    last = "".join(current).strip()
    if last:
        segments.append(Segment(raw=last, op=Op.NONE))

    return segments


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

CommandHandler = Callable[[list[str], str], str]
"""(args, stdin) -> output.  Raise Exception on error."""


class Registry:
    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}
        self._help: dict[str, str] = {}
        self._register_builtins()

    def register(self, name: str, description: str, handler: CommandHandler) -> None:
        self._handlers[name] = handler
        self._help[name] = description

    @property
    def help(self) -> dict[str, str]:
        return dict(self._help)

    # -- execution ----------------------------------------------------------

    def exec(self, command: str, stdin: str = "") -> str:
        segments = parse_chain(command)
        if not segments:
            return "[error] empty command"

        collected: list[str] = []
        last_output = ""
        last_err = False
        pipe_input = stdin

        for i, seg in enumerate(segments):
            if i > 0:
                prev_op = segments[i - 1].op
                if prev_op == Op.AND and last_err:
                    continue
                if prev_op == Op.OR and not last_err:
                    continue

            seg_stdin = ""
            if i == 0:
                seg_stdin = pipe_input
            elif segments[i - 1].op == Op.PIPE:
                seg_stdin = last_output

            last_output, last_err = self._exec_single(seg.raw, seg_stdin)

            if i < len(segments) - 1 and seg.op == Op.PIPE:
                continue
            if last_output:
                collected.append(last_output)

        return "\n".join(collected)

    def _exec_single(self, command: str, stdin: str) -> tuple[str, bool]:
        parts = tokenize(command)
        if not parts:
            return "[error] empty command", True

        name = parts[0]
        args = parts[1:]

        handler = self._handlers.get(name)
        if handler is None:
            available = ", ".join(sorted(self._handlers))
            return f"[error] unknown command: {name}\nAvailable: {available}", True

        try:
            out = handler(args, stdin)
            return out, False
        except Exception as e:
            return f"[error] {name}: {e}", True

    # -- builtins -----------------------------------------------------------

    def _register_builtins(self) -> None:
        self.register("echo", "Echo back the input", _builtin_echo)
        self.register("time", "Return the current time", _builtin_time)
        self.register("help", "List available commands", self._builtin_help)
        self.register("grep", "Filter lines matching a pattern (supports -i, -v, -c)", _builtin_grep)
        self.register("head", "Show first N lines (default 10)", _builtin_head)
        self.register("tail", "Show last N lines (default 10)", _builtin_tail)
        self.register("wc", "Count lines, words, chars (-l, -w, -c)", _builtin_wc)

    def _builtin_help(self, args: list[str], stdin: str) -> str:
        lines = [f"  {name} — {desc}" for name, desc in sorted(self._help.items())]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Built-in command implementations
# ---------------------------------------------------------------------------

def _builtin_echo(args: list[str], stdin: str) -> str:
    return stdin if stdin else " ".join(args)


def _builtin_time(args: list[str], stdin: str) -> str:
    return _time.strftime("%Y-%m-%d %H:%M:%S %Z")


def _builtin_grep(args: list[str], stdin: str) -> str:
    ignore_case = False
    invert = False
    count_only = False
    pattern = ""

    for a in args:
        if a == "-i":
            ignore_case = True
        elif a == "-v":
            invert = True
        elif a == "-c":
            count_only = True
        else:
            pattern = a

    if not pattern:
        raise ValueError("usage: grep [-i] [-v] [-c] <pattern>")

    if ignore_case:
        pattern = pattern.lower()

    matched = []
    for line in stdin.split("\n"):
        haystack = line.lower() if ignore_case else line
        match = pattern in haystack
        if invert:
            match = not match
        if match:
            matched.append(line)

    if count_only:
        return str(len(matched))
    return "\n".join(matched)


def _parse_line_count(args: list[str], default: int = 10) -> int:
    n = default
    i = 0
    while i < len(args):
        if args[i] == "-n" and i + 1 < len(args):
            n = int(args[i + 1])
            i += 2
        else:
            try:
                n = int(args[i].lstrip("-"))
            except ValueError:
                pass
            i += 1
    return n


def _builtin_head(args: list[str], stdin: str) -> str:
    n = _parse_line_count(args)
    lines = stdin.split("\n")
    return "\n".join(lines[:n])


def _builtin_tail(args: list[str], stdin: str) -> str:
    n = _parse_line_count(args)
    lines = stdin.split("\n")
    return "\n".join(lines[-n:]) if n > 0 else "\n".join(lines)


def _builtin_wc(args: list[str], stdin: str) -> str:
    lines = len(stdin.split("\n"))
    words = len(stdin.split())
    chars = len(stdin)
    if args:
        if args[0] == "-l":
            return str(lines)
        if args[0] == "-w":
            return str(words)
        if args[0] == "-c":
            return str(chars)
    return f"{lines} lines, {words} words, {chars} chars"


# ---------------------------------------------------------------------------
# MCP tool definition helper
# ---------------------------------------------------------------------------

def run_tool_description(commands: dict[str, str]) -> str:
    """Build the `run` tool description from registered command help."""
    lines = [
        "Your ONLY tool. Execute commands via run(command=\"...\"). "
        "Supports chaining: cmd1 && cmd2, cmd1 | cmd2.\n\nAvailable commands:"
    ]
    for name, desc in sorted(commands.items()):
        lines.append(f"  {name} — {desc}")
    return "\n".join(lines)
