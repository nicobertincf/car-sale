from app.state import AgentState
from langchain_core.messages import BaseMessage


RESEARCH_KEYWORDS = ("invest", "buscar", "research", "document")
SUPERVISOR_KEYWORDS = ("revisa", "valida", "audita", "corrige")


def _latest_user_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if message.type == "human":
            return str(message.content).lower()
    return ""


def router_node(state: AgentState) -> AgentState:
    messages = state.get("messages", [])
    last_input = _latest_user_text(messages)

    if any(keyword in last_input for keyword in RESEARCH_KEYWORDS):
        next_agent = "researcher"
    elif any(keyword in last_input for keyword in SUPERVISOR_KEYWORDS):
        next_agent = "supervisor"
    else:
        next_agent = "builder"

    return {
        "intent": next_agent,
        "next_agent": next_agent,
    }


def route_from_router(state: AgentState) -> str:
    return state.get("next_agent", "builder")
