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
        return {
            "is_task_complete": False,
            "task_completion_reasoning": f"Completion check error: {e}",
        }

    is_complete = bool(verdict.is_complete)
    print(f"Task complete: {is_complete} — {verdict.reasoning}")

    return {
        "is_task_complete": is_complete,
        "task_completion_reasoning": verdict.reasoning,
    }


def route_after_completion_check(state: State):
    """Route to END when the task is complete, otherwise keep working."""
    if state.get("is_task_complete"):
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
    system_message = [SystemMessage(content=prompt.format(current_date=state["current_date"], skills_description=state["skills_description"], soul=state["soul"]))]
    
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
