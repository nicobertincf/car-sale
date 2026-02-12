import json

from langchain_core.messages import AIMessage, ToolMessage

from app.car_sales_graph import (
    contact_agent_node,
    final_supervisor_node,
    _extract_last_contact_profile,
    _extract_recent_vehicle_candidates,
    _match_vehicle_candidates,
    _sanitize_final_response_text,
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

    matches = _match_vehicle_candidates("quiero que me contacten por el peugeot 3008 igual", candidates)
    assert matches == [54, 24]


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


def test_sanitize_final_response_text_removes_ids_and_list_style():
    raw_text = """
ID: 53
- Audi A4 2021 con 94,150 km y precio de $16,077.
ID de solicitud: 10
Te contactaremos en la tarde.
"""
    sanitized = _sanitize_final_response_text(raw_text)
    assert "ID:" not in sanitized
    assert "solicitud" not in sanitized.lower()
    assert "- " not in sanitized
    assert "\n" not in sanitized
    assert "Audi A4" in sanitized


def test_final_supervisor_node_masks_ids_without_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    draft = """
ID: 42
1. Volkswagen Tiguan 2024, 69,709 km, $17,685.
ID de solicitud: 9
Te contactaremos en la tarde.
"""
    out = final_supervisor_node({"messages": [AIMessage(content=draft)], "conversation_language": "es"})
    assert out["conversation_language"] == "es"
    assert out["messages"]
    final_text = out["messages"][-1].content
    assert "ID" not in final_text
    assert "request_id" not in final_text
    assert "1." not in final_text


def test_final_supervisor_keeps_same_message_id_for_replacement(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = final_supervisor_node(
        {
            "messages": [AIMessage(content="ID: 42\n- Texto", id="ai-msg-1")],
            "conversation_language": "es",
        }
    )
    assert out["messages"][-1].id == "ai-msg-1"
