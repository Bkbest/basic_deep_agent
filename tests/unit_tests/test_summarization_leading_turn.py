"""Tests for the "request must start with a user turn" invariant.

After a summarization cutoff the retained tail can begin at an assistant reply
(or at tool results whose assistant turn was summarized away). Ollama answers
such a request with empty content, and the synthetic user turn that used to fix
it was only added when the tail was *completely* empty -- and was never written
to state, so the very next turn lost it again.

These tests pin the corrected behaviour: the synthetic turn is recomputed on
every call and is never persisted.
"""

import os
import sys

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

try:
    import pytest
except ModuleNotFoundError:  # allow running as a plain script
    pytest = None

# Make `src` importable when this file is run directly or via pytest.
_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"
)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import AI_Nodes.nodes as nodes  # noqa: E402
from langmem.short_term import RunningSummary, SummarizationResult  # noqa: E402

pytestmark = pytest.mark.anyio if pytest else []


def _summary(text="Carried over work."):
    return RunningSummary(
        summary=text,
        summarized_message_ids=set(),
        last_summarized_message_id="m2",
    )


def _stub_summarization(monkeypatch, returned_messages, returned_summary):
    """Make `asummarize_messages` return a scripted result."""

    async def fake_summarize(*args, **kwargs):
        return SummarizationResult(
            messages=returned_messages,
            running_summary=returned_summary,
        )

    monkeypatch.setattr(nodes, "asummarize_messages", fake_summarize)


# ---------------------------------------------------------------------------
# The predicate
# ---------------------------------------------------------------------------


def test_needs_leading_user_turn_for_assistant_first_tail():
    assert nodes._needs_leading_user_turn([AIMessage(content="working")]) is True


def test_needs_leading_user_turn_for_tool_first_tail():
    assert nodes._needs_leading_user_turn([ToolMessage(content="{}", tool_call_id="1")]) is True


def test_needs_leading_user_turn_when_empty():
    assert nodes._needs_leading_user_turn([]) is True


def test_needs_leading_user_turn_ignores_leading_system_message():
    messages = [SystemMessage(content="sys"), AIMessage(content="working")]
    assert nodes._needs_leading_user_turn(messages) is True


def test_leading_user_turn_satisfied():
    assert nodes._needs_leading_user_turn([HumanMessage(content="hi")]) is False
    assert (
        nodes._needs_leading_user_turn(
            [HumanMessage(content="hi"), AIMessage(content="working")]
        )
        is False
    )


# ---------------------------------------------------------------------------
# `_summarize` -- the reported bug
# ---------------------------------------------------------------------------


async def test_assistant_only_tail_gets_a_user_turn(monkeypatch):
    """Turn N+1: the tail is just the previous assistant reply.

    This is the shape that produced "No message content" in the reported run.
    """
    assistant_only = AIMessage(content="I'll check the todos.", id="m3")
    _stub_summarization(monkeypatch, [assistant_only], _summary())

    kept, summary = await nodes._summarize(
        [HumanMessage(content="go", id="m1"), assistant_only], _summary()
    )

    assert isinstance(kept[0], HumanMessage)
    assert kept[0].content == nodes.SUMMARY_ONLY_USER_MESSAGE
    assert kept[1] is assistant_only
    assert summary is not None


async def test_tool_first_tail_still_sends_a_user_turn(monkeypatch):
    """Turn N+2: the tail begins with orphaned tool results.

    `_sanitize_conversation` drops them, which leaves nothing but the summary,
    so the request becomes a single synthetic user turn.
    """
    tool_message = ToolMessage(content="{}", tool_call_id="1", id="m4")
    _stub_summarization(monkeypatch, [tool_message], _summary())

    kept, _ = await nodes._summarize(
        [HumanMessage(content="go", id="m1"), tool_message], _summary()
    )

    assert len(kept) == 1
    assert isinstance(kept[0], HumanMessage)
    assert kept[0].content == nodes.SUMMARY_ONLY_USER_MESSAGE


def test_ensure_leading_user_turn_handles_tool_first_tail():
    """An unsanitized tool-first input is still fronted with a user turn."""
    tool_message = ToolMessage(content="{}", tool_call_id="1")

    kept = nodes._ensure_leading_user_turn([tool_message], _summary(), [tool_message])

    assert isinstance(kept[0], HumanMessage)
    assert kept[1] is tool_message


async def test_empty_tail_with_summary_keeps_old_behaviour(monkeypatch):
    _stub_summarization(monkeypatch, [], _summary())

    kept, _ = await nodes._summarize([HumanMessage(content="go", id="m1")], _summary())

    assert len(kept) == 1
    assert isinstance(kept[0], HumanMessage)
    assert kept[0].content == nodes.SUMMARY_ONLY_USER_MESSAGE


async def test_human_first_tail_is_left_alone(monkeypatch):
    human = HumanMessage(content="new question", id="m5")
    assistant = AIMessage(content="answering", id="m6")
    _stub_summarization(monkeypatch, [human, assistant], _summary())

    kept, _ = await nodes._summarize([human, assistant], _summary())

    assert kept == [human, assistant], "must not inject a duplicate user turn"


async def test_no_summary_and_no_conversation_falls_back_to_history(monkeypatch):
    """Nothing to summarize and no summary: replay, but still user-first."""
    assistant = AIMessage(content="orphan", id="m2")
    _stub_summarization(monkeypatch, [], None)

    kept, summary = await nodes._summarize([assistant], None)

    assert summary is None
    assert isinstance(kept[0], HumanMessage)
    assert kept[0].content == nodes.CONTINUATION_USER_MESSAGE
    assert kept[1] is assistant


async def test_continuation_message_does_not_claim_a_missing_summary(monkeypatch):
    assistant = AIMessage(content="orphan", id="m2")
    _stub_summarization(monkeypatch, [assistant], None)

    kept, _ = await nodes._summarize([assistant], None)

    assert kept[0].content == nodes.CONTINUATION_USER_MESSAGE
    assert "summary" not in kept[0].content.lower()


async def test_summarization_failure_also_fronts_the_history(monkeypatch):
    """An exception must not bypass the invariant."""

    async def boom(*args, **kwargs):
        raise RuntimeError("summarizer down")

    monkeypatch.setattr(nodes, "asummarize_messages", boom)

    assistant = AIMessage(content="orphan", id="m2")
    kept, summary = await nodes._summarize([assistant], _summary())

    assert isinstance(kept[0], HumanMessage)
    assert kept[1] is assistant
    assert summary is not None


async def test_synthetic_turn_is_rebuilt_each_call(monkeypatch):
    """The synthetic turn is per-request, so the next call must re-add it.

    This is the regression the report describes: it went out once, was never
    persisted, and the following turn was assistant-first again.
    """
    assistant = AIMessage(content="working", id="m3")

    _stub_summarization(monkeypatch, [assistant], _summary())
    first, _ = await nodes._summarize([assistant], _summary())

    _stub_summarization(monkeypatch, [assistant], _summary())
    second, _ = await nodes._summarize([assistant], _summary())

    for kept in (first, second):
        assert isinstance(kept[0], HumanMessage)
        assert kept[0].id == nodes.CONTINUATION_MESSAGE_ID


async def test_llm_receives_a_user_turn(monkeypatch):
    """End-to-end through `llm_with_tools`: the request is never AI-first."""

    class RecordingLLM:
        def __init__(self):
            self.seen = None

        async def ainvoke(self, messages):
            self.seen = messages
            return AIMessage(content="Done.")

    class FakeRuntime:
        class execution_info:
            node_attempt = 1

    assistant = AIMessage(content="working", id="m3")
    _stub_summarization(monkeypatch, [assistant], _summary())

    recording = RecordingLLM()
    monkeypatch.setattr(nodes, "llm_tools", recording)

    state = {
        "messages": [assistant],
        "current_date": "Fri Oct 30, 2026",
        "skills_description": "none",
        "soul": None,
        "summary": _summary(),
        "todos": [],
    }

    await nodes.llm_with_tools(state, FakeRuntime)

    sent = recording.seen
    assert isinstance(sent[0], SystemMessage)
    assert isinstance(sent[1], HumanMessage), (
        "Ollama returns empty content when the first non-system message is not "
        "a user turn"
    )
    assert sent[2] is assistant
    assert state["messages"] == [assistant], (
        "the synthetic turn must not be persisted to state"
    )
