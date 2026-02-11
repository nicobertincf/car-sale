import operator
from typing import Annotated, Literal
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    """Estado compartido entre nodos del grafo."""

    messages: list[str]
    intent: str
    research_context: Annotated[list[str], operator.add]
    draft_answer: str
    final_answer: str
    next_agent: Literal["researcher", "builder", "supervisor", "end"]
