from app.graph import graph
from langchain_core.messages import HumanMessage


def test_graph_path_with_research_keyword():
    output = graph.invoke({"messages": [HumanMessage(content="Necesito investigar este tema y documentarlo")]})
    assert output["intent"] == "researcher"
    assert output["next_agent"] == "end"
    assert "Respuesta final revisada" in output["final_answer"]


def test_graph_path_without_research_keyword():
    output = graph.invoke({"messages": [HumanMessage(content="Ayudame a proponer una solucion")]})
    assert output["intent"] == "builder"
    assert output["next_agent"] == "end"
    assert "Checklist" in output["final_answer"]
