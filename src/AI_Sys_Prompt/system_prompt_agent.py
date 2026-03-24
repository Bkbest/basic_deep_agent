"""Prompt templates and tool descriptions for deep agents from scratch.

This module contains all the system prompts, tool descriptions, and instruction
templates used throughout the deep agents educational framework.
"""

INTERNET_SEARCH_DESCRIPTION = """Search the web using Tavily for current information and documentation.

    This tool searches the web and returns relevant results. 
    Args:
        query: The search query (be specific and detailed)
        max_results: Number of results to return (default: 5)
        topic: Search topic type - "general" for most queries, "news" for current events
        include_raw_content: Include full page content (warning: uses more tokens)

    Returns:
        Dictionary containing:
        - results: List of search results, each with:
            - title: Page title
            - url: Page URL
            - content: Relevant excerpt from the page
            - score: Relevance score (0-1)
        - query: The original search query
    """

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
  
EDIT_DESCRIPTION = """Performs exact string replacements in files. 

Usage:
- You must use your `Read` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file. 
- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`. 
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance."""
    
AGENT_DESCRIPTION = """You are an AI assistant designed to answer user questions, which may require web searches.

Your primary goal is to provide a direct and comprehensive answer to the user. To do this effectively, you must follow a structured internal process. This process, including your task list, is for your internal use only and should not be shared with the user.

It is mandatory to use the `write_todos` and `read_todos` tools to manage your internal task list for every user request.

**Your Internal Workflow:**

Based upon the user's request:                                                                                
  1. Use the write_todos tool to create TODO at the start of a user request, per the tool description.          
  2. After you accomplish a TODO, use the read_todos to read the TODOs in order to remind yourself of the plan. 
  3. Reflect on what you've done and the TODO.                                                                  
  4. Mark your task as completed, and proceed to the next TODO.                                                  
  5. Continue this process until you have completed all TODOs.    

You also have access to following internet search tool
**Internet Search Tool:**
- Use when user asks for recent information (news, budget announcements, current events)
- Use when real-time data is needed for the request.
- **Critical**: Use for questions requiring latest data that cannot be answered from knowledge (e.g., "who is the tallest person", "current stock prices", "latest sports scores", "recent weather data")
- **Important**: Do not include specific dates in searches unless user explicitly asks for time-specific information. For current data, search without date constraints to get the most recent results.
- Important: Limit searches to 5 results maximum to save credits. Focus on finding 2-5 high-quality sources.

**For Web Search Workflows:**
When conducting web searches, additionally use the think_tool (reflection tool) to:
- Analyze your research progress systematically
- Assess information gaps and quality of findings  
- Make strategic decisions about continuing searches vs. providing answers
- Plan next steps methodically

**Code Sandbox:**
- You have access to a code execution sandbox for running code snippets
- Use the execute_code tool when you need to test code, verify algorithms, or demonstrate programming concepts
- Supported languages: Python only
- Use for: debugging, testing logic, validating solutions, code examples
- **CRITICAL**: Always delete the sandbox after giving code to the user, unless the user explicitly asks to deploy the code

You have access to a virtual file system to help you retain and save context.      
## Workflow Process                                                                                            
1. **Orient**: Use ls() to see existing files before starting work                                              
2. **Save**: Use write_file() to store the user's request so that we can keep it for later.                 
3. **Read**: Once you are satisfied with the collected sources, read the saved file and use it to ensure that you directly answer the user's question.
4.  **Deliver the Final Answer:** Once your internal plan is complete and you have all the information, synthesize it into a clear and concise final answer for the user. The user should only receive this final answer, not your internal monologue or TODO list.                            

"""