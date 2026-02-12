import json

import app.car_sales_graph as car_sales_graph_module
from langchain_core.messages import AIMessage, ToolMessage

from app.car_sales_graph import (
    contact_agent_node,
    final_supervisor_node,
    _enforce_quote_tool_call_policy,
    _extract_last_contact_profile,
    _extract_recent_vehicle_candidates,
    _sync_state_from_tool_messages,
)


def test_extract_last_contact_profile_from_ai_tool_call():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "create_executive_call_request",
                    "args": {
                        "vehicle_id": 40,
                        "customer_name": "Roger Aguilar Pacheco",
                        "phone_number": "+56941425034",
                        "preferred_call_time": "despues de las 19",
                    },
                }
            ],
        )
    ]

    profile = _extract_last_contact_profile(messages)
    assert profile is not None
    assert profile["customer_name"] == "Roger Aguilar Pacheco"
    assert profile["phone_number"] == "+56941425034"
    assert profile["preferred_call_time"] == "despues de las 19"


def test_vehicle_candidate_matching_with_recent_search_results():
    payload = {
        "count": 2,
        "vehicles": [
            {"id": 54, "make": "Peugeot", "model": "3008", "year": 2022},
            {"id": 24, "make": "Peugeot", "model": "3008", "year": 2020},
        ],
    }
    messages = [
        ToolMessage(
            content=json.dumps(payload, ensure_ascii=False),
            tool_call_id="call_2",
            name="search_used_vehicles",
        )
    ]

    candidates = _extract_recent_vehicle_candidates(messages)
    assert [item["id"] for item in candidates] == [54, 24]


def test_sync_state_from_tool_messages_builds_persistent_memory():
    search_payload = {
        "count": 2,
        "filters_used": {"country_id": 5, "mileage_km_max": 100000},
        "vehicles": [
            {"id": 42, "make": "Volkswagen", "model": "Tiguan", "year": 2024, "country_of_origin": "Germany"},
            {"id": 53, "make": "Audi", "model": "A4", "year": 2021, "country_of_origin": "Germany"},
        ],
    }
    contact_payload = {
        "ok": True,
        "request_id": 8,
        "vehicle_id": 42,
        "customer_name": "Roger Aguilar Pacheco",
        "phone_number": "+56941425034",
        "preferred_call_time": "despues de las 19",
        "created": True,
    }
    state = {
        "messages": [
            ToolMessage(
                content=json.dumps(search_payload, ensure_ascii=False),
                tool_call_id="call_search_1",
                name="search_used_vehicles",
            ),
            ToolMessage(
                content=json.dumps(contact_payload, ensure_ascii=False),
                tool_call_id="call_contact_1",
                name="create_executive_call_request",
            ),
        ]
    }

    patch = _sync_state_from_tool_messages(state)
    assert patch["active_search_filters"]["country_id"] == 5
    assert patch["selected_vehicle_id"] == 42
    assert patch["known_contact_profile"]["customer_name"] == "Roger Aguilar Pacheco"
    assert patch["last_contact_request"]["request_id"] == 8
    assert len(patch["search_history"]) == 1
    assert len(patch["contact_history"]) == 1


def test_contact_agent_reuses_persisted_profile_without_model_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    state = {
        "messages": [
            ToolMessage(
                content=json.dumps(
                    {
                        "ok": True,
                        "request_id": 8,
                        "vehicle_id": 42,
                        "customer_name": "Roger Aguilar Pacheco",
                        "phone_number": "+56941425034",
                        "preferred_call_time": "despues de las 19",
                        "created": True,
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="call_contact_2",
                name="create_executive_call_request",
            )
        ]
    }

    out = contact_agent_node(state)
    assert out["known_contact_profile"]["customer_name"] == "Roger Aguilar Pacheco"
    assert out["selected_vehicle_id"] == 42
    assert "OPENAI_API_KEY" in out["messages"][-1].content


def test_final_supervisor_uses_llm_rewriter(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    monkeypatch.setenv("FINAL_SUPERVISOR_USE_LLM", "true")

    class _FakeSupervisorLLM:
        def invoke(self, _messages):
            return AIMessage(content="Respuesta final limpia sin identificadores internos.")

    monkeypatch.setattr(car_sales_graph_module, "_llm", lambda: _FakeSupervisorLLM())
    out = final_supervisor_node(
        {
            "messages": [AIMessage(content="ID: 42\n- Texto técnico", id="ai-msg-1")],
            "conversation_language": "es",
        }
    )
    assert out["messages"][-1].id == "ai-msg-1"
    assert "identificadores internos" in out["messages"][-1].content.lower()


def test_final_supervisor_can_skip_llm_when_disabled(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    monkeypatch.setenv("FINAL_SUPERVISOR_USE_LLM", "false")

    def _raise_if_called():
        raise AssertionError("_llm should not be called when FINAL_SUPERVISOR_USE_LLM is false")

    monkeypatch.setattr(car_sales_graph_module, "_llm", _raise_if_called)
    out = final_supervisor_node({"messages": [AIMessage(content="Texto de prueba")]})
    assert out["conversation_language"] in {"und", "es", "en"}


def test_enforce_quote_tool_policy_overrides_wrong_country_id_and_make():
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_search_1",
                "name": "search_used_vehicles",
                "args": {"country_id": 4, "make": "Volkswagen", "mileage_km_max": 100000},
                "type": "tool_call",
            }
        ],
    )

    patched = _enforce_quote_tool_call_policy(
        response,
        active_filters={"mileage_km_max": 100000},
        runtime_country_id_override=5,
        runtime_make_override=None,
        runtime_clear_make=True,
        runtime_country_intent_detected=True,
        runtime_parallel_search_mode=False,
        conversation_language="es",
        catalog_lookup_in_current_turn=True,
    )

    args = patched.tool_calls[0]["args"]
    assert args["country_id"] == 5
    assert args["mileage_km_max"] == 100000
    assert "make" not in args


def test_enforce_quote_tool_policy_blocks_search_when_country_unresolved(monkeypatch):
    monkeypatch.setattr(
        car_sales_graph_module,
        "get_inventory_metadata",
        lambda db_path: {"countries": [{"id": 4, "name": "France"}, {"id": 5, "name": "Germany"}]},
    )
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_search_2",
                "name": "search_used_vehicles",
                "args": {"country_id": 4, "mileage_km_max": 100000},
                "type": "tool_call",
            }
        ],
    )

    patched = _enforce_quote_tool_call_policy(
        response,
        active_filters={"mileage_km_max": 100000},
        runtime_country_id_override=None,
        runtime_make_override=None,
        runtime_clear_make=False,
        runtime_country_intent_detected=True,
        runtime_parallel_search_mode=False,
        conversation_language="es",
        catalog_lookup_in_current_turn=True,
    )

    assert "país exacto" in patched.content.lower()
    assert "Germany" in patched.content
    assert not patched.tool_calls


def test_enforce_quote_tool_policy_forces_catalog_lookup_before_search():
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_search_3",
                "name": "search_used_vehicles",
                "args": {"country_id": 5, "mileage_km_max": 100000},
                "type": "tool_call",
            }
        ],
    )

    patched = _enforce_quote_tool_call_policy(
        response,
        active_filters={"mileage_km_max": 100000},
        runtime_country_id_override=5,
        runtime_make_override=None,
        runtime_clear_make=False,
        runtime_country_intent_detected=True,
        runtime_parallel_search_mode=False,
        conversation_language="es",
        catalog_lookup_in_current_turn=False,
    )

    assert patched.tool_calls
    assert patched.tool_calls[0]["name"] == "list_available_vehicle_filters"
    assert patched.tool_calls[0]["args"] == {}


def test_enforce_quote_tool_policy_keeps_explicit_make_when_country_changes():
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_search_4",
                "name": "search_used_vehicles",
                "args": {"country_id": 6, "make": "Volkswagen", "mileage_km_max": 100000},
                "type": "tool_call",
            }
        ],
    )

    patched = _enforce_quote_tool_call_policy(
        response,
        active_filters={"mileage_km_max": 100000, "make": "Audi"},
        runtime_country_id_override=5,
        runtime_make_override="Audi",
        runtime_clear_make=False,
        runtime_country_intent_detected=True,
        runtime_parallel_search_mode=False,
        conversation_language="es",
        catalog_lookup_in_current_turn=True,
    )

    args = patched.tool_calls[0]["args"]
    assert args["country_id"] == 5
    assert args["make"] == "Audi"
    assert args["mileage_km_max"] == 100000


def test_enforce_quote_tool_policy_parallel_mode_deduplicates_and_keeps_per_call_filters():
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_search_5",
                "name": "search_used_vehicles",
                "args": {"country_id": 6, "mileage_km_max": 100000, "limit": 5},
                "type": "tool_call",
            },
            {
                "id": "call_search_6",
                "name": "search_used_vehicles",
                "args": {"country_id": 6, "mileage_km_max": 100000, "limit": 5},
                "type": "tool_call",
            },
            {
                "id": "call_search_7",
                "name": "search_used_vehicles",
                "args": {"country_id": 5, "make": "Audi", "mileage_km_max": 100000, "limit": 5},
                "type": "tool_call",
            },
        ],
    )

    patched = _enforce_quote_tool_call_policy(
        response,
        active_filters={"country_id": 1, "make": "Toyota", "mileage_km_max": 50000},
        runtime_country_id_override=5,
        runtime_make_override="Audi",
        runtime_clear_make=False,
        runtime_country_intent_detected=True,
        runtime_parallel_search_mode=True,
        conversation_language="es",
        catalog_lookup_in_current_turn=True,
    )

    assert len(patched.tool_calls) == 2
    first_args = patched.tool_calls[0]["args"]
    second_args = patched.tool_calls[1]["args"]
    assert first_args == {"country_id": 6, "mileage_km_max": 100000, "limit": 5}
    assert second_args == {"country_id": 5, "make": "Audi", "mileage_km_max": 100000, "limit": 5}
