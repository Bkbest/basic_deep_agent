"""Structured output schemas for task completion checks."""

from pydantic import BaseModel, Field


class TaskCompletion(BaseModel):
    """Verdict returned by the LLM when deciding if the agent's task is done."""

    is_complete: bool = Field(
        description=(
            "True only if the user's task is fully complete: every TODO item is "
            "marked completed and a concrete final answer has been delivered. "
            "False if any TODO is pending or in progress, or if the agent is "
            "waiting on the user for clarification."
        )
    )
    reasoning: str = Field(
        description="Short justification for the verdict, citing the TODO list and the latest agent message."
    )
