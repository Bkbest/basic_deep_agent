import pytest
from langchain_core.messages import HumanMessage

from AI_Agent import graph
from AI_Agent.basic_agent import get_current_date

pytestmark = pytest.mark.anyio


async def test_agent_simple_passthrough() -> None:
    # `current_date` and `skills_description` are read by the `llm_with_tools`
    # node, so they must be supplied here just as the app does.
    inputs = {
        "messages": [HumanMessage(content="Say hello and nothing else.")],
        "current_date": get_current_date(),
        "skills_description": "Skills: none",
        "soul": None,
    }
    res = await graph.ainvoke(inputs)
    assert res is not None
    assert res["messages"], "the graph should produce at least one message"
