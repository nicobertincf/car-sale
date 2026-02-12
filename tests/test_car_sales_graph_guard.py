import app.car_sales_graph as car_sales_graph_module
from langchain_core.messages import AIMessage, HumanMessage

from app.car_sales_graph import quote_agent_node


def test_quote_guard_resets_on_new_human_turn(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MAX_AGENT_TOOL_ITERATIONS", "8")

    blocked = quote_agent_node(
        {
            "messages": [AIMessage(content="respuesta de tool anterior")],
            "quote_agent_turns": 8,
            "runtime_country_id_override": None,
            "runtime_clear_make": False,
        }
    )
    assert "búsquedas automáticas en cadena" in blocked["messages"][-1].content

    reset = quote_agent_node(
        {
            "messages": [
                HumanMessage(content="Primera consulta"),
                AIMessage(content="respuesta"),
                HumanMessage(content="Nueva consulta"),
            ],
            "quote_agent_turns": 8,
            "runtime_country_id_override": None,
            "runtime_clear_make": False,
        }
    )
    assert "OPENAI_API_KEY" in reset["messages"][-1].content


def test_quote_guard_resets_when_human_count_increases(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MAX_AGENT_TOOL_ITERATIONS", "8")

    reset = quote_agent_node(
        {
            "messages": [
                HumanMessage(content="Quiero ver autos alemanes"),
                AIMessage(content="mensaje intermedio"),
            ],
            "quote_agent_turns": 8,
            "quote_agent_human_count": 0,
            "runtime_country_id_override": 6,
            "runtime_clear_make": False,
            "runtime_country_intent_detected": True,
        }
    )

    assert "Detuve la ejecución" not in reset["messages"][-1].content
    assert "OPENAI_API_KEY" in reset["messages"][-1].content


def test_conversation_language_is_stored_in_state(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        car_sales_graph_module,
        "_infer_conversation_language_with_llm",
        lambda _messages, _current_language: "en",
    )
    output = quote_agent_node(
        {
            "messages": [HumanMessage(content="hello, can you find me a japanese car?")],
        }
    )
    assert output["conversation_language"] == "en"
