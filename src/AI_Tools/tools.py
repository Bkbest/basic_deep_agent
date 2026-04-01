from langchain_core.tools import tool, InjectedToolCallId
from AI_State.state import Todo
from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from typing_extensions import Annotated, Literal,Union
from AI_State.state import State
from langgraph.prebuilt.tool_node import InjectedState
from AI_Sys_Prompt.system_prompt_agent import (
    WRITE_TODOS_DESCRIPTION,
    INTERNET_SEARCH_DESCRIPTION,
)
from tavily import TavilyClient
import os
from dotenv import load_dotenv
from datetime import datetime
from AI_STRUCT_OUT.summary import Summary
import asyncpg
from AI_LLM.agent_llm import MyLLM
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

@tool(description="List all skills stored in the database, returns list of {skill_name, skill_description}.", parse_docstring=True)
async def list_skills() -> list[dict]:
    """List all skills from the 'skills' database table.

    Returns:
        List of dictionaries containing 'skill_name' and 'skill_description'.
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING not set")

    try:
        conn = await asyncpg.connect(connection_string)
        try:
            rows = await conn.fetch("SELECT skill_name, skill_description FROM skills")
            if not rows:
                return []
            return [
                {"skill_name": row["skill_name"], "skill_description": row["skill_description"]}
                for row in rows
            ]
        finally:
            await conn.close()
    except Exception as e:
        raise RuntimeError(f"Failed to list skills: {e}")

@tool(description="Read the skill text for a given skill_name from the skills table.", parse_docstring=True)
async def read_skill(skill_name: str) -> str:
    """Read a single skill from the 'skills' database table.

    Args:
        skill_name: The key name of the skill to read.

    Returns:
        The 'skill' text or an error message if not found.
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING not set")

    try:
        conn = await asyncpg.connect(connection_string)
        try:
            row = await conn.fetchrow(
                "SELECT skill FROM skills WHERE skill_name = $1",
                skill_name,
            )
            if not row:
                return f"Skill '{skill_name}' not found"
            return row["skill"]
        finally:
            await conn.close()
    except Exception as e:
        raise RuntimeError(f"Failed to read skill '{skill_name}': {e}")

@tool(description="Save a skill to the database. If the skill exists, it will be updated; otherwise, a new skill will be inserted.", parse_docstring=True)
async def save_skill(
    skill_name: str,
    skill: str,
    skill_description: str,
) -> str:
    """Save (insert or update) a skill in the 'skills' database table.

    This tool will insert a new skill if it doesn't exist, or update it if it already exists.

    Args:
        skill_name: The unique key name of the skill.
        skill: The skill text content.
        skill_description: The description of the skill.

    Returns:
        A confirmation message indicating whether the skill was inserted or updated.
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING not set")

    try:
        conn = await asyncpg.connect(connection_string)
        try:
            # Check if skill already exists
            row = await conn.fetchrow(
                "SELECT skill_name FROM skills WHERE skill_name = $1",
                skill_name,
            )
            if row:
                # Update existing skill
                await conn.execute(
                    """
                    UPDATE skills
                    SET skill = $2, skill_description = $3
                    WHERE skill_name = $1
                    """,
                    skill_name,
                    skill,
                    skill_description,
                )
                return f"Skill '{skill_name}' updated successfully"
            else:
                # Insert new skill
                await conn.execute(
                    """
                    INSERT INTO skills (skill_name, skill, skill_description)
                    VALUES ($1, $2, $3)
                    """,
                    skill_name,
                    skill,
                    skill_description,
                )
                return f"Skill '{skill_name}' inserted successfully"
        finally:
            await conn.close()
    except Exception as e:
        raise RuntimeError(f"Failed to save skill '{skill_name}': {e}")   

def get_today_str() -> str:
    """Get current date"""
    return datetime.now().strftime("%a %b %d, %Y")
    
@tool(description=INTERNET_SEARCH_DESCRIPTION)
def internet_search(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    query: str,
    max_results:int,
    topic: Literal["general", "news", "finance"],
    include_raw_content: bool = False,
    
):
    try:
        tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        return tavily_client.search(
            query,
            max_results=max_results,
            include_raw_content=include_raw_content,
            topic=topic,
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
        mcp_tools = await client.get_tools()
        return [write_todos,read_todos,think_tool,internet_search,list_skills,read_skill,save_skill] + mcp_tools
    
    def getToolsSync(self):
        """Synchronous wrapper for getAllTools"""
        import asyncio
        return asyncio.run(self.getAllTools())

