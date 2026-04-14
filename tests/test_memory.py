"""Memory compression module tests.

Run:  uv run python -m pytest tests/test_memory.py -v
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

from core.memory import (
    COMPRESS_EVERY,
    HISTORY_DIR,
    RECENT_K,
    SUMMARY_MODEL,
    _compress,
    _parse_summary_response,
    append_to_history,
    count_meaningful,
    estimate_tokens,
    load_for_llm,
    load_latest_summary,
    maybe_compress,
)

# ── Fixtures ──────────────────────────────────────────────────────────

SAMPLE_CONVERSATION: list[dict] = [
    {"role": "user", "content": "你好啊Anna，我叫小明，今天工作特别累"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {
                    "name": "send_message",
                    "arguments": '{"message":"小明你好呀～工作累了就好好休息一下"}',
                },
            }
        ],
    },
    {"role": "tool", "tool_call_id": "c1", "content": "Message sent."},
    {"role": "user", "content": "我最近在学弹吉他，想弹周杰伦的晴天"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c2",
                "type": "function",
                "function": {
                    "name": "send_message",
                    "arguments": '{"message":"晴天！经典曲目，我帮你记着进展～"}',
                },
            }
        ],
    },
    {"role": "tool", "tool_call_id": "c2", "content": "Message sent."},
    {"role": "user", "content": "我不太喜欢别人跟我讲大道理"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c3",
                "type": "function",
                "function": {
                    "name": "send_message",
                    "arguments": '{"message":"收到收到，不讲大道理！"}',
                },
            }
        ],
    },
    {"role": "tool", "tool_call_id": "c3", "content": "Message sent."},
    {"role": "user", "content": "明天有个重要会议，帮我记一下"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c4",
                "type": "function",
                "function": {
                    "name": "send_message",
                    "arguments": '{"message":"记下了！明天我会提醒你的"}',
                },
            }
        ],
    },
    {"role": "tool", "tool_call_id": "c4", "content": "Message sent."},
]

SAMPLE_LLM_RESPONSE = """\
## user_facts
- 名字：小明
- 今天工作特别累
- 最近在学弹吉他，想弹周杰伦的《晴天》
- 明天有个重要会议

## user_state
- 当前状态：工作后感到疲惫
- 需求：希望得到放松和提醒

## user_preferences
- 不喜欢别人讲大道理

## anna_stance
- 友好、关心、语气轻松温暖

## anna_commitments
- 承诺记住用户学吉他弹《晴天》的进展
- 承诺明天提醒用户开会

## topic_thread
1. 用户自我介绍（小明），工作劳累
2. 用户分享学吉他，目标弹《晴天》
3. 用户表示不喜欢听大道理
4. 用户请求记住明天的会议

## open_threads
- 用户学吉他弹《晴天》的进展
- 明天的重要会议提醒
"""


@pytest.fixture()
def tmp_history(tmp_path: Path) -> Path:
    """Return a temporary history JSON path."""
    return tmp_path / "test_history.json"


@pytest.fixture()
def summary_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Redirect HISTORY_DIR to a temp directory so tests don't pollute the real one."""
    import core.memory as mem

    monkeypatch.setattr(mem, "HISTORY_DIR", tmp_path)
    return tmp_path


# ── Unit tests ────────────────────────────────────────────────────────


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens([]) == 0

    def test_basic(self):
        msgs = [{"role": "user", "content": "hello world"}]
        tokens = estimate_tokens(msgs)
        # JSON string ~40 chars, /3 ≈ 13
        assert 5 < tokens < 30

    def test_chinese(self):
        msgs = [{"role": "user", "content": "你好世界" * 100}]
        tokens = estimate_tokens(msgs)
        assert tokens > 100


class TestParseSummaryResponse:
    def test_full_response(self):
        result = _parse_summary_response(SAMPLE_LLM_RESPONSE)
        assert "user" in result
        assert "anna" in result
        assert "shared" in result

        # User should contain all three sub-sections
        assert "user_facts" in result["user"]
        assert "user_state" in result["user"]
        assert "user_preferences" in result["user"]
        assert "小明" in result["user"]

        # Anna
        assert "anna_stance" in result["anna"]
        assert "anna_commitments" in result["anna"]
        assert "吉他" in result["anna"]

        # Shared
        assert "topic_thread" in result["shared"]
        assert "open_threads" in result["shared"]

    def test_missing_sections(self):
        partial = "## user_facts\n- 名字：小明\n\n## topic_thread\n聊了工作\n"
        result = _parse_summary_response(partial)
        assert "小明" in result["user"]
        assert "暂无" not in result["user"]  # user_facts is present
        assert "暂无" in result["anna"]  # no anna sections
        assert "topic_thread" in result["shared"]

    def test_empty_response(self):
        result = _parse_summary_response("")
        assert result["user"] == "（暂无）"
        assert result["anna"] == "（暂无）"
        assert result["shared"] == "（暂无）"


class TestAppendToHistory:
    def test_create_new(self, tmp_history: Path):
        msgs = [{"role": "user", "content": "hello"}]
        append_to_history(tmp_history, msgs)

        data = json.loads(tmp_history.read_text())
        assert len(data) == 1
        assert data[0]["content"] == "hello"

    def test_append_existing(self, tmp_history: Path):
        initial = [{"role": "user", "content": "first"}]
        tmp_history.parent.mkdir(parents=True, exist_ok=True)
        tmp_history.write_text(json.dumps(initial))

        append_to_history(tmp_history, [{"role": "assistant", "content": "second"}])

        data = json.loads(tmp_history.read_text())
        assert len(data) == 2
        assert data[0]["content"] == "first"
        assert data[1]["content"] == "second"

    def test_append_empty(self, tmp_history: Path):
        initial = [{"role": "user", "content": "only"}]
        tmp_history.parent.mkdir(parents=True, exist_ok=True)
        tmp_history.write_text(json.dumps(initial))

        append_to_history(tmp_history, [])

        data = json.loads(tmp_history.read_text())
        assert len(data) == 1


class TestLoadForLlm:
    def test_no_history(self, tmp_history: Path, summary_dirs):
        recent, memory = load_for_llm(tmp_history)
        assert recent == []
        assert memory is None

    def test_within_window(self, tmp_history: Path, summary_dirs):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        tmp_history.parent.mkdir(parents=True, exist_ok=True)
        tmp_history.write_text(json.dumps(msgs))

        recent, memory = load_for_llm(tmp_history)
        assert len(recent) == 10
        assert memory is None

    def test_exceeds_window(self, tmp_history: Path, summary_dirs, monkeypatch):
        import core.memory as mem

        monkeypatch.setattr(mem, "RECENT_K", 5)

        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        tmp_history.parent.mkdir(parents=True, exist_ok=True)
        tmp_history.write_text(json.dumps(msgs))

        recent, memory = load_for_llm(tmp_history)
        assert len(recent) == 5
        assert recent[0]["content"] == "msg15"
        assert recent[-1]["content"] == "msg19"

    def test_with_summary(self, tmp_history: Path, summary_dirs):
        # Create history
        msgs = [{"role": "user", "content": "hello"}]
        tmp_history.parent.mkdir(parents=True, exist_ok=True)
        tmp_history.write_text(json.dumps(msgs))

        # Create summary files
        ts = "20260410_120000"
        for dim, content in [
            ("user", "### user_facts\n- 名字：小明"),
            ("anna", "### anna_stance\n- 友好"),
            ("shared", "### topic_thread\n聊了工作"),
        ]:
            d = summary_dirs / dim
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{ts}.md").write_text(content)

        recent, memory = load_for_llm(tmp_history)
        assert len(recent) == 1
        assert memory is not None
        assert "小明" in memory
        assert "友好" in memory
        assert "工作" in memory


class TestLoadLatestSummary:
    def test_no_summaries(self, summary_dirs):
        assert load_latest_summary() is None

    def test_empty_dir(self, summary_dirs):
        (summary_dirs / "user").mkdir()
        assert load_latest_summary() is None

    def test_picks_latest(self, summary_dirs):
        for ts in ("20260410_100000", "20260410_120000"):
            for dim in ("user", "anna", "shared"):
                d = summary_dirs / dim
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{ts}.md").write_text(f"{dim} at {ts}")

        result = load_latest_summary()
        assert result is not None
        assert "120000" in result
        # Should contain all three sections
        assert "About the user" in result
        assert "About Anna" in result
        assert "Conversation context" in result


class TestMaybeCompress:
    def test_below_threshold(self, tmp_history: Path, monkeypatch):
        import core.memory as mem

        monkeypatch.setattr(mem, "_compress_task", None)
        msgs = [{"role": "user", "content": "short"}]
        tmp_history.parent.mkdir(parents=True, exist_ok=True)
        tmp_history.write_text(json.dumps(msgs))

        asyncio.run(maybe_compress(tmp_history))
        # Should not have spawned a task (no error, no crash)

    def test_no_file(self, tmp_history: Path, monkeypatch):
        import core.memory as mem

        monkeypatch.setattr(mem, "_compress_task", None)
        asyncio.run(maybe_compress(tmp_history))
        # Should return silently


# ── Integration test (requires real API) ──────────────────────────────


class TestCompressIntegration:
    """Calls the real LLM API. Skip with: pytest -m 'not integration'"""

    @pytest.mark.integration
    def test_full_pipeline(self, tmp_history: Path, summary_dirs):
        """End-to-end: write history → compress → verify summary files."""
        tmp_history.parent.mkdir(parents=True, exist_ok=True)
        tmp_history.write_text(
            json.dumps(SAMPLE_CONVERSATION, ensure_ascii=False, indent=2)
        )

        # Run compression
        asyncio.run(_compress(tmp_history))

        # Verify files were created
        for dim in ("anna", "user", "shared"):
            md_files = list((summary_dirs / dim).glob("*.md"))
            assert len(md_files) == 1, f"Expected 1 file in {dim}/, got {len(md_files)}"

            content = md_files[0].read_text()
            assert content.strip(), f"{dim} summary is empty"
            assert "暂无" not in content or dim == "anna", (
                f"{dim} should have content from the test conversation"
            )

        # Verify load_latest_summary combines them
        summary = load_latest_summary()
        assert summary is not None
        assert "About the user" in summary
        assert "About Anna" in summary
        assert "Conversation context" in summary
