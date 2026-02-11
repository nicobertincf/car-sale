from app.state import AgentState


def supervisor_node(state: AgentState) -> AgentState:
    draft = state.get("draft_answer", "No hay borrador para revisar.")
    final_answer = (
        "Respuesta final revisada:\n"
        f"{draft}\n"
        "Checklist: alcance claro, pasos accionables, y siguiente iteracion definida."
    )
    return {
        "final_answer": final_answer,
        "next_agent": "end",
    }
