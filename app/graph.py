from langgraph.graph import END, START, StateGraph

from app.nodes.builder import builder_node
from app.nodes.researcher import researcher_node
from app.nodes.router import route_from_router, router_node
from app.nodes.supervisor import supervisor_node
from app.state import AgentState


def build_graph():
    graph_builder = StateGraph(AgentState)

    graph_builder.add_node("router", router_node)
    graph_builder.add_node("researcher", researcher_node)
    graph_builder.add_node("builder", builder_node)
    graph_builder.add_node("supervisor", supervisor_node)

    graph_builder.add_edge(START, "router")
    graph_builder.add_conditional_edges(
        "router",
        route_from_router,
        {
            "researcher": "researcher",
            "builder": "builder",
            "supervisor": "supervisor",
        },
    )

    graph_builder.add_edge("researcher", "builder")
    graph_builder.add_edge("builder", "supervisor")
    graph_builder.add_edge("supervisor", END)

    return graph_builder.compile()


graph = build_graph()
