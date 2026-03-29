from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from AI_State.state import State
from AI_Tools.tools import MyTools
from AI_Sys_Prompt.system_prompt_agent import AGENT_DESCRIPTION
from AI_LLM.agent_llm import MyLLM
from langgraph.graph import END
from langmem.short_term import summarize_messages
from langgraph.runtime import Runtime
import time
import asyncio


tools=MyTools().getToolsSync()
llm_factory = MyLLM(temperature=0.7,tools=tools)
llm = llm_factory.llm_without_tools()
llm_tools = llm_factory.llm_with_tools()

async def is_tool_required(state: State):
    messages = state["messages"]
    lastMessage = messages[-1]  
    
    if hasattr(lastMessage,"tool_calls") and lastMessage.tool_calls:
        return "tool_node"
    else:
        print("Tool not required")
        return END


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
    
    summarization_result = summarize_messages(
        state["messages"],
        running_summary=state.get("summary"),
        model=llm,
        max_tokens=10000,
        max_tokens_before_summary=10000,
        max_summary_tokens=4000
    )
    messags_after_summarization = summarization_result.messages
    prompt_template = ChatPromptTemplate.from_messages  ([
            ("system", AGENT_DESCRIPTION)
        ]+messags_after_summarization)
    await asyncio.sleep(10)
    chain = prompt_template.invoke(state)
    response = llm_tools.invoke(chain)
    state_update = {"messages": [response]}
    if summarization_result.running_summary:
        state_update["summary"] = summarization_result.running_summary
    
    # Return the response as a message
    return state_update
