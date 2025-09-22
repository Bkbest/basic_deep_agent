from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from AI_State.state import State
from AI_Tools.tools import MyTools
from AI_Sys_Prompt.system_prompt_agent import system_prompt_todo_req
from AI_LLM.agent_llm import MyLLM
from langgraph.graph import END

llm_factory = MyLLM(temperature=0.7,tools=MyTools().getAllTools())
llm = llm_factory.llm_without_tools()
llm_tools = llm_factory.llm_with_tools()

def is_tool_required(state: State):
    messages = state["messages"]
    lastMessage = messages[-1]  
    
    if hasattr(lastMessage,"tool_calls") and lastMessage.tool_calls:
        return "tool_node"
    else:
        print("Tool not required")
        return END


def llm_with_tools(state: State):
    """
    Processes messages using LLM with tools when required.
    
    Args:
        state: Current state containing messages and tool requirement
        
    Returns:
        Dict containing updated messages
    """
    print(state["messages"])
    # Create the prompt template with system prompt and messages
    prompt_template = ChatPromptTemplate.from_messages  ([
            ("system", system_prompt_todo_req),
            MessagesPlaceholder(variable_name="messages")
        ])
    chain = prompt_template.invoke(state)
    response = llm_tools.invoke(chain)
    
    # Return the response as a message
    return {"messages": [response]}
