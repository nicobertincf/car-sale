from app.graph import graph


def test_graph_path_with_research_keyword():
    output = graph.invoke({"messages": ["Necesito investigar este tema y documentarlo"]})
    assert output["intent"] == "researcher"
    assert output["next_agent"] == "end"
    assert "Respuesta final revisada" in output["final_answer"]


def test_graph_path_without_research_keyword():
    output = graph.invoke({"messages": ["Ayudame a proponer una solucion"]})
    assert output["intent"] == "builder"
    assert output["next_agent"] == "end"
    assert "Checklist" in output["final_answer"]
