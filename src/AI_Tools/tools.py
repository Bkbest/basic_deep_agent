from langchain_core.tools import tool, InjectedToolCallId
from AI_State.state import Todo
from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from typing_extensions import Annotated, Literal
from AI_State.state import State
from langgraph.prebuilt.tool_node import InjectedState
from AI_Sys_Prompt.system_prompt_agent import (
    WRITE_TODOS_DESCRIPTION,
    LS_DESCRIPTION,
    READ_FILE_DESCRIPTION,
    WRITE_FILE_DESCRIPTION,
    INTERNET_SEARCH_DESCRIPTION,
    SUMMARIZE_WEB_SEARCH
)
from tavily import TavilyClient
import uuid, base64
import os
from dotenv import load_dotenv
from datetime import datetime
from AI_STRUCT_OUT.summary import Summary
from AI_LLM.agent_llm import MyLLM
import traceback
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

# Load environment variables
load_dotenv()




@tool(description=WRITE_TODOS_DESCRIPTION,parse_docstring=True)
def write_todos(
    todos: list[Todo], tool_call_id: Annotated[str, InjectedToolCallId]
) -> Command:
    """Create or update the agent's TODO list for task planning and tracking.

    Args:
        todos: List of Todo items with content and status
        tool_call_id: Tool call identifier for message response

    Returns:
        Command to update agent state with new TODO list
    """
    return Command(
        update={
            "todos": todos,
            "messages": [
                ToolMessage(f"Updated todo list to {todos}", tool_call_id=tool_call_id)
            ],
        }
    )
    
@tool(parse_docstring=True)
def read_todos(
    state: Annotated[State, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> str:
    """Read the current TODO list from the agent state.

    This tool allows the agent to retrieve and review the current TODO list
    to stay focused on remaining tasks and track progress through complex workflows.

    Args:
        state: Injected agent state containing the current TODO list
        tool_call_id: Injected tool call identifier for message tracking

    Returns:
        Formatted string representation of the current TODO list
    """
    todos = state.get("todos", [])
    if not todos:
        return "No todos currently in the list."

    result = "Current TODO List:\n"
    for i, todo in enumerate(todos, 1):
        status_emoji = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}
        emoji = status_emoji.get(todo["status"], "❓")
        result += f"{i}. {emoji} {todo['content']} ({todo['status']})\n"

    return result.strip()

@tool(description=LS_DESCRIPTION)
def ls(state: Annotated[State, InjectedState]) -> list[str]:
    """List all files in the virtual filesystem."""
    return list(state.get("files", {}).keys())

@tool(description=READ_FILE_DESCRIPTION, parse_docstring=True)
def read_file(
    file_path: str,
    state: Annotated[State, InjectedState],
    offset: int = 0,
    limit: int = 2000,
) -> str:
    """Read file content from virtual filesystem with optional offset and limit.

    Args:
        file_path: Path to the file to read
        state: Agent state containing virtual filesystem (injected in tool node)
        offset: Line number to start reading from (default: 0)
        limit: Maximum number of lines to read (default: 2000)

    Returns:
        Formatted file content with line numbers, or error message if file not found
    """
    files = state.get("files", {})
    if file_path not in files:
        return f"Error: File '{file_path}' not found"

    content = files[file_path]
    if not content:
        return "System reminder: File exists but has empty contents"

    lines = content.splitlines()
    start_idx = offset
    end_idx = min(start_idx + limit, len(lines))

    if start_idx >= len(lines):
        return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

    result_lines = []
    for i in range(start_idx, end_idx):
        line_content = lines[i][:2000]  # Truncate long lines
        result_lines.append(f"{i + 1:6d}\t{line_content}")

    return "\n".join(result_lines)

@tool(description=WRITE_FILE_DESCRIPTION, parse_docstring=True)
def write_file(
    file_path: str,
    content: str,
    state: Annotated[State, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Write content to a file in the virtual filesystem.

    Args:
        file_path: Path where the file should be created/updated
        content: Content to write to the file
        state: Agent state containing virtual filesystem (injected in tool node)
        tool_call_id: Tool call identifier for message response (injected in tool node)

    Returns:
        Command to update agent state with new file content
    """
    files = state.get("files", {})
    files[file_path] = content
    return Command(
        update={
            "files": files,
            "messages": [
                ToolMessage(f"Updated file {file_path}", tool_call_id=tool_call_id)
            ],
        }
    )
    
@tool(description="Get current date")
def get_current_date() -> str:
    """Get current date"""
    return datetime.now().strftime("%a %b %d, %Y")

def get_today_str() -> str:
    """Get current date"""
    return datetime.now().strftime("%a %b %d, %Y")
    
@tool(description=INTERNET_SEARCH_DESCRIPTION)
def internet_search(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    query: str,
    max_results:int,
    topic: Literal["general", "news", "finance"]
    
):
    """Search web and save detailed results to files while returning minimal context.

    Performs web search and saves full content to files for context offloading.
    Returns only essential information to help the agent decide on next steps.

    Args:
        query: Search query string
        max_results: Maximum number of results (default: 5, limit to save credits)
        topic: Type of search - "general", "news", or "finance"
    """
    try:
        print("hello")
        tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        
        search_results = tavily_client.search(
            query,
            max_results=max_results,
            include_raw_content=True,
            topic=topic,
        )
        files = state.get("files", {})
        saved_files = []
        summaries = []
        
        for result in search_results.get('results', []):
            try:
                # Process and summarize results
                content = result['raw_content']
                if not content:
                    continue
                processed_results = summarize_webpage_content(content)
                # uniquify file names
                uid = base64.urlsafe_b64encode(uuid.uuid4().bytes).rstrip(b"=").decode("ascii")[:8]
                name, ext = os.path.splitext(processed_results.filename)
                processed_results.filename = f"{name}_{uid}{ext}"
                file_content = f"""# Search Result: {result['title']}

**URL:** {result['url']}
**Query:** {query}

## Summary
{processed_results.summary}

## Raw Content
{result['raw_content'] if result['raw_content'] else 'No raw content available'}
"""

                files[processed_results.filename] = file_content
                saved_files.append(processed_results.filename)
                summaries.append(f"- {processed_results.filename}: {processed_results.summary}...")
                
            except Exception as e:
                print(f"Error processing search result: {e}")
                print("Full stacktrace:")
                traceback.print_exc()
                continue

        # Create minimal summary for tool message - focus on what was collected
        summary_text = f"""🔍 Found {len(saved_files)} result(s) for '{query}':
        
{chr(10).join(summaries)}

Files: {', '.join(saved_files)}
💡 Use read_file() to access full details when needed."""
        
        return Command(
            update={
                "files": files,
                "messages": [
                    ToolMessage(summary_text, tool_call_id=tool_call_id)
                ],
            }
        )
        
    except Exception as e:
        print(f"Error in internet_search: {e}")
        error_message = f"❌ Failed to search for '{query}': {str(e)}"
        return Command(
            update={
                "messages": [
                    ToolMessage(error_message, tool_call_id=tool_call_id)
                ],
            }
        )


def summarize_webpage_content(webpage_content: str) -> Summary:
    """Summarize webpage content using the configured summarization model.

    Args:
        webpage_content: Raw webpage content to summarize

    Returns:
        Summary object with filename and summary
    """
    try:
        llm_factory = MyLLM(temperature=0.7,tools=[],model="gpt-oss:120b-cloud")
        llm_web_search = llm_factory.llm_without_tools()
        llm_for_web_search = llm_web_search.with_structured_output(Summary)
        # Generate summary
        content=SUMMARIZE_WEB_SEARCH.format(
                webpage_content=webpage_content, 
                date=get_today_str()
        )
        summary_and_filename = llm_for_web_search.invoke([
            HumanMessage(content)
        ])
        return summary_and_filename

    except Exception as e:
        print(f"Error in summarize_webpage_content: {e}")
        print("Full stacktrace:")
        traceback.print_exc()
        # Return a basic summary object on failure
        return Summary(
            filename="search_result.md",
            summary=str(e)
        )

@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps systematically.
    This creates a deliberate pause in the research workflow for quality decision-making.

    When to use:
    - After receiving search results: What key information did I find?
    - Before deciding next steps: Do I have enough to answer comprehensively?
    - When assessing research gaps: What specific information am I still missing?
    - Before concluding research: Can I provide a complete answer now?
    - How complex is the question: Have I reached the number of search limits?

    Reflection should address:
    1. Analysis of current findings - What concrete information have I gathered?
    2. Gap assessment - What crucial information is still missing?
    3. Quality evaluation - Do I have sufficient evidence/examples for a good answer?
    4. Strategic decision - Should I continue searching or provide my answer?

    Args:
        reflection: Your detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"

class MyTools:
    async def getAllTools(self):
        client = MultiServerMCPClient(
            {
                "pandora_sandbox": {
                    "transport": "streamable_http",
                    "url": os.getenv("SANDBOX_URL"),
                }
            }
        )
        sandbox_tools = await client.get_tools()
        return [write_todos, read_todos, ls, read_file, internet_search,think_tool,get_current_date] + sandbox_tools
    
    def getToolsSync(self):
        """Synchronous wrapper for getAllTools"""
        import asyncio
        return asyncio.run(self.getAllTools())
    
