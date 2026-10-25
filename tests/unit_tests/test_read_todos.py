"""Tests for the ``read_todos`` tool.

These tests cover four layers:

1. Formatting      - the rendered string for empty, partial and full lists.
2. Schema          - injected arguments stay hidden from the model.
3. ToolNode        - the exact execution path that produced
                     "Error invoking tool 'read_todos' with kwargs {} with error:".
4. Compiled graph  - state injection against the real ``State`` schema.

Layer 3 and layer 4 are the regression tests for the bug: ``read_todos`` used
to annotate its state as ``Annotated[State, InjectedState]``. langchain-core
validates injected arguments (``include_injected=True``), so pydantic validated
the *entire* graph state against the ``State`` TypedDict. In a TypedDict,
``Optional[X] = None`` does not make a key optional, so keys such as
``is_task_complete`` and ``incomplete_attempts`` were reported as missing. The
failure lands under the injected ``state`` argument, langgraph filters such
errors out, and the resulting ToolMessage ends up with an empty error body.

Run with::

    python -m pytest tests/unit_tests/test_read_todos.py -v

The tests are synchronous on purpose so they do not depend on
pytest-asyncio or anyio being installed, matching the repository's
``python -m pytest tests/unit_tests`` Makefile target.
"""

import os
import sys

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt.tool_node import ToolNode

# Make `src` importable when this file is run directly or via pytest.
_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src",
)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from AI_State.state import State  # noqa: E402
from AI_Tools.tools import read_todos  # noqa: E402

# The generic "the tool blew up" text langgraph puts in an error ToolMessage.
FAILURE_TEXT = "Please fix the error and try again."

EMPTY_MESSAGE = "No todos currently in the list."


def _run(state: dict, tool_call_id: str = "call-1") -> str:
    """Call the tool body directly, bypassing injection."""
    return read_todos.func(state, tool_call_id)


def _invoke_in_graph(todos, *, include_key: bool = True) -> AIMessage | object:
    """Run ``read_todos`` through a compiled graph and return the ToolMessage.

    ToolNode cannot be invoked on its own (it needs graph context), so this
    wires the smallest possible graph around it.
    """
    graph = StateGraph(State)
    graph.add_node("tool_node", ToolNode([read_todos]))
    graph.add_edge(START, "tool_node")
    graph.add_edge("tool_node", END)

    state = {
        "messages": [
            HumanMessage(content="what is on my list?"),
            AIMessage(
                content="",
                tool_calls=[{"name": "read_todos", "args": {}, "id": "call-1"}],
            ),
        ],
        "current_date": "Mon Jan 01, 2026",
        "skills_description": "Skills: none",
        "soul": None,
        "files": {},
    }
    if include_key:
        state["todos"] = [] if todos is None else todos
    elif todos is not None:  # caller explicitly wants the key omitted
        state["todos"] = todos

    result = graph.compile().invoke(state)
    return result["messages"][-1]


# ---------------------------------------------------------------------------
# Layer 1: formatting
# ---------------------------------------------------------------------------


def test_empty_list_returns_no_todos_message():
    assert _run({"todos": []}) == EMPTY_MESSAGE


def test_missing_todos_key_returns_no_todos_message():
    """A state without a `todos` key must not raise a KeyError."""
    assert _run({}) == EMPTY_MESSAGE


def test_none_todos_returns_no_todos_message():
    assert _run({"todos": None}) == EMPTY_MESSAGE


def test_renders_header_numbering_content_and_status():
    state = {
        "todos": [
            {"content": "Read the paper", "status": "completed"},
            {"content": "Summarise findings", "status": "in_progress"},
        ]
    }

    result = _run(state)

    assert result.splitlines()[0] == "Current TODO List:"
    assert "1. ✅ Read the paper (completed)" in result
    assert "2. 🔄 Summarise findings (in_progress)" in result


def test_numbering_starts_at_one_and_increments():
    """Three items must render as 1., 2., 3. - not 0-based."""
    state = {
        "todos": [
            {"content": f"Task {i}", "status": "pending"} for i in range(1, 4)
        ]
    }

    lines = _run(state).splitlines()[1:]

    assert [line.split(".")[0] for line in lines] == ["1", "2", "3"]


def test_pending_status_uses_hourglass_emoji():
    result = _run({"todos": [{"content": "Do it", "status": "pending"}]})

    assert "⏳ Do it (pending)" in result


def test_unknown_status_falls_back_to_question_mark():
    """An unexpected status must degrade gracefully, not raise KeyError."""
    result = _run({"todos": [{"content": "Odd one", "status": "archived"}]})

    assert "❓ Odd one (archived)" in result


def test_output_has_no_trailing_whitespace():
    result = _run({"todos": [{"content": "Task", "status": "pending"}]})

    assert result == result.strip()


def test_order_is_preserved():
    state = {
        "todos": [
            {"content": "First", "status": "pending"},
            {"content": "Second", "status": "completed"},
            {"content": "Third", "status": "in_progress"},
        ]
    }

    contents = [
        line.split(" ", 2)[2].rsplit(" (", 1)[0]
        for line in _run(state).splitlines()[1:]
    ]

    assert contents == ["First", "Second", "Third"]


# ---------------------------------------------------------------------------
# Layer 2: injected arguments must stay out of the model-facing schema
# ---------------------------------------------------------------------------


def test_state_and_tool_call_id_are_not_exposed_to_the_model():
    """The model legitimately calls this tool with `{}`."""
    exposed = set(read_todos.tool_call_schema.model_fields)

    assert "state" not in exposed
    assert "tool_call_id" not in exposed
    assert exposed == set()


def test_tool_advertises_no_arguments():
    assert read_todos.args == {}


def test_injected_parameters_are_declared_on_the_signature():
    """Guards against someone 'fixing' the empty schema by adding args."""
    assert {"state", "tool_call_id"} <= set(read_todos.get_input_schema().model_fields)


# ---------------------------------------------------------------------------
# Layer 3: the ToolNode path that originally failed
# ---------------------------------------------------------------------------


def test_tool_node_returns_success_for_populated_list():
    message = _invoke_in_graph([{"content": "Read the paper", "status": "pending"}])

    assert message.status == "success"
    assert "1. ⏳ Read the paper (pending)" in message.content


def test_tool_node_returns_success_for_empty_list():
    message = _invoke_in_graph([])

    assert message.status == "success"
    assert message.content == EMPTY_MESSAGE


def test_tool_node_returns_success_when_todos_key_is_absent():
    """The original bug also fired when the list did not exist yet."""
    message = _invoke_in_graph(None, include_key=False)

    assert message.status == "success"
    assert message.content == EMPTY_MESSAGE


def test_tool_node_never_returns_the_generic_error():
    """Regression guard for the reported symptom."""
    for todos in ([], None, [{"content": "Task", "status": "pending"}]):
        message = _invoke_in_graph(todos)

        assert message.status != "error", message.content
        assert FAILURE_TEXT not in message.content


def test_tool_node_replies_to_the_right_tool_call():
    message = _invoke_in_graph([])

    assert message.tool_call_id == "call-1"
    assert message.name == "read_todos"


# ---------------------------------------------------------------------------
# Layer 4: compiled graph with the real `State` schema
# ---------------------------------------------------------------------------


def test_works_with_full_state():
    """Complete state, as it looks after the first agent turn."""
    graph = StateGraph(State)
    graph.add_node("tool_node", ToolNode([read_todos]))
    graph.add_edge(START, "tool_node")
    graph.add_edge("tool_node", END)

    result = graph.compile().invoke(
        {
            "messages": [
                HumanMessage(content="show my todos"),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "read_todos", "args": {}, "id": "c-9"}],
                ),
            ],
            "todos": [{"content": "Ship it", "status": "in_progress"}],
            "files": {},
            "summary": None,
            "current_date": "Mon Jan 01, 2026",
            "skills_description": "Skills: none",
            "soul": None,
            "is_task_complete": False,
            "task_completion_reasoning": "",
            "pending_tasks_note": None,
            "incomplete_attempts": 0,
        }
    )

    message = result["messages"][-1]

    assert message.status == "success"
    assert "1. 🔄 Ship it (in_progress)" in message.content


def test_works_on_the_first_tool_round():
    """Minimal state: the completion-check keys do not exist yet.

    This is the scenario that used to fail, because `State` is a TypedDict and
    ``Optional[X] = None`` still marks those keys as required.
    """
    message = _invoke_in_graph([{"content": "Write the plan", "status": "pending"}])

    assert message.status == "success"
    assert "Write the plan" in message.content
