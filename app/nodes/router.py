from __future__ import annotations

import os
from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.state import AgentState


ROUTER_PROMPT = """
Eres un router para un flujo multiagente técnico.

Devuelve exactamente una ruta:
- researcher: cuando el usuario pide investigar, recopilar evidencia o buscar información.
- builder: cuando el usuario pide diseñar o construir una solución.
- supervisor: cuando el usuario pide auditar, validar o revisar una propuesta existente.

Si la intención no es clara, devuelve builder.
""".strip()


class RouterDecision(BaseModel):
    next_agent: Literal["researcher", "builder", "supervisor"]


def _llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
        timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "45")),
    )


def router_node(state: AgentState) -> AgentState:
    messages = state.get("messages", [])

    if not os.getenv("OPENAI_API_KEY"):
        return {"intent": "builder", "next_agent": "builder"}

    try:
        decision = _llm().with_structured_output(RouterDecision).invoke(
            [SystemMessage(content=ROUTER_PROMPT)] + messages
        )
        next_agent = decision.next_agent
    except Exception:
        next_agent = "builder"

    return {
        "intent": next_agent,
        "next_agent": next_agent,
    }


def route_from_router(state: AgentState) -> str:
    return state.get("next_agent", "builder")
