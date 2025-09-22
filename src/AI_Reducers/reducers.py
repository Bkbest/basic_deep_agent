"""
This module contains reducer functions for managing state in the weather agent application.

Reducers are pure functions that take the current state and an action, and return a new state.
They are used in the application's state management system to update the state in a predictable way.
"""

from langchain_core.messages import BaseMessage
from typing import Sequence

def message_reducer(messages: Sequence[BaseMessage], newMessage) -> Sequence[BaseMessage]:
    """
    Reducer function for managing the messages state.
    
    Args:
        messages: Current list of messages
        newMessage: New message to add
        
    Returns:
        Updated list of messages with the new message appended
    """
    return messages + newMessage


def file_reducer(files: dict[str, str], newFile: tuple[str, str]) -> dict[str, str]:
    """Reducer function for managing the files state."""
    if files is None:
        return newFile
    elif newFile is None:
        return files
    else:
        return {**files, **newFile}
        
    