from langchain_core.tools import tool, InjectedToolCallId
from AI_State.state import Todo
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from typing_extensions import Annotated
from AI_State.state import State
from langgraph.prebuilt import InjectedState

WRITE_TODOS_DESCRIPTION =""" Create and manage structured task lists for tracking progress through complex workflows.                       
                                                                                                               
 ## When to Use                                                                                                
 - Multi-step or non-trivial tasks requiring coordination                                                      
 - When user provides multiple tasks or explicitly requests todo list                                          
 - Avoid for single, trivial actions                                                                           
                                                                                                               
 ## Structure                                                                                                  
 - Maintain one list containing multiple todo objects (content, status, id)                                    
 - Use clear, actionable content descriptions                                                                  
 - Status must be: pending, in_progress, or completed                                                          
                                                                                                               
 ## Best Practices                                                                                             
 - Only one in_progress task at a time                                                                         
 - Mark completed immediately when task is fully done                                                          
 - Always send the full updated list when making changes                                                       
 - Prune irrelevant items to keep list focused                                                                 
                                                                                                               
 ## Progress Updates                                                                                           
 - Call TodoWrite again to change task status or edit content                                                  
 - Reflect real-time progress; don't batch completions                                                         
 - If blocked, keep in_progress and add new task describing blocker                                            
                                                                                                               
 ## Parameters                                                                                                 
 - todos: List of TODO items with content and status fields                                                    
                                                                                                               
 ## Returns                                                                                                    
 Updates agent state with new todo list.  """

LS_DESCRIPTION = """  List all files in the virtual filesystem stored in agent state.                             
                                                                                                                
 Shows what files currently exist in agent memory. Use this to orient yourself before other file operations     
 and maintain awareness of your file organization.                                                              
                                                                                                                
 No parameters required - simply call ls() to see all available files.  """
 
READ_FILE_DESCRIPTION = """ Read content from a file in the virtual filesystem with optional pagination.         
                                                                                                                 
 This tool returns file content with line numbers (like `cat -n`) and supports reading large files in chunks    
 to avoid context overflow.                                                                                     
                                                                                                                 
 Parameters:                                                                                                    
  - file_path (required): Path to the file you want to read                                                      
  - offset (optional, default=0): Line number to start reading from                                              
  - limit (optional, default=2000): Maximum number of lines to read                                              
                                                                                                                 
 Essential before making any edits to understand existing content. Always read a file before editing it."""
 
WRITE_FILE_DESCRIPTION = """  Create a new file or completely overwrite an existing file in the virtual filesystem.                          
                                                                                                                 
  This tool creates new files or replaces entire file contents. Use for initial file creation or complete        
  rewrites. Files are stored persistently in agent state.                                                        
                                                                                                                 
  Parameters:                                                                                                    
  - file_path (required): Path where the file should be created/overwritten                                      
  - content (required): The complete content to write to the file                                                
                                                                                                                 
  Important: This replaces the entire file content. Use edit_file for partial modifications.  """


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

# Mock search result
search_result = """The Model Context Protocol (MCP) is an open standard protocol developed 
by Anthropic to enable seamless integration between AI models and external systems like 
tools, databases, and other services. It acts as a standardized communication layer, 
allowing AI models to access and utilize data from various sources in a consistent and 
efficient manner. Essentially, MCP simplifies the process of connecting AI assistants 
to external services by providing a unified language for data exchange. """


# Mock search tool
@tool(parse_docstring=True)
def web_search(
    query: str,
):
    """Search the web for information on a specific topic.

    This tool performs web searches and returns relevant results
    for the given query. Use this when you need to gather information from
    the internet about any topic.

    Args:
        query: The search query string. Be specific and clear about what
               information you're looking for.

    Returns:
        Search results from search engine.

    Example:
        web_search("machine learning applications in healthcare")
    """
    return search_result

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

class MyTools:
    def getAllTools(self):
        return [write_todos, read_todos, web_search, ls, read_file]    
    
