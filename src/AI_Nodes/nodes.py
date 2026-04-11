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
    agent_description = AGENT_DESCRIPTION
    prompt = PromptTemplate.from_template(agent_description)
    system_message = [SystemMessage(content=prompt.format(current_date=state["current_date"], skills_description=state["skills_description"]))]
    
    #add systemmessage to the beginning of the messages to be summarized so that it is included in the summary.
    state["messages"] = system_message + state["messages"]
    
    summarization_result = await asummarize_messages(
        state["messages"],
        running_summary=state.get("summary"),
        model=llm,
        max_tokens=40000,
        max_tokens_before_summary=20000,
        max_summary_tokens=1000,
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
    await asyncio.sleep(10)
    response = await llm_tools.ainvoke(messags_after_summarization)
    state_update = {"messages": [response]}
    if summarization_result.running_summary:
        state_update["summary"] = summarization_result.running_summary
    
    # Return the response as a message
    return state_update
