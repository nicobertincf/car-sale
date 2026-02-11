from app.state import AgentState


def builder_node(state: AgentState) -> AgentState:
    context = "\n".join(state.get("research_context", []))
    user_request = state.get("messages", [""])[-1]

    if context:
        draft = (
            "Borrador generado con contexto de investigacion:\n"
            f"Solicitud: {user_request}\n"
            f"Contexto:\n{context}\n"
            "Propuesta inicial: implementar en pasos y validar con pruebas."
        )
    else:
        draft = (
            "Borrador generado sin contexto externo:\n"
            f"Solicitud: {user_request}\n"
            "Propuesta inicial: descomponer el problema y ejecutar iterativamente."
        )

    return {
        "draft_answer": draft,
        "next_agent": "supervisor",
    }
