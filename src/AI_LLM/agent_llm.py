"""
This module provides a custom LLM wrapper class that manages both a base LLM and LLM with tools.
It uses the Ollama framework with the llama3.2:3b model.
"""

from langchain_ollama.chat_models import ChatOllama

class MyLLM:
    """Custom LLM wrapper that provides access to both base LLM and LLM with tools."""
    def __init__(self,temperature,tools) -> None:
        """
        Initializes the MyLLM instance with the given temperature and tools.

        Args:
            temperature (float): The temperature for the LLM.
            tools (list): The list of tools to bind to the LLM.
        """
        self.temperature = temperature
        self.llm = ChatOllama(model="gpt-oss",temperature=self.temperature)
        self.llm_tools = self.llm.bind_tools(tools)

    def llm_without_tools(self):
        """
        Returns the base LLM without tools.

        Returns:
            ChatOllama: The base LLM instance.
        """
        return self.llm

    def llm_with_tools(self):
        return self.llm_tools