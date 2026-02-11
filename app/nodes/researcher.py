from app.state import AgentState
from app.tools.web import fake_web_search
from langchain_core.messages import BaseMessage


def _latest_user_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if message.type == "human":
            return str(message.content)
    return ""


def researcher_node(state: AgentState) -> AgentState:
    query = _latest_user_text(state.get("messages", []))
    context_item = fake_web_search(query)
    return {
        "research_context": [context_item],
        "next_agent": "builder",
    }
