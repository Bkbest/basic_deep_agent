from langchain_core.messages import SystemMessage,AIMessage,HumanMessage
from langchain_core.prompts import PromptTemplate,ChatPromptTemplate
from AI_State.state import State
from AI_Tools.tools import MyTools
from AI_Sys_Prompt.system_prompt_agent import AGENT_DESCRIPTION
from AI_LLM.agent_llm import MyLLM
from langgraph.graph import END
from langmem.short_term import asummarize_messages, summarize_messages
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
        ("user", "Create a summary of the conversation above. If a sandbox was created during the conversation,you must include sandbox id in the summary and mention not to create a new sandbox."),
    ]
)


DEFAULT_EXISTING_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("placeholder", "{messages}"),
        (
            "user",
            "This is summary of the conversation so far: {existing_summary}\n\n"
            "Extend this summary by taking into account the new messages above. If a sandbox ID was created during the conversation summary and history,you must include sandbox id(s) in the summary and mention not to create a new sandbox.",
        ),
    ]
)

TASK_COMPLETION_PROMPT = """You are auditing whether an AI agent has finished the user's task.

Decide if the task is COMPLETE. Use both the TODO list and the conversation to judge.

Rules:
- COMPLETE only when every TODO item is marked "completed" AND the agent has delivered a concrete final answer to the user.
- INCOMPLETE if any TODO is "pending" or "in_progress".
- INCOMPLETE if the agent is still gathering information or has only described what it plans to do.
- INCOMPLETE if the agent asked the user a clarifying question, because work cannot proceed without the answer.
- COMPLETE if the agent delivered a final answer and stated it is done or blocked and cannot continue without the user, and nothing remains that it can do on its own.
- If there is no TODO list, judge from the conversation alone: has the user's request been fully answered?
- Every list starts with two standing items: "Create a detailed list of pending tasks" and "Recheck that the answer reached the user...". Both count like any other TODO and must be "completed" before the task is complete.

## TODO list
{todos}

## Conversation
{messages}

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


def _format_conversation(messages, limit: int = 12) -> str:
    """Render the tail of the conversation for the completion prompt."""
    lines = []
    for msg in messages[-limit:]:
        msg_type = getattr(msg, "type", None) or (
            msg.get("type") if isinstance(msg, dict) else None
        ) or "unknown"
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content", "")

        tool_calls = getattr(msg, "tool_calls", None) or (
            msg.get("tool_calls") if isinstance(msg, dict) else None
        ) or []

        # Tool-call-only AI messages have empty content but are still meaningful
        if not content and not tool_calls:
            continue
        if not isinstance(content, str):
            content = str(content)

        line = f"{msg_type}: {content.strip()}"
        if tool_calls:
            names = [
                tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
                for tc in tool_calls
            ]
            line += f" (requested tools: {', '.join(names)})"
        lines.append(line)

    return "\n\n".join(lines) if lines else "No conversation content available."


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
    The LLM is given the TODO list and the recent conversation and returns a
    structured Yes/No verdict.

    Returns:
        Dict containing the `is_task_complete` flag and its reasoning.
    """
    messages = state.get("messages", [])
    todos = state.get("todos", [])

    prompt = TASK_COMPLETION_PROMPT.format(
        todos=_format_todos(todos),
        messages=_format_conversation(messages),
    )

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

    system_message = [SystemMessage(content=system_content)]
    
    #add systemmessage to the beginning of the messages to be summarized so that it is included in the summary.
    state["messages"] = system_message + state["messages"]
    
    summarization_result = await asummarize_messages(
        state["messages"],
        running_summary=state.get("summary"),
        model=llm,
        max_tokens=230000,
        max_tokens_before_summary=110000,
        max_summary_tokens=10000,
        initial_summary_prompt=DEFAULT_INITIAL_SUMMARY_PROMPT,
        existing_summary_prompt=DEFAULT_EXISTING_SUMMARY_PROMPT,
    )
    messags_after_summarization = summarization_result.messages
    
    # If there are exactly two system messages after summarization, convert the second one to an AIMessage
    system_message_indices = [i for i, msg in enumerate(messags_after_summarization) if isinstance(msg, SystemMessage)]
    if len(system_message_indices) == 2:
        print(system_message_indices)
        second_system_idx = system_message_indices[1]
        messags_after_summarization[second_system_idx] = AIMessage(content=messags_after_summarization[second_system_idx].content)
        # Insert a HumanMessage after the second system message using the first message from state
        human_msg = HumanMessage(content="Look at the summary and the conversation below and decide what to do next.")
        messags_after_summarization.insert(second_system_idx, human_msg)
        print(messags_after_summarization)
    response = await llm_tools.ainvoke(messags_after_summarization)
    state_update = {"messages": [response]}
    if summarization_result.running_summary:
        state_update["summary"] = summarization_result.running_summary
    
    # Return the response as a message
    return state_update
