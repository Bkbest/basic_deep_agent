import asyncio
import sys

from langgraph.graph import START, StateGraph
from AI_Nodes.nodes import is_tool_required, llm_with_tools
from AI_State.state import State
from langgraph.prebuilt.tool_node import (
    ToolNode
)
from AI_Tools.tools import MyTools
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.postgres import PostgresSaver
import os
from dotenv import load_dotenv
import asyncpg
from langgraph.types import RetryPolicy
from datetime import datetime

load_dotenv()


def create_research_brief_workflow():
    # Create the workflow graph
    workflow = StateGraph(state_schema=State)
    all_tools = MyTools().getToolsSync()

    # Add nodes
    workflow.add_node("llm_with_tools", llm_with_tools,retry_policy=RetryPolicy(max_attempts=3))
    workflow.add_node("tool_node", ToolNode(all_tools))

    # Add edges
    workflow.add_edge(START, "llm_with_tools")
    workflow.add_conditional_edges("llm_with_tools", is_tool_required)
    workflow.add_edge("tool_node", "llm_with_tools")
    
    graph = workflow.compile()
    
    return graph

async def invoke_workflow_stream(thread_id, message):
    """
    Async generator that yields chunks from the workflow
    """
    # Create the workflow graph
    workflow = StateGraph(state_schema=State)
    all_tools = await MyTools().getAllTools()
    # Add nodes
    workflow.add_node("llm_with_tools", llm_with_tools,retry_policy=RetryPolicy(max_attempts=3))
    workflow.add_node("tool_node", ToolNode(all_tools))

    # Add edges
    workflow.add_edge(START, "llm_with_tools")
    workflow.add_conditional_edges("llm_with_tools", is_tool_required)
    workflow.add_edge("tool_node", "llm_with_tools")

    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    async with AsyncPostgresSaver.from_conn_string(connection_string) as checkpointer:  
        
        try:
            await checkpointer.setup()
        except Exception as e:
            print(f"Error setting up checkpointer: {e}")
            return
        
        try:
            await create_thread(thread_id)
        except Exception as e:
            print(f"Error creating thread: {e}")
            # Checkpointer might have done its job, so clean it up
            await asyncio.to_thread(checkpointer.delete_thread, thread_id)
            return
        
    
        graph = workflow.compile(checkpointer=checkpointer)
        skills = await get_skills_description()
        
        
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
        
        async for chunk in graph.astream({"messages": message,"current_date": get_current_date(), "skills_description": skills},stream_mode="updates", config=config ):
            yield chunk


async def invoke_workflow(prompt: str, thread_id: str = "default"):
    """
    Invoke the workflow with a prompt and return the full output.
    """
    graph = create_research_brief_workflow()
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
   
    output = graph.invoke(
       {"messages": prompt,"current_date": get_current_date(), "skills_description": await get_skills_description()},
        config=config
    )
    if output and 'messages' in output:
        agent_response = output['messages'][-1].content if output['messages'] else "No response"
        return agent_response
    return "No output from workflow"

            
def get_current_date() -> str:
    """Get current date"""
    return datetime.now().strftime("%a %b %d, %Y")


async def get_skills_description() -> str:
    """Fetch all skills from the database and format them as a readable string."""
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        return "Skills: none (database not configured)"

    try:
        conn = await asyncpg.connect(connection_string)
        try:
            rows = await conn.fetch("SELECT skill_name, skill_description FROM skills")
            if not rows:
                return "Skills: none"
            lines = ["Skills:"]
            for row in rows:
                lines.append(f"  - {row['skill_name']}: {row['skill_description']}")
            return "\n".join(lines)
        finally:
            await conn.close()
    except Exception:
        return "Skills: unable to fetch"

            
async def delete_thread(thread_id):
    """
    delete all checkpoints for a thread and remove from threads table
    """

    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")
    
    try:
        with PostgresSaver.from_conn_string(connection_string) as checkpointer:  
            try:
                checkpointer.delete_thread(thread_id)
            except Exception as e:
                print(f"Error deleting checkpointer thread: {e}")
                return
        
        # Also delete from threads table
        try:
            conn = await asyncpg.connect(connection_string)
            try:
                await conn.execute('DELETE FROM threads WHERE thread_id = $1', thread_id)
            finally:
                await conn.close()
        except Exception as e:
            print(f"Error deleting thread from threads table: {e}")
            
    except Exception as e:
        print(f"Error in delete_thread: {e}")
        
        
async def create_thread(thread_id):
    """
    create a new thread by inserting thread_id into threads table
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")
    
    try:
        # Connect to PostgreSQL
        conn = await asyncpg.connect(connection_string)
        
        try:
            # Create threads table if it doesn't exist
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id VARCHAR(255) PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Insert the thread_id
            await conn.execute(
                'INSERT INTO threads (thread_id) VALUES ($1) ON CONFLICT (thread_id) DO NOTHING',
                thread_id
            )
            
        finally:
            await conn.close()
            
    except Exception as e:
        raise Exception(f"Failed to create thread: {str(e)}")

async def get_threads():
    """
    Get all distinct thread IDs from the database
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")
    
    try:
        conn = await asyncpg.connect(connection_string)
        try:
            # Query distinct thread_ids from the threads table
            rows = await conn.fetch('SELECT thread_id, created_at FROM threads ORDER BY created_at DESC')
            
            threads = []
            for row in rows:
                threads.append({
                    "thread_id": row['thread_id'],
                    "created_at": row['created_at'].isoformat() if row['created_at'] else None
                })
            
            return {"threads": threads, "count": len(threads)}
            
        finally:
            await conn.close()
            
    except Exception as e:
        raise Exception(f"Failed to fetch threads: {str(e)}")
    
    
def get_thread(thread_id):
    
    """
    Get a specific thread by thread_id
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")
    try:
        with PostgresSaver.from_conn_string(connection_string) as checkpointer:  
            try:
                config = {"configurable": {"thread_id": thread_id}}
                result = checkpointer.get_tuple(config)
                return result
            except Exception as e:
                print(f"Error getting checkpointer thread: {e}")
                return
            
    except Exception as e:
        print(f"Error in get_thread: {e}")
    
    
        


graph = create_research_brief_workflow()

if __name__ == "__main__":
    # Example usage
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
    async def main():
        
        # Then invoke the workflow stream
        # async for chunk in invoke_workflow_stream("17", [HumanMessage("do you know any skills, don't access any tools.")]):
        #     print(chunk)
        
        # Finally, clean up by deleting the thread
        print(await get_threads())
        # await print(get_thread("thread_2e61jwp1a_1774693865061"))
    
    asyncio.run(main())
