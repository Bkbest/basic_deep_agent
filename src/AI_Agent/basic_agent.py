import asyncio
import sys

from langgraph.graph import START, StateGraph
from AI_Nodes.nodes import is_tool_required, llm_with_tools
from AI_State.state import State
from langgraph.prebuilt import ToolNode
from AI_Tools.tools import MyTools
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import os
from dotenv import load_dotenv

load_dotenv()


def create_research_brief_workflow():
    # Create the workflow graph
    workflow = StateGraph(state_schema=State)
    all_tools = MyTools().getToolsSync()

    # Add nodes
    workflow.add_node("llm_with_tools", llm_with_tools)
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
    workflow.add_node("llm_with_tools", llm_with_tools)
    workflow.add_node("tool_node", ToolNode(all_tools))

    # Add edges
    workflow.add_edge(START, "llm_with_tools")
    workflow.add_conditional_edges("llm_with_tools", is_tool_required)
    workflow.add_edge("tool_node", "llm_with_tools")

    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    async with AsyncPostgresSaver.from_conn_string(connection_string) as checkpointer:  
        
        await checkpointer.setup()
        
        # checkpointer.delete_thread(thread_id)
    
        graph = workflow.compile(checkpointer=checkpointer)
        
        
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}
        
        async for chunk in graph.astream({"messages": message},stream_mode="updates", config=config ):
            yield chunk


graph = create_research_brief_workflow()

if __name__ == "__main__":
    # Example usage
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    async def main():
        async for chunk in invoke_workflow_stream("1", [HumanMessage("research about the latest advancements in renewable energy")]):
            print(chunk)
    
    asyncio.run(main())
