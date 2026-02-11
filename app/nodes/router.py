from app.state import AgentState


RESEARCH_KEYWORDS = ("invest", "buscar", "research", "document")
SUPERVISOR_KEYWORDS = ("revisa", "valida", "audita", "corrige")


def router_node(state: AgentState) -> AgentState:
    messages = state.get("messages", [])
    last_input = messages[-1].lower() if messages else ""

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
