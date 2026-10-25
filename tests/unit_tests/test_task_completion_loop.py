"""Tests for the agent loop's task-completion check.

Verifies that when the model stops calling tools the graph does *not* end
immediately: the completion check decides between finishing and looping back.

The LLM is stubbed everywhere, so these run fast and offline. For a check
against the real model, run:

    python -m tests.unit_tests.test_task_completion_loop

which executes the ``main()`` demo at the bottom.
"""

import asyncio
import os
import sys

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

try:
    import pytest
except ModuleNotFoundError:  # allow running as a plain script
    pytest = None

# Make `src` importable when this file is run directly or via pytest.
_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import AI_Nodes.nodes as nodes  # noqa: E402
from AI_State.state import State  # noqa: E402
from AI_STRUCT_OUT.task_completion import TaskCompletion  # noqa: E402

# anyio marker is only meaningful under pytest; ignore it when run standalone.
pytestmark = pytest.mark.anyio if pytest else []


class FakeStructured:
    """Stand-in for the structured-output LLM returning scripted verdicts."""

    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.calls = 0
        self.prompts = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        idx = min(self.calls, len(self.verdicts) - 1)
        self.calls += 1
        return TaskCompletion(
            is_complete=self.verdicts[idx],
            reasoning="stub verdict",
        )


class ScriptedAgent:
    """Stand-in for `llm_with_tools`, emitting scripted AIMessages in order."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    async def __call__(self, state):
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return {"messages": [self.responses[idx]]}


def build_loop_graph(agent, monkeypatch, structured):
    """Build the exact routing topology the real agent graph uses."""
    monkeypatch.setattr(nodes, "llm_task_completion", structured)

    graph = StateGraph(State)
    graph.add_node("llm_with_tools", agent)
    graph.add_node("tool_node", lambda state: {})
    graph.add_node("llm_is_task_complete", nodes.llm_is_task_complete)

    graph.add_edge(START, "llm_with_tools")
    graph.add_conditional_edges("llm_with_tools", nodes.is_tool_required)
    graph.add_edge("tool_node", "llm_with_tools")
    graph.add_conditional_edges("llm_is_task_complete", nodes.route_after_completion_check)
    return graph.compile()


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


async def test_tool_call_routes_to_tool_node():
    msg = AIMessage(content="", tool_calls=[{"name": "write_todos", "args": {}, "id": "1"}])
    assert await nodes.is_tool_required({"messages": [msg]}) == "tool_node"


async def test_no_tool_call_routes_to_completion_check_not_end():
    msg = AIMessage(content="Here is what I found so far.")
    result = await nodes.is_tool_required({"messages": [msg]})
    assert result == "llm_is_task_complete"
    assert result != END


async def test_route_after_completion_check():
    assert nodes.route_after_completion_check({"is_task_complete": True}) == END
    assert nodes.route_after_completion_check({"is_task_complete": False}) == "llm_with_tools"
    # Missing key must not be treated as complete.
    assert nodes.route_after_completion_check({}) == "llm_with_tools"


# ---------------------------------------------------------------------------
# The completion check itself
# ---------------------------------------------------------------------------

_PARTIAL_STATE = {
    "messages": [
        HumanMessage(content="Summarize the paper"),
        AIMessage(content="I've read it, working on the summary."),
    ],
    "todos": [
        {"content": "Read paper", "status": "completed"},
        {"content": "Write summary", "status": "in_progress"},
    ],
}


async def test_incomplete_verdict_loops_back(monkeypatch):
    monkeypatch.setattr(nodes, "llm_task_completion", FakeStructured([False]))
    out = await nodes.llm_is_task_complete(_PARTIAL_STATE)

    assert out["is_task_complete"] is False
    assert out["task_completion_reasoning"] == "stub verdict"
    assert nodes.route_after_completion_check(out) == "llm_with_tools"


async def test_complete_verdict_ends(monkeypatch):
    monkeypatch.setattr(nodes, "llm_task_completion", FakeStructured([True]))
    out = await nodes.llm_is_task_complete(_PARTIAL_STATE)

    assert out["is_task_complete"] is True
    assert nodes.route_after_completion_check(out) == END


async def test_prompt_includes_todos_and_conversation(monkeypatch):
    fake = FakeStructured([False])
    monkeypatch.setattr(nodes, "llm_task_completion", fake)
    await nodes.llm_is_task_complete(_PARTIAL_STATE)

    prompt = fake.prompts[0]
    assert "Write summary" in prompt
    assert "in_progress" in prompt
    assert "Read paper" in prompt
    assert "Summarize the paper" in prompt


async def test_llm_failure_keeps_working(monkeypatch):
    """A failed check must not silently end the run."""

    class Boom:
        async def ainvoke(self, prompt):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(nodes, "llm_task_completion", Boom())
    out = await nodes.llm_is_task_complete(_PARTIAL_STATE)

    assert out["is_task_complete"] is False
    assert "model unavailable" in out["task_completion_reasoning"]
    assert nodes.route_after_completion_check(out) == "llm_with_tools"


async def test_no_todos_judged_from_conversation(monkeypatch):
    fake = FakeStructured([True])
    monkeypatch.setattr(nodes, "llm_task_completion", fake)
    out = await nodes.llm_is_task_complete({"messages": [HumanMessage(content="hi")], "todos": []})

    assert out["is_task_complete"] is True
    assert "No TODO list was created" in fake.prompts[0]


def test_format_conversation_skips_empty_and_notes_tool_calls():
    rendered = nodes._format_conversation([
        AIMessage(content=""),  # no content, no tool calls -> skipped
        AIMessage(content="", tool_calls=[{"name": "internet_search", "args": {}, "id": "1"}]),
        HumanMessage(content="next"),
    ])
    assert "internet_search" in rendered
    assert "next" in rendered


# ---------------------------------------------------------------------------
# Full loop topology
# ---------------------------------------------------------------------------


async def test_loop_repeats_until_complete(monkeypatch):
    """Partial answer -> loop once -> final answer -> END."""
    agent = ScriptedAgent([
        AIMessage(content="Here is a partial answer."),
        AIMessage(content="Now the full final answer."),
    ])
    structured = FakeStructured([False, True])
    graph = build_loop_graph(agent, monkeypatch, structured)

    out = await graph.ainvoke({
        "messages": [HumanMessage(content="Do the thing")],
        "todos": [{"content": "Step 1", "status": "pending"}],
    })

    assert agent.calls == 2, "should have looped back exactly once"
    assert structured.calls == 2
    assert out["is_task_complete"] is True


async def test_completes_immediately(monkeypatch):
    agent = ScriptedAgent([AIMessage(content="Done.")])
    structured = FakeStructured([True])
    graph = build_loop_graph(agent, monkeypatch, structured)

    out = await graph.ainvoke({"messages": [HumanMessage(content="hi")], "todos": []})

    assert agent.calls == 1
    assert out["is_task_complete"] is True


async def test_tool_call_path_returns_then_completes(monkeypatch):
    agent = ScriptedAgent([
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
        AIMessage(content="Final answer."),
    ])
    structured = FakeStructured([True])
    graph = build_loop_graph(agent, monkeypatch, structured)

    out = await graph.ainvoke({"messages": [HumanMessage(content="hi")], "todos": []})

    assert agent.calls == 2, "tool call -> tool_node -> back to llm -> END"
    assert out["is_task_complete"] is True


# ---------------------------------------------------------------------------
# Optional: real-model check (opt-in, makes network calls)
# ---------------------------------------------------------------------------


async def _demo_against_real_llm():
    """Run the completion check against the configured model."""
    cases = {
        "INCOMPLETE (todos still open)": {
            "messages": [
                HumanMessage(content="Write a report on transformers."),
                AIMessage(content="I'll start by searching for recent papers."),
            ],
            "todos": [
                {"content": "Search for papers", "status": "completed"},
                {"content": "Write the report", "status": "in_progress"},
                {"content": "Proofread", "status": "pending"},
            ],
        },
        "COMPLETE (question answered)": {
            "messages": [
                HumanMessage(content="What is 2+2?"),
                AIMessage(content="4. Let me know if you need anything else."),
            ],
            "todos": [],
        },
    }

    for label, state in cases.items():
        out = await nodes.llm_is_task_complete(state)
        print(f"{label} -> is_task_complete={out['is_task_complete']}")
        print(f"   reasoning: {out['task_completion_reasoning']}")
        print(f"   route: {nodes.route_after_completion_check(out)}\n")


# ---------------------------------------------------------------------------
# Standalone runner (works without pytest installed)
# ---------------------------------------------------------------------------


class _MonkeyPatch:
    """Minimal stand-in for pytest's monkeypatch fixture."""

    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        self._undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)
        self._undo.clear()


async def _run_standalone() -> int:
    """Run every stubbed check without pytest. Returns nonzero on failure."""
    checks = [
        ("tool call -> tool_node", test_tool_call_routes_to_tool_node),
        ("no tool call -> completion check", test_no_tool_call_routes_to_completion_check_not_end),
        ("route_after_completion_check", test_route_after_completion_check),
        ("incomplete -> loop back", test_incomplete_verdict_loops_back),
        ("complete -> end", test_complete_verdict_ends),
        ("prompt has todos + conversation", test_prompt_includes_todos_and_conversation),
        ("llm failure keeps working", test_llm_failure_keeps_working),
        ("no todos -> judge conversation", test_no_todos_judged_from_conversation),
        ("format_conversation", test_format_conversation_skips_empty_and_notes_tool_calls),
        ("loop repeats until complete", test_loop_repeats_until_complete),
        ("completes immediately", test_completes_immediately),
        ("tool path then completes", test_tool_call_path_returns_then_completes),
    ]

    failures = 0
    for label, check in checks:
        mp = _MonkeyPatch()
        try:
            result = check(mp) if check.__code__.co_argcount else check()
            if asyncio.iscoroutine(result):
                await result
            print(f"  PASS  {label}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL  {label}: {e}")
        except Exception as e:
            failures += 1
            print(f"  ERROR {label}: {type(e).__name__}: {e}")
        finally:
            mp.undo()

    print(f"\n{failures} failure(s) out of {len(checks)} checks")
    return failures


if __name__ == "__main__":
    print("=== Offline checks (stubbed LLM) ===")
    exit_code = asyncio.run(_run_standalone())

    if "--with-llm" in sys.argv:
        print("\n=== Real model check ===")
        asyncio.run(_demo_against_real_llm())

    sys.exit(1 if exit_code else 0)