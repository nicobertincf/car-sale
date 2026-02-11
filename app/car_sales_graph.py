from __future__ import annotations

import os
from typing import Any, Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel
from typing_extensions import NotRequired

from app.prompts.car_sales_prompts import (
    CONTACT_AGENT_SYSTEM_PROMPT,
    QUOTE_AGENT_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
)
from app.tools.car_sales_tools import CONTACT_TOOLS, QUOTE_TOOLS


class CarSalesState(MessagesState):
    route: NotRequired[Literal["quote_agent", "contact_agent"]]


class RouteDecision(BaseModel):
    route: Literal["quote_agent", "contact_agent"]


def _ensure_langchain_cache_compat() -> None:
    """Compatibility guard for mixed LangChain installs in local environments."""
    try:
        import langchain

        if not hasattr(langchain, "llm_cache"):
            setattr(langchain, "llm_cache", None)
    except Exception:
        # Never block graph execution due to optional compatibility patching.
        return


def _llm() -> ChatOpenAI:
    _ensure_langchain_cache_compat()
    return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)


def router_node(state: CarSalesState) -> CarSalesState:
    messages = state["messages"]
    previous_route = state.get("route", "quote_agent")

    if not os.getenv("OPENAI_API_KEY"):
        return {"route": previous_route}

    try:
        decision = _llm().with_structured_output(RouteDecision).invoke(
            [SystemMessage(content=ROUTER_SYSTEM_PROMPT)] + messages
        )
        return {"route": decision.route}
    except Exception:
        # Keep the previous route to avoid keyword-based hardcoded routing fallbacks.
        return {"route": previous_route}


def route_from_router(state: CarSalesState) -> str:
    return state.get("route", "quote_agent")


def quote_agent_node(state: CarSalesState) -> CarSalesState:
    messages = state["messages"]

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "messages": [
                AIMessage(
                    content=(
                        "Para usar el agente de cotización en LangSmith/Studio necesitas `OPENAI_API_KEY`. "
                        "Configúrala en `.env` y vuelve a ejecutar."
                    )
                )
            ]
        }

    response = _llm().bind_tools(QUOTE_TOOLS).invoke(
        [SystemMessage(content=QUOTE_AGENT_SYSTEM_PROMPT)] + messages
    )
    return {"messages": [response], "route": "quote_agent"}


def contact_agent_node(state: CarSalesState) -> CarSalesState:
    messages = state["messages"]

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "messages": [
                AIMessage(
                    content=(
                        "Para usar el agente de contacto en LangSmith/Studio necesitas `OPENAI_API_KEY`. "
                        "Configúrala en `.env` y vuelve a ejecutar."
                    )
                )
            ]
        }

    response = _llm().bind_tools(CONTACT_TOOLS).invoke(
        [SystemMessage(content=CONTACT_AGENT_SYSTEM_PROMPT)] + messages
    )
    return {"messages": [response], "route": "contact_agent"}


def _route_after_agent(state: CarSalesState, tools_node_name: str) -> str:
    if not state.get("messages"):
        return END

    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []
    if tool_calls:
        return tools_node_name
    return END


def route_after_quote_agent(state: CarSalesState) -> str:
    return _route_after_agent(state, "quote_tools")


def route_after_contact_agent(state: CarSalesState) -> str:
    return _route_after_agent(state, "contact_tools")


def build_graph() -> Any:
    builder = StateGraph(CarSalesState)

    builder.add_node("router", router_node)
    builder.add_node("quote_agent", quote_agent_node)
    builder.add_node("quote_tools", ToolNode(QUOTE_TOOLS))
    builder.add_node("contact_agent", contact_agent_node)
    builder.add_node("contact_tools", ToolNode(CONTACT_TOOLS))

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        route_from_router,
        {
            "quote_agent": "quote_agent",
            "contact_agent": "contact_agent",
        },
    )

    builder.add_conditional_edges(
        "quote_agent",
        route_after_quote_agent,
        {
            "quote_tools": "quote_tools",
            END: END,
        },
    )
    builder.add_edge("quote_tools", "quote_agent")

    builder.add_conditional_edges(
        "contact_agent",
        route_after_contact_agent,
        {
            "contact_tools": "contact_tools",
            END: END,
        },
    )
    builder.add_edge("contact_tools", "contact_agent")

    return builder.compile()


graph = build_graph()
