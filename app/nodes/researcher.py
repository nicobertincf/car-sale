from app.state import AgentState
from app.tools.web import fake_web_search


def researcher_node(state: AgentState) -> AgentState:
    query = state.get("messages", [""])[-1]
    context_item = fake_web_search(query)
    return {
        "research_context": [context_item],
        "next_agent": "builder",
    }
