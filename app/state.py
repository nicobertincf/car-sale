import operator
from typing import Annotated, Literal
from typing_extensions import NotRequired
from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """Estado compartido entre nodos del grafo."""

    intent: NotRequired[str]
    research_context: NotRequired[Annotated[list[str], operator.add]]
    draft_answer: NotRequired[str]
    final_answer: NotRequired[str]
    next_agent: NotRequired[Literal["researcher", "builder", "supervisor", "end"]]
