"""
This module defines the state structure for the weather agent application.

The State class uses TypedDict to define a strongly-typed state structure,
with each field annotated with its corresponding reducer function.
This approach helps maintain type safety and ensures that state updates
are handled through the appropriate reducer functions.
"""

from typing_extensions import Annotated
from AI_Reducers.reducers import file_reducer
from langchain.agents import AgentState
from typing import TypedDict, Literal


class Todo(TypedDict):
    content: str
    status: Literal["pending", "completed","in_progress"]


class State(AgentState):
    """
    Defines the state structure for the weather agent.
    
    Fields:
        messages: List of messages in the conversation
            - Uses message_reducer to manage message state
        isToolNeeded: Boolean indicating whether a tool is needed
            - Uses tool_reducer to manage tool state
    """
    # messages: Annotated[list, message_reducer]
    todos: list[Todo]
    files: Annotated[dict[str, str], file_reducer]