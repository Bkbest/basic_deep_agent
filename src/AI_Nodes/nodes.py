from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import PromptTemplate,ChatPromptTemplate
from AI_State.state import State
from AI_Tools.tools import MyTools
from AI_Sys_Prompt.system_prompt_agent import AGENT_DESCRIPTION
from AI_LLM.agent_llm import MyLLM
from langgraph.graph import END
from langmem.short_term import RunningSummary, asummarize_messages
from langgraph.runtime import Runtime
import asyncio


tools=MyTools().getToolsSync()
llm_factory = MyLLM(temperature=0.7,tools=tools)
llm = llm_factory.llm_without_tools()
llm_tools = llm_factory.llm_with_tools()
llm_task_completion = llm_factory.llm_for_task_completion()

DEFAULT_INITIAL_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("placeholder", "{messages}"),
        (
            "user",
            "Create a summary of the conversation above. If a sandbox was created "
            "during the conversation, you must include the sandbox id in the summary "
            "and mention not to create a new sandbox.\n\n"
            "Reply with plain prose only. Do not call any tools.",
        ),
    ]
)


DEFAULT_EXISTING_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("placeholder", "{messages}"),
        (
            "user",
            "This is summary of the conversation so far: {existing_summary}\n\n"
            "Extend this summary by taking into account the new messages above. If a "
            "sandbox ID was created during the conversation summary and history, you "
            "must include sandbox id(s) in the summary and mention not to create a new "
            "sandbox.\n\n"
            "Reply with plain prose only. Do not call any tools.",
        ),
    ]
)

# langmem's default `final_prompt` re-injects the system message and decides
# whether to keep it with:
#
#     existing_summary.summary in existing_system_message.content
#
# When the summarization model returns an empty string (which happens when it
# answers with tool calls instead of prose, because the history it is reading is
# full of tool-call messages), `"" in <anything>` is True, so the agent's system
# prompt is dropped and the conversation collapses to a lone
# "Summary of the conversation so far:" message.
#
# Returning only the retained messages keeps that branch out of our path
# entirely. We own the system message and append the summary to it ourselves.
MESSAGES_ONLY_FINAL_PROMPT = ChatPromptTemplate.from_messages(
    [("placeholder", "{messages}")]
)

TASK_COMPLETION_PROMPT = """You are auditing whether an AI agent has finished the user's task.

Decide if the task is COMPLETE by looking only at the TODO list.

Rules:
- COMPLETE only when every TODO item is marked "completed".
- INCOMPLETE if any TODO is "pending" or "in_progress".
- INCOMPLETE if there is no TODO list, because progress cannot be verified.
- Every list starts with two standing items: "Create a detailed list of pending tasks" and "Recheck that the answer reached the user...". Both count like any other TODO and must be "completed" before the task is complete.

## TODO list
{todos}

Answer by calling the schema: set `is_complete` to true or false, and put your justification in `reasoning`."""


def _format_todos(todos) -> str:
    """Render the TODO list for the completion prompt."""
    if not todos:
        return "No TODO list was created."
    lines = []
    for i, todo in enumerate(todos, 1):
        if isinstance(todo, dict):
            content = todo.get("content", "")
            status = todo.get("status", "unknown")
        else:
            content = getattr(todo, "content", str(todo))
            status = getattr(todo, "status", "unknown")
        lines.append(f"{i}. [{status}] {content}")
    return "\n".join(lines)


# Two standing todos that must lead the list at the start of every human turn.
STANDING_TODOS = (
    "Create a detailed list of pending tasks",
    "Recheck that the answer reached the user the way they asked for it "
    "(calendar reminder, shared link, or just in chat)",
)


def _seed_standing_todos(todos) -> list:
    """Put the standing todos at the front of the list, reset to pending.

    ``write_todos`` replaces the whole list, so this is re-applied at the start
    of each human turn rather than relying on the agent to preserve them.

    Args:
        todos: Existing todo list (list of dicts) or None.

    Returns:
        list: The standing todos first (status "pending"), then the agent's own.
    """
    todos = [dict(todo) for todo in (todos or [])]
    rest = [todo for todo in todos if todo.get("content") not in STANDING_TODOS]
    return [{"content": content, "status": "pending"} for content in STANDING_TODOS] + rest


async def seed_standing_todos(state: State):
    """Ensure the two standing todos lead the list at the start of a turn."""
    return {"todos": _seed_standing_todos(state.get("todos"))}


def _pending_todos(todos) -> list:
    """Return the todos that are not yet completed, formatted for display."""
    pending = []
    for todo in todos or []:
        if isinstance(todo, dict):
            content = todo.get("content", "")
            status = todo.get("status", "unknown")
        else:
            content = getattr(todo, "content", str(todo))
            status = getattr(todo, "status", "unknown")
        if status != "completed":
            pending.append(f"{content} ({status})")
    return pending


def _pending_todos_message(pending: list, reasoning: str = "") -> str:
    """Build the AI message describing why work continues.

    The completion check's reasoning is already a natural-language explanation
    of what is still outstanding, so it becomes the message body. The formatted
    todo list is kept only as a fallback for when no reasoning is available
    (for example, when the check itself failed).

    Args:
        pending: Outstanding todo items, already formatted.
        reasoning: The model's justification for the "not complete" verdict.

    Returns:
        str: Message content for the state update.
    """
    reasoning = (reasoning or "").strip()
    if reasoning:
        return reasoning

    items = "\n".join(f"- {item}" for item in pending)
    return (
        f"I still have {len(pending)} task(s) pending:\n{items}\n"
        "I'll continue working on them."
    )


# Cap on consecutive "not complete" verdicts before the run is forced to end.
MAX_INCOMPLETE_ATTEMPTS = 3


def _completion_update(
    todos, is_complete: bool, reasoning: str, use_reasoning: bool = True
) -> dict:
    """Build the state update returned by the completion check.

    Outstanding work is recorded in `pending_tasks_note` rather than
    `messages`. Putting it in `messages` made the check read its own note back
    and verdict "incomplete" forever.

    Args:
        todos: Current todo list.
        is_complete: Verdict from the LLM.
        reasoning: Model's justification for the verdict.
        use_reasoning: When False, fall back to listing the pending todos
            (used when `reasoning` is an internal error, not a real verdict).

    Returns:
        dict: State update for the graph.
    """
    update = {
        "is_task_complete": is_complete,
        "task_completion_reasoning": reasoning,
    }

    if is_complete:
        update["pending_tasks_note"] = None
        return update

    pending = _pending_todos(todos)
    if pending:
        update["pending_tasks_note"] = _pending_todos_message(
            pending, reasoning if use_reasoning else ""
        )

    return update


async def is_tool_required(state: State):
    """Route to the tool node when the model asked for tools.

    Otherwise, verify completion with the LLM instead of ending immediately.
    """
    messages = state["messages"]
    lastMessage = messages[-1]

    if hasattr(lastMessage, "tool_calls") and lastMessage.tool_calls:
        return "tool_node"
    else:
        # No tool call does not mean the task is finished -- verify with the LLM.
        print("Tool not required, checking if task is complete")
        return "llm_is_task_complete"


async def llm_is_task_complete(state: State):
    """
    Ask the LLM whether the user's task is actually finished.

    Reaching this node means the model returned no tool calls, which does not
    by itself prove the task is done -- the agent may have stopped mid-plan.
    Only the TODO list is consulted: the model's own prose is not evidence that
    the work is finished, and judging from it let the agent talk its way to
    "complete" while items were still open.

    Returns:
        Dict containing the `is_task_complete` flag and its reasoning.
    """
    todos = state.get("todos", [])

    prompt = TASK_COMPLETION_PROMPT.format(todos=_format_todos(todos))

    try:
        verdict = await llm_task_completion.ainvoke(prompt)
    except Exception as e:
        # Fail closed: an unreadable verdict must not silently end the run.
        print(f"⚠️  Task completion check failed ({e}); continuing the loop")
        return _completion_update(
            todos,
            is_complete=False,
            reasoning=f"Completion check error: {e}",
            use_reasoning=False,
        )

    is_complete = bool(verdict.is_complete)
    print(f"Task complete: {is_complete} — {verdict.reasoning}")

    update = _completion_update(todos, is_complete, verdict.reasoning)
    # Count consecutive incomplete verdicts so the router can cap the loop.
    previous = state.get("incomplete_attempts") or 0
    update["incomplete_attempts"] = 0 if is_complete else previous + 1

    return update


def route_after_completion_check(state: State):
    """Route to END when the task is complete, otherwise keep working.

    The loop is capped: after MAX_INCOMPLETE_ATTEMPTS consecutive "not
    complete" verdicts the run ends instead of burning the recursion limit.
    """
    if state.get("is_task_complete"):
        return END

    if (state.get("incomplete_attempts") or 0) >= MAX_INCOMPLETE_ATTEMPTS:
        print(
            f"⚠️  Task still incomplete after {MAX_INCOMPLETE_ATTEMPTS} attempts; "
            "ending the run"
        )
        return END

    return "llm_with_tools"


def _summary_text(summary) -> str:
    """Return the summary's text, or "" when there is nothing usable.

    A summarization model can answer with tool calls instead of prose, which
    leaves `AIMessage.content` empty. That empty string is dangerous downstream,
    so it is normalised to "" here and treated as "no summary".
    """
    if summary is None:
        return ""
    text = getattr(summary, "summary", summary)
    if text is None:
        return ""
    return str(text).strip()


# Used when a request's retained history no longer begins with a human turn and a
# summary is available. A system-prompt-only request, or one that starts with an
# assistant turn, makes some models (Ollama in particular) return empty content.
SUMMARY_ONLY_USER_MESSAGE = (
    "Continue the task. The summary of the conversation so far is in the "
    "system prompt above."
)

# Same purpose as above, but for when no summary could be produced either, so
# pointing at one would be a lie.
CONTINUATION_USER_MESSAGE = (
    "Continue the task from where it was left off. Pick the next step and keep "
    "working until every todo item is completed."
)

# Stable id so the synthetic turn is recognisable in logs and can be matched
# exactly. It is never written to `state["messages"]`, so it cannot collide with
# a real message or get pulled into a later summarization round.
CONTINUATION_MESSAGE_ID = "synthetic-continuation-turn"


def _sanitize_conversation(messages: list) -> list:
    """Drop leading `ToolMessage`s from a message list.

    langmem keeps the tail as `messages[total_summarized_messages:]`. When the
    summarization cutoff lands on an `AIMessage` carrying tool calls, its
    matching `ToolMessage`s are appended to the summarized slice, so the tail can
    begin with a tool result whose parent assistant turn is gone. Providers
    reject that shape, and Ollama answers it with empty content.

    Only leading tool messages are removed; nothing else is filtered or
    reordered.

    Args:
        messages: Messages to sanitize. Not mutated.

    Returns:
        list: A new list with leading tool messages removed.
    """
    if not messages:
        return []
    start = 0
    while start < len(messages) and isinstance(messages[start], ToolMessage):
        start += 1
    if start:
        print(f"Ignoring {start} orphaned tool message(s) at the start of the conversation")
    return list(messages[start:])


def _has_conversation(messages: list) -> bool:
    """True when `messages` holds at least one non-system message."""
    return any(not isinstance(m, SystemMessage) for m in messages or [])


def _needs_leading_user_turn(messages: list) -> bool:
    """True when `messages` does not already begin with a human turn.

    Providers accept a conversation that starts with a user turn. An
    assistant-first history (the kept tail after a summarization cutoff landed on
    an assistant message) or a tool-first history (cutoff landed on an assistant
    turn that carried tool calls) is rejected or answered with empty content by
    some models, Ollama in particular.

    Args:
        messages: Messages about to be sent (system message excluded or not).

    Returns:
        bool: True when a synthetic leading user turn has to be prepended.
    """
    for message in messages or []:
        if isinstance(message, SystemMessage):
            continue
        return not isinstance(message, HumanMessage)
    return True


def _continuation_human_message(has_summary: bool) -> HumanMessage:
    """Build the synthetic user turn that fronts a summarized request.

    Never written to state: it exists only so the request starts with a human
    turn. It is rebuilt on every call, which is what keeps the invariant true
    even though the previous turn's copy was never persisted.

    Args:
        has_summary: True when a usable summary is already in the system prompt.

    Returns:
        HumanMessage: The continuation turn.
    """
    content = SUMMARY_ONLY_USER_MESSAGE if has_summary else CONTINUATION_USER_MESSAGE
    return HumanMessage(content=content, id=CONTINUATION_MESSAGE_ID)


def _ensure_leading_user_turn(kept: list, summary, original_messages: list) -> list:
    """Guarantee that the messages sent to the model start with a human turn.

    Called on every request, not just the first one after a summarization. The
    earlier version only handled the case where the kept tail was completely
    empty, so the very next turn -- whose tail is just the previous assistant
    reply -- went out as system + assistant and the model answered with empty
    content.

    Args:
        kept: Retained messages after summarization, already sanitized.
        summary: The running summary that will accompany the request, or None.
        original_messages: The full conversation, used as a fallback when both
            the retained tail and the summary are gone.

    Returns:
        list: Messages that begin with a human turn (unless nothing at all is
        available to send).
    """
    if not _has_conversation(kept):
        if _summary_text(summary):
            print(
                "⚠️  Summarization left no conversation; "
                "continuing from the summary alone"
            )
            return [_continuation_human_message(has_summary=True)]

        # Both the conversation and the summary are gone, so replaying the
        # history is the only way to avoid an empty turn.
        print(
            "⚠️  Summarization left no conversation and no summary; "
            "falling back to the full history"
        )
        kept = _sanitize_conversation(original_messages)
        if not kept:
            return []

    if _needs_leading_user_turn(kept):
        print(
            "⚠️  Retained history does not start with a user turn; "
            "prepending a continuation message"
        )
        return [
            _continuation_human_message(has_summary=bool(_summary_text(summary)))
        ] + list(kept)

    return kept


def _is_empty_response(message) -> bool:
    """True when a model reply carries neither text nor tool calls.

    Some providers (Ollama in particular) answer with empty content. Storing
    such a reply adds a blank assistant turn to the history that every later
    call replays, so it is dropped instead.

    A reply with tool calls counts as non-empty even when its content is "",
    because the tool calls are what the graph routes on next.

    Args:
        message: The `AIMessage` returned by the model, or None.

    Returns:
        bool: True when there is nothing worth persisting.
    """
    if message is None:
        return True
    if getattr(message, "tool_calls", None):
        return False
    content = getattr(message, "content", "")
    if isinstance(content, list):
        # Content-block replies: keep only the text blocks.
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return not str(content).strip()


async def _summarize(messages, running_summary):
    """Summarize `messages` without ever leaving the model an empty conversation.

    Two langmem behaviours have to be guarded here:

    1. **Empty summary.** It records whatever the model returned, including "".
       An empty summary poisons `state["summary"]`, and langmem's default
       `final_prompt` then deletes the agent's system prompt because
       `"" in <anything>` is True. `MESSAGES_ONLY_FINAL_PROMPT` keeps that
       branch out of the path, and empty summaries are rejected outright.

    2. **A retained tail that does not start with a user turn.** The kept tail
       is `messages[total_summarized_messages:]`, which is empty when the cutoff
       consumed every message. Because the cutoff is the first message where the
       running total reaches `max_tokens_before_summary` *and* the remainder
       fits the `max_tokens - max_summary_tokens` budget, and because that
       budget check is trivially satisfied near the end of the list, the
       retained tail can be empty, hold only orphaned tool results, or start at
       an assistant reply. A request with nothing but a system message -- or one
       that begins with an assistant turn -- makes Ollama return empty content,
       and Ollama answering with empty content is what tripped the
       completion-check cap.

    The tail is recomputed from `state["messages"]` on every call, so a
    synthetic user turn is prepended on demand rather than stored: the message
    added for one request is gone from state by the next one.

    Args:
        messages: Conversation messages, without the agent's system prompt.
        running_summary: The `RunningSummary` from state, or None.

    Returns:
        tuple[list, RunningSummary | None]: Messages for the LLM (non-empty
        whenever `messages` was non-empty) and the summary to persist.
    """
    try:
        result = await asummarize_messages(
            messages,
            running_summary=running_summary,
            model=llm,
            max_tokens=530000,
            max_tokens_before_summary=460000,
            max_summary_tokens=100000,
            initial_summary_prompt=DEFAULT_INITIAL_SUMMARY_PROMPT,
            existing_summary_prompt=DEFAULT_EXISTING_SUMMARY_PROMPT,
            final_prompt=MESSAGES_ONLY_FINAL_PROMPT,
        )
    except Exception as e:
        # Summarization must never break the turn; fall back to the full history.
        # The leading-user-turn invariant still applies: a resumed thread whose
        # history starts at an assistant reply would otherwise go out as-is.
        print(f"⚠️  Summarization failed ({e}); continuing with full history")
        fallback = _ensure_leading_user_turn(
            _sanitize_conversation(messages), running_summary, messages
        )
        return fallback, running_summary

    new_summary = result.running_summary
    kept = _sanitize_conversation(result.messages)

    # Guard 1: reject an empty summary so it can never poison state.
    if new_summary is not None and not _summary_text(new_summary):
        print(
            "⚠️  Summarization returned no text (likely a tool call instead of prose); "
            "keeping the previous summary"
        )
        new_summary = running_summary

    # Guard 2: never call the model with a conversation that does not start
    # with a user turn (including the extreme case of no conversation at all).
    kept = _ensure_leading_user_turn(kept, new_summary, messages)

    return kept, new_summary


async def llm_with_tools(state: State, runtime: Runtime):
    """
    Processes messages using LLM with tools when required.
    
    Args:
        state: Current state containing messages and tool requirement
        
    Returns:
        Dict containing updated messages
    """
    info = runtime.execution_info
    if info.node_attempt > 1:
        print("sleeping for 60 seconds before retrying.")
        await asyncio.sleep(60)     
    # Create the prompt template with system prompt and messages
    agent_description = AGENT_DESCRIPTION
    prompt = PromptTemplate.from_template(agent_description)
    system_content = prompt.format(current_date=state["current_date"], skills_description=state["skills_description"], soul=state["soul"])

    # Surface outstanding work from the completion check. This lives in state
    # (not `messages`) so the check does not read its own note back.
    pending_note = state.get("pending_tasks_note")
    if pending_note:
        system_content += (
            "\n\n## Outstanding Work (from your last progress check)\n"
            f"{pending_note}\n"
        )

    # Summarization only ever sees the conversation. The system prompt is added
    # afterwards, exactly once, so it cannot be summarized away or dropped by
    # langmem's own system-message handling.
    messages_after_summarization, summary = await _summarize(
        list(state["messages"]), state.get("summary")
    )

    summary_text = _summary_text(summary)
    if summary_text:
        system_content += (
            "\n\n## Conversation summary so far\n"
            f"{summary_text}\n"
        )

    messages_for_llm = [SystemMessage(content=system_content)] + messages_after_summarization

    response = await llm_tools.ainvoke(messages_for_llm)

    state_update = {}
    if _is_empty_response(response):
        # Keep blank replies out of the history; replaying them only makes the
        # next turn emptier.
        print("⚠️  LLM returned an empty response; not adding it to the state")
    else:
        state_update["messages"] = [response]

    if summary is not None:
        state_update["summary"] = summary

    # Return the response as a message
    return state_update
