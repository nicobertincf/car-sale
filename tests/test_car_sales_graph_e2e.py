from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import app.car_sales_graph as car_sales_graph_module
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from scripts.init_sqlite_db import initialize_database


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def _latest_human(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            return _message_text(message.content)
    return ""


def _latest_tool_payload(messages: list[BaseMessage]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if getattr(message, "type", None) != "tool":
            continue
        try:
            payload = json.loads(_message_text(message.content))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _all_contact_payloads(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for message in messages:
        if getattr(message, "type", None) != "tool":
            continue
        try:
            payload = json.loads(_message_text(message.content))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("ok") is True and payload.get("request_id"):
            payloads.append(payload)
    return payloads


@dataclass
class _FakeStructuredInvoker:
    parent: "_FakeLLM"
    schema: type

    def invoke(self, messages: list[BaseMessage]) -> Any:
        latest = _latest_human(messages).lower()
        schema_name = self.schema.__name__

        if schema_name == "ConversationLanguageDecision":
            return self.schema(conversation_language="es")

        if schema_name == "RouteDecision":
            is_contact = any(token in latest for token in ["llam", "contact", "solicitud", "vehiculos"])
            return self.schema(route="contact_agent" if is_contact else "quote_agent")

        if schema_name == "QuoteRuntimeDirective":
            if any(token in latest for token in ["japon", "japones", "japanese", "japan"]):
                return self.schema(country_id_override=6, clear_make=True, country_intent_detected=True)
            if any(token in latest for token in ["aleman", "alemanes", "german", "germany"]):
                return self.schema(country_id_override=5, clear_make=True, country_intent_detected=True)
            return self.schema(country_id_override=None, clear_make=False, country_intent_detected=False)

        raise AssertionError(f"Unsupported structured schema in fake LLM: {schema_name}")


@dataclass
class _FakeToolBoundInvoker:
    parent: "_FakeLLM"
    tool_names: set[str]

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        if "create_executive_call_request" in self.tool_names:
            return self.parent._invoke_contact_agent(messages)
        return self.parent._invoke_quote_agent(messages)


class _FakeLLM:
    def __init__(self) -> None:
        self._counter = 0
        self.last_search_results: list[dict[str, Any]] = []

    def _next_call_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    def with_structured_output(self, schema: type) -> _FakeStructuredInvoker:
        return _FakeStructuredInvoker(self, schema)

    def bind_tools(self, tools: list[Any]) -> _FakeToolBoundInvoker:
        return _FakeToolBoundInvoker(self, {tool.name for tool in tools})

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        # Used by final supervisor: rewrite into customer-facing single paragraph without internal IDs.
        draft = _latest_human(messages)
        normalized_lines: list[str] = []
        for raw_line in draft.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if lowered.startswith("id:") or lowered.startswith("request_id"):
                continue
            if "id de solicitud" in lowered:
                line = line.split("ID de solicitud", 1)[0].strip()
            line = re.sub(r"\bID:\s*\d+\b", "", line).strip()
            if line.startswith("- "):
                line = line[2:]
            if len(line) > 3 and line[0].isdigit() and line[1:3] == ". ":
                line = line[3:]
            line = line.replace("**", "")
            line = " ".join(line.split())
            if line:
                normalized_lines.append(line)
        text = " ".join(normalized_lines).strip() or " ".join(draft.split()).strip() or draft
        return AIMessage(content=text)

    def _invoke_quote_agent(self, messages: list[BaseMessage]) -> AIMessage:
        payload = _latest_tool_payload(messages)
        if payload is not None and isinstance(payload.get("vehicles"), list):
            vehicles = payload.get("vehicles", [])
            self.last_search_results = [row for row in vehicles if isinstance(row, dict)]
            if not self.last_search_results:
                return AIMessage(content="No encontré autos con esos criterios, si quieres ajustamos un filtro.")

            if len(self.last_search_results) == 1:
                vehicle = self.last_search_results[0]
                return AIMessage(
                    content=(
                        f"Encontré una opción.\nID: {vehicle.get('id')}\n"
                        f"- {vehicle.get('make')} {vehicle.get('model')} {vehicle.get('year')}, "
                        f"{vehicle.get('mileage_km')} km, ${vehicle.get('price_usd')}."
                    )
                )

            lines = ["Encontré varias opciones:"]
            for vehicle in self.last_search_results[:4]:
                lines.append(
                    f"- {vehicle.get('make')} {vehicle.get('model')} ({vehicle.get('year')}) ID: {vehicle.get('id')}"
                )
            return AIMessage(content="\n".join(lines))

        latest = _latest_human(messages).lower()
        if any(token in latest for token in ["japon", "japones", "japanese", "japan"]):
            args = {"country_id": 6, "mileage_km_max": 100000}
        elif any(token in latest for token in ["aleman", "alemanes", "german", "germany"]):
            args = {"country_id": 5, "mileage_km_max": 100000}
        else:
            return AIMessage(content="Cuéntame qué país o filtros quieres usar para buscar opciones.")

        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": self._next_call_id("search"),
                    "name": "search_used_vehicles",
                    "args": args,
                    "type": "tool_call",
                }
            ],
        )

    def _infer_vehicle_id(self, text: str) -> int | None:
        lowered = text.lower()
        if "audi" in lowered:
            return 53
        if "nissan" in lowered or "x-trail" in lowered or "xtrail" in lowered:
            return 40

        for row in self.last_search_results:
            make = str(row.get("make", "")).lower()
            model = str(row.get("model", "")).lower()
            if make and make in lowered and model and model in lowered:
                vehicle_id = row.get("id")
                if isinstance(vehicle_id, int):
                    return vehicle_id
        if len(self.last_search_results) == 1 and isinstance(self.last_search_results[0].get("id"), int):
            return int(self.last_search_results[0]["id"])
        return None

    def _extract_profile_from_text(self, text: str) -> tuple[str | None, str | None, str | None]:
        phone_match = re.search(r"\+?\d[\d\s-]{7,}\d", text)
        phone_number = re.sub(r"\s+", "", phone_match.group(0)) if phone_match else None

        first_chunk = text.split(",")[0].strip()
        customer_name = first_chunk if first_chunk and not any(ch.isdigit() for ch in first_chunk) else None

        lowered = text.lower()
        if "tarde" in lowered:
            preferred_call_time = "tarde"
        elif "19" in lowered:
            preferred_call_time = "despues de las 19"
        else:
            preferred_call_time = None
        return customer_name, phone_number, preferred_call_time

    def _last_profile_from_messages(self, messages: list[BaseMessage]) -> dict[str, str] | None:
        for payload in reversed(_all_contact_payloads(messages)):
            customer_name = str(payload.get("customer_name", "")).strip()
            phone_number = str(payload.get("phone_number", "")).strip()
            preferred_call_time = str(payload.get("preferred_call_time", "")).strip()
            if customer_name and phone_number and preferred_call_time:
                return {
                    "customer_name": customer_name,
                    "phone_number": phone_number,
                    "preferred_call_time": preferred_call_time,
                }
        return None

    def _invoke_contact_agent(self, messages: list[BaseMessage]) -> AIMessage:
        latest = _latest_human(messages)
        lowered = latest.lower()

        if "vehiculos" in lowered and ("llamar" in lowered or "contact" in lowered):
            requested_models: list[str] = []
            for contact_payload in _all_contact_payloads(messages):
                vehicle_id = contact_payload.get("vehicle_id")
                if vehicle_id == 40:
                    requested_models.append("Nissan X-Trail")
                elif vehicle_id == 53:
                    requested_models.append("Audi A4")
            if requested_models:
                unique_models = list(dict.fromkeys(requested_models))
                models_text = " y ".join(unique_models)
                return AIMessage(
                    content=(
                        f"Registraste solicitudes para {models_text}. "
                        "Ambas con preferencia de llamada en la tarde."
                    )
                )
            return AIMessage(
                content="Aún no tengo solicitudes de contacto registradas en esta conversación."
            )

        payload = _latest_tool_payload(messages)
        # Only confirm tool output when the current graph step is processing the tool result.
        if (
            messages
            and getattr(messages[-1], "type", None) == "tool"
            and payload is not None
            and payload.get("ok") is True
            and payload.get("request_id")
        ):
            vehicle_name = "vehículo"
            vehicle_id = payload.get("vehicle_id")
            if vehicle_id == 40:
                vehicle_name = "Nissan X-Trail"
            elif vehicle_id == 53:
                vehicle_name = "Audi A4"
            return AIMessage(
                content=(
                    f"Solicitud registrada para {vehicle_name}. "
                    f"ID de solicitud: {payload.get('request_id')}. "
                    f"Horario preferido: {payload.get('preferred_call_time', 'tarde')}."
                )
            )

        profile = self._last_profile_from_messages(messages)
        vehicle_id = self._infer_vehicle_id(latest)

        customer_name, phone_number, preferred_call_time = self._extract_profile_from_text(latest)
        if customer_name and phone_number and preferred_call_time and vehicle_id is not None:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": self._next_call_id("contact"),
                        "name": "create_executive_call_request",
                        "args": {
                            "vehicle_id": vehicle_id,
                            "customer_name": customer_name,
                            "phone_number": phone_number,
                            "preferred_call_time": preferred_call_time,
                        },
                        "type": "tool_call",
                    }
                ],
            )

        if profile and vehicle_id is not None and ("llam" in lowered or "contact" in lowered):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": self._next_call_id("contact"),
                        "name": "create_executive_call_request",
                        "args": {
                            "vehicle_id": vehicle_id,
                            "customer_name": profile["customer_name"],
                            "phone_number": profile["phone_number"],
                            "preferred_call_time": profile["preferred_call_time"],
                        },
                        "type": "tool_call",
                    }
                ],
            )

        return AIMessage(
            content="Para avanzar, compárteme tu nombre completo, teléfono y horario preferido de llamada."
        )


def _run_turn(state: dict[str, Any], user_text: str) -> tuple[dict[str, Any], str]:
    next_state = dict(state)
    next_state["messages"] = list(state.get("messages", [])) + [HumanMessage(content=user_text)]
    output = car_sales_graph_module.graph.invoke(next_state)
    reply = _message_text(output["messages"][-1].content)
    return output, reply


def test_e2e_japan_then_contact_then_germany_then_contact_then_supervised_summary(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "dealership.db"
    initialize_database(db_path=db_path, seed_count=60)

    monkeypatch.setenv("DEALERSHIP_DB_PATH", str(db_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("FINAL_SUPERVISOR_USE_LLM", "true")

    fake_llm = _FakeLLM()
    monkeypatch.setattr(car_sales_graph_module, "_llm", lambda: fake_llm)

    state: dict[str, Any] = {"messages": []}

    state, reply_1 = _run_turn(state, "quiero un auto japones con menos de 100mil kilometros")
    assert "Nissan X-Trail" in reply_1
    assert "ID" not in reply_1
    assert "\n-" not in reply_1

    state, reply_2 = _run_turn(state, "quiero que me llamen")
    assert "nombre completo" in reply_2.lower()
    assert "teléfono" in reply_2.lower() or "telefono" in reply_2.lower()

    state, reply_3 = _run_turn(state, "Mario Sepulveda, +56912341234, llamenme en la tarde")
    assert "Nissan X-Trail" in reply_3
    assert "ID" not in reply_3

    state, reply_4 = _run_turn(state, "ahora quiero ver autos alemanes")
    assert "Audi A4" in reply_4
    assert "ID" not in reply_4
    assert "\n-" not in reply_4

    state, reply_5 = _run_turn(state, "quiero que me contacten por el audi")
    assert "Audi A4" in reply_5
    assert "ID" not in reply_5

    state, reply_6 = _run_turn(state, "que vehiculos son los que pedi que me llamaran?")
    assert "Nissan X-Trail" in reply_6
    assert "Audi A4" in reply_6
    assert "ID" not in reply_6
    assert "\n" not in reply_6

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT vehicle_id, customer_name, phone_number, preferred_call_time
            FROM contact_requests
            ORDER BY id ASC;
            """
        ).fetchall()

    assert len(rows) == 2
    assert {int(row[0]) for row in rows} == {40, 53}
    assert all(str(row[1]).strip() == "Mario Sepulveda" for row in rows)
    assert all(str(row[2]).strip() == "+56912341234" for row in rows)
