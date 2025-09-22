from langgraph.graph import START, StateGraph
from AI_Nodes.nodes import is_tool_required, llm_with_tools
from AI_State.state import State
from langgraph.prebuilt import ToolNode
from AI_Tools.tools import MyTools
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver


def create_research_brief_workflow():
    # Create the workflow graph
    workflow = StateGraph(state_schema=State)
    all_tools = MyTools().getAllTools()

    # Add nodes
    workflow.add_node("llm_with_tools", llm_with_tools)
    workflow.add_node("tool_node", ToolNode(all_tools))

    # Add edges
    workflow.add_edge(START, "llm_with_tools")
    workflow.add_conditional_edges("llm_with_tools", is_tool_required)
    workflow.add_edge("tool_node", "llm_with_tools")

    # # Compile the graph with checkpointer
    # checkpointer = MemorySaver()
    graph = workflow.compile()
    
    return graph

graph = create_research_brief_workflow()

if __name__ == "__main__":
    # Example usage
    config = {"configurable": {"thread_id": "5"},"recursion_limit": 3}
    query = "what is 2 multiplied by 3 plus 7"
    input_messages = [HumanMessage(query)]
    output = graph.invoke({
        "messages": input_messages,
        'tools': ','.join([f'{tool}: {desc}' for tool, desc in MyTools().getToolDiscription().items()])
    }, config=config)
    # output["messages"][-1].pretty_print()

