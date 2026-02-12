from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, trim_messages
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel
from typing_extensions import NotRequired

from app.db.vehicle_repository import (
    ALLOWED_FILTERS,
    DEFAULT_INVENTORY_DB,
    get_inventory_metadata,
)
from app.prompts.car_sales_prompts import (
    CONTACT_AGENT_SYSTEM_PROMPT,
    FINAL_RESPONSE_SYSTEM_PROMPT,
    QUOTE_AGENT_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
)
from app.tools.car_sales_tools import CONTACT_TOOLS, QUOTE_TOOLS


def _append_with_cap(current: list[Any] | None, new: list[Any] | None, cap: int) -> list[Any]:
    merged = list(current or [])
    merged.extend(list(new or []))
    if len(merged) > cap:
        return merged[-cap:]
    return merged


def _append_state_logs(current: list[str] | None, new: list[str] | None) -> list[str]:
    return [str(item) for item in _append_with_cap(current, new, cap=300)]


def _append_search_events(current: list[dict[str, Any]] | None, new: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return _append_with_cap(current, new, cap=100)


def _append_contact_events(
    current: list[dict[str, Any]] | None,
    new: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    return _append_with_cap(current, new, cap=100)


def _append_unique_strings(current: list[str] | None, new: list[str] | None) -> list[str]:
    merged = list(current or [])
    seen = {str(item) for item in merged}
    for item in new or []:
        value = str(item)
        if value in seen:
            continue
        seen.add(value)
        merged.append(value)
    if len(merged) > 2000:
        return merged[-2000:]
    return merged


def _merge_non_empty_dict(current: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(current or {})
    for key, value in (new or {}).items():
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            merged[key] = stripped
            continue
        merged[key] = value
    return merged


def _merge_updates(*updates: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for update in updates:
        if not update:
            continue
        merged.update(update)
    return merged


class CarSalesState(MessagesState):
    route: NotRequired[Literal["quote_agent", "contact_agent"]]
    active_flow: NotRequired[Literal["quote", "contact"]]
    conversation_language: NotRequired[str]
    quote_agent_turns: NotRequired[int]
    contact_agent_turns: NotRequired[int]
    quote_agent_human_count: NotRequired[int]
    contact_agent_human_count: NotRequired[int]
    active_search_filters: NotRequired[dict[str, Any]]
    last_vehicle_candidates: NotRequired[list[dict[str, Any]]]
    selected_vehicle_id: NotRequired[int | None]
    last_contact_request: NotRequired[dict[str, Any]]
    known_contact_profile: NotRequired[Annotated[dict[str, Any], _merge_non_empty_dict]]
    processed_tool_message_keys: NotRequired[Annotated[list[str], _append_unique_strings]]
    state_logs: NotRequired[Annotated[list[str], _append_state_logs]]
    search_history: NotRequired[Annotated[list[dict[str, Any]], _append_search_events]]
    contact_history: NotRequired[Annotated[list[dict[str, Any]], _append_contact_events]]
    runtime_country_id_override: NotRequired[int | None]
    runtime_make_override: NotRequired[str | None]
    runtime_clear_make: NotRequired[bool]
    runtime_country_intent_detected: NotRequired[bool]
    runtime_parallel_search_mode: NotRequired[bool]


class RouteDecision(BaseModel):
    route: Literal["quote_agent", "contact_agent"]


class QuoteRuntimeDirective(BaseModel):
    country_id_override: int | None = None
    make_override: str | None = None
    clear_make: bool = False
    country_intent_detected: bool = False
    parallel_search_mode: bool = False


class ConversationLanguageDecision(BaseModel):
    conversation_language: str | None = None


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
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "45"))
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
        timeout=timeout_seconds,
    )


def _max_agent_tool_iterations() -> int:
    return max(1, int(os.getenv("MAX_AGENT_TOOL_ITERATIONS", "8")))


def _max_quote_iterations_per_turn() -> int:
    return max(3, int(os.getenv("MAX_QUOTE_ITERATIONS_PER_TURN", "3")))


def _max_contact_iterations_per_turn() -> int:
    return max(3, int(os.getenv("MAX_CONTACT_ITERATIONS_PER_TURN", "3")))


def _trim_history(messages: list[BaseMessage]) -> list[BaseMessage]:
    max_messages = max(4, int(os.getenv("MAX_CONTEXT_MESSAGES", "18")))
    trimmer = trim_messages(
        strategy="last",
        max_tokens=max_messages,
        token_counter=len,
        start_on="human",
        include_system=False,
    )
    return trimmer.invoke(messages)


def _inventory_db_path() -> Path:
    return Path(os.getenv("DEALERSHIP_DB_PATH", str(DEFAULT_INVENTORY_DB)))


def _latest_human_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            return str(message.content)
    return ""


def _sanitize_language_code(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    code = raw_value.strip().lower().replace("_", "-")
    if not code:
        return None
    if len(code) > 16:
        return None
    for token in code.split("-"):
        if not token:
            return None
        if not token.isalnum():
            return None
    primary = code.split("-")[0]
    if len(primary) < 2 or len(primary) > 3:
        return None
    return code


def _infer_conversation_language_with_llm(
    messages: list[BaseMessage],
    current_language: str | None,
) -> str | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None

    latest_user_text = _latest_human_text(messages)
    if not latest_user_text:
        return _sanitize_language_code(current_language)

    try:
        system_prompt = """
You are a language inference assistant for chat state.

Return JSON only:
- conversation_language: BCP-47 language code in lowercase (for example: "es", "en", "pt", "fr", "es-cl"), or null.

Rules:
1. Infer the language that the assistant should use for the current turn.
2. Prioritize the latest user message.
3. If the user explicitly asks for another language, use that requested language.
4. If the language is unclear, keep current_language if available; otherwise return null.
""".strip()

        decision = _llm().with_structured_output(ConversationLanguageDecision).invoke(
            [
                SystemMessage(content=system_prompt),
                SystemMessage(content=f"current_language={current_language or 'null'}"),
            ]
            + _trim_history(messages)
        )
        return _sanitize_language_code(decision.conversation_language)
    except Exception:
        return None


def _resolve_conversation_language(state: CarSalesState) -> str:
    existing = _sanitize_language_code(state.get("conversation_language"))
    inferred = _infer_conversation_language_with_llm(state.get("messages", []), existing)
    if inferred:
        return inferred
    if existing:
        return existing

    default_language = _sanitize_language_code(os.getenv("DEFAULT_CONVERSATION_LANGUAGE", ""))
    if default_language:
        return default_language
    return "und"


def _count_human_messages(messages: list[BaseMessage]) -> int:
    return sum(1 for message in messages if getattr(message, "type", None) == "human")


def _is_new_user_turn(state: CarSalesState, counter_key: str) -> tuple[bool, int]:
    messages = state.get("messages", [])
    human_count = _count_human_messages(messages)
    previous_human_count = int(state.get(counter_key, 0))
    last_is_human = bool(messages) and getattr(messages[-1], "type", None) == "human"
    return human_count > previous_human_count or last_is_human, human_count


def _message_content_as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
        return "\n".join(part for part in parts if part)
    return str(content)


def _safe_json_loads(raw: str) -> Any | None:
    try:
        return json.loads(raw)
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _sanitize_search_filters(raw_filters: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in raw_filters.items():
        if key not in ALLOWED_FILTERS:
            continue
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            sanitized[key] = stripped
        else:
            sanitized[key] = value
    return sanitized


def _compact_vehicle_candidates(raw_rows: list[dict[str, Any]], *, max_items: int = 12) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        vehicle_id = _safe_int(row.get("id"))
        if vehicle_id is None:
            continue
        candidates.append(
            {
                "id": vehicle_id,
                "make": str(row.get("make", "")).strip(),
                "model": str(row.get("model", "")).strip(),
                "year": _safe_int(row.get("year")),
                "mileage_km": _safe_int(row.get("mileage_km")),
                "price_usd": _safe_int(row.get("price_usd")),
                "country_of_origin": str(row.get("country_of_origin", "")).strip(),
            }
        )
        if len(candidates) >= max_items:
            break
    return candidates


def _sync_state_from_tool_messages(state: CarSalesState) -> dict[str, Any]:
    messages = state.get("messages", [])
    processed = {str(item) for item in state.get("processed_tool_message_keys", [])}

    new_processed: list[str] = []
    search_events: list[dict[str, Any]] = []
    contact_events: list[dict[str, Any]] = []
    logs: list[str] = []

    active_search_filters = state.get("active_search_filters")
    last_vehicle_candidates = state.get("last_vehicle_candidates")
    selected_vehicle_id = state.get("selected_vehicle_id")
    last_contact_request = state.get("last_contact_request")
    known_contact_profile = dict(state.get("known_contact_profile", {}))

    for index, message in enumerate(messages):
        if getattr(message, "type", None) != "tool":
            continue

        tool_message_key = str(getattr(message, "tool_call_id", None) or f"tool_msg_{index}")
        if tool_message_key in processed:
            continue

        payload = _safe_json_loads(_message_content_as_text(getattr(message, "content", "")))
        new_processed.append(tool_message_key)
        if not isinstance(payload, dict):
            continue

        if isinstance(payload.get("vehicles"), list):
            vehicles = _compact_vehicle_candidates(payload.get("vehicles", []))
            filters_raw = payload.get("filters_used")
            filters = _sanitize_search_filters(filters_raw) if isinstance(filters_raw, dict) else {}
            if filters:
                active_search_filters = filters
            last_vehicle_candidates = vehicles
            search_events.append(
                {
                    "tool_message_key": tool_message_key,
                    "filters_used": filters,
                    "count": _safe_int(payload.get("count")) or len(vehicles),
                    "vehicle_ids": [item["id"] for item in vehicles if isinstance(item.get("id"), int)],
                }
            )
            logs.append(
                "search_used_vehicles processed: "
                f"count={len(vehicles)} filters={json.dumps(filters, ensure_ascii=False)}"
            )
            continue

        if payload.get("found") is True and isinstance(payload.get("vehicle"), dict):
            details = payload.get("vehicle", {})
            vehicle_id = _safe_int(details.get("id"))
            if vehicle_id is not None:
                selected_vehicle_id = vehicle_id
                logs.append(f"get_vehicle_details processed: selected_vehicle_id={vehicle_id}")
            continue

        if payload.get("ok") is True and _safe_int(payload.get("request_id")) is not None:
            request_id = _safe_int(payload.get("request_id"))
            vehicle_id = _safe_int(payload.get("vehicle_id"))
            customer_name = str(payload.get("customer_name", "")).strip()
            phone_number = str(payload.get("phone_number", "")).strip()
            preferred_call_time = str(payload.get("preferred_call_time", "")).strip()

            if vehicle_id is not None:
                selected_vehicle_id = vehicle_id

            if request_id is not None:
                last_contact_request = {
                    "request_id": request_id,
                    "vehicle_id": vehicle_id,
                    "customer_name": customer_name,
                    "phone_number": phone_number,
                    "preferred_call_time": preferred_call_time,
                    "created": bool(payload.get("created", True)),
                }
                contact_events.append(last_contact_request)
                logs.append(
                    f"create_executive_call_request processed: request_id={request_id} vehicle_id={vehicle_id}"
                )

            known_contact_profile = _merge_non_empty_dict(
                known_contact_profile,
                {
                    "customer_name": customer_name,
                    "phone_number": phone_number,
                    "preferred_call_time": preferred_call_time,
                },
            )

    patch: dict[str, Any] = {}
    if new_processed:
        patch["processed_tool_message_keys"] = new_processed
    if logs:
        patch["state_logs"] = logs
    if search_events:
        patch["search_history"] = search_events
    if contact_events:
        patch["contact_history"] = contact_events
    if isinstance(active_search_filters, dict):
        patch["active_search_filters"] = active_search_filters
    if isinstance(last_vehicle_candidates, list):
        patch["last_vehicle_candidates"] = last_vehicle_candidates
    if selected_vehicle_id is not None:
        patch["selected_vehicle_id"] = selected_vehicle_id
    if isinstance(last_contact_request, dict):
        patch["last_contact_request"] = last_contact_request
    if known_contact_profile:
        patch["known_contact_profile"] = known_contact_profile
    return patch


def _render_state_context_block(state: CarSalesState) -> str:
    lines: list[str] = []

    conversation_language = state.get("conversation_language")
    if isinstance(conversation_language, str) and conversation_language.strip():
        lines.append(f"conversation_language={conversation_language.strip().lower()}")

    active_filters = state.get("active_search_filters")
    if isinstance(active_filters, dict) and active_filters:
        lines.append("Persisted active filters:")
        lines.append(json.dumps(active_filters, ensure_ascii=False))

    candidates = state.get("last_vehicle_candidates")
    if isinstance(candidates, list) and candidates:
        compact = candidates[:5]
        lines.append("Recent vehicles in context:")
        lines.append(json.dumps(compact, ensure_ascii=False))

    selected_vehicle_id = state.get("selected_vehicle_id")
    if isinstance(selected_vehicle_id, int):
        lines.append(f"selected_vehicle_id={selected_vehicle_id}")

    contact_profile = state.get("known_contact_profile")
    if isinstance(contact_profile, dict) and contact_profile:
        lines.append("Persisted contact profile:")
        lines.append(json.dumps(contact_profile, ensure_ascii=False))

    return "\n".join(lines).strip()


def _extract_last_contact_profile(messages: list[BaseMessage]) -> dict[str, str] | None:
    for message in reversed(messages):
        if getattr(message, "type", None) != "ai":
            continue
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in reversed(tool_calls):
            if call.get("name") != "create_executive_call_request":
                continue
            args = call.get("args")
            if isinstance(args, str):
                args = _safe_json_loads(args)
            if not isinstance(args, dict):
                continue
            customer_name = str(args.get("customer_name", "")).strip()
            phone_number = str(args.get("phone_number", "")).strip()
            preferred_call_time = str(args.get("preferred_call_time", "")).strip()
            if customer_name and phone_number and preferred_call_time:
                return {
                    "customer_name": customer_name,
                    "phone_number": phone_number,
                    "preferred_call_time": preferred_call_time,
                }

    for message in reversed(messages):
        if getattr(message, "type", None) != "tool":
            continue
        payload = _safe_json_loads(_message_content_as_text(getattr(message, "content", "")))
        if not isinstance(payload, dict) or not payload.get("ok"):
            continue
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


def _extract_recent_vehicle_candidates(messages: list[BaseMessage], *, max_items: int = 8) -> list[dict[str, Any]]:
    for message in reversed(messages):
        if getattr(message, "type", None) != "tool":
            continue
        payload = _safe_json_loads(_message_content_as_text(getattr(message, "content", "")))
        if not isinstance(payload, dict):
            continue
        vehicles = payload.get("vehicles")
        if not isinstance(vehicles, list):
            continue

        candidates: list[dict[str, Any]] = []
        for row in vehicles:
            if not isinstance(row, dict):
                continue
            raw_id = row.get("id")
            if not isinstance(raw_id, int):
                continue
            candidates.append(
                {
                    "id": raw_id,
                    "make": str(row.get("make", "")).strip(),
                    "model": str(row.get("model", "")).strip(),
                    "year": row.get("year"),
                }
            )
        if candidates:
            return candidates[:max_items]
    return []


def _coerce_tool_call_args(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, dict):
        return dict(raw_args)
    if isinstance(raw_args, str):
        parsed = _safe_json_loads(raw_args)
        if isinstance(parsed, dict):
            return dict(parsed)
    return {}


def _has_tool_result_in_current_turn(messages: list[BaseMessage], tool_name: str) -> bool:
    for message in reversed(messages):
        message_type = getattr(message, "type", None)
        if message_type == "human":
            break
        if message_type != "tool":
            continue
        current_name = str(getattr(message, "name", "")).strip()
        if current_name == tool_name:
            return True
    return False


def _enforce_quote_tool_call_policy(
    response: AIMessage,
    *,
    active_filters: dict[str, Any],
    runtime_country_id_override: int | None,
    runtime_make_override: str | None,
    runtime_clear_make: bool,
    runtime_country_intent_detected: bool,
    runtime_parallel_search_mode: bool,
    conversation_language: str,
    catalog_lookup_in_current_turn: bool,
) -> AIMessage:
    tool_calls = getattr(response, "tool_calls", None) or []
    if not tool_calls:
        return response

    has_search_call = any(
        isinstance(call, dict) and call.get("name") == "search_used_vehicles"
        for call in tool_calls
    )
    search_call_count = sum(
        1 for call in tool_calls if isinstance(call, dict) and call.get("name") == "search_used_vehicles"
    )
    effective_parallel_mode = runtime_parallel_search_mode or search_call_count > 1
    if has_search_call and not catalog_lookup_in_current_turn:
        first_search_call = next(
            (
                call
                for call in tool_calls
                if isinstance(call, dict) and call.get("name") == "search_used_vehicles"
            ),
            None,
        )
        base_call_id = str((first_search_call or {}).get("id") or "call_search")
        return AIMessage(
            content="",
            id=getattr(response, "id", None),
            tool_calls=[
                {
                    "id": f"{base_call_id}_catalog",
                    "name": "list_available_vehicle_filters",
                    "args": {},
                    "type": "tool_call",
                }
            ],
        )

    if (
        runtime_country_intent_detected
        and runtime_country_id_override is None
        and not effective_parallel_mode
    ):
        if has_search_call:
            try:
                metadata = get_inventory_metadata(db_path=_inventory_db_path())
                countries = metadata.get("countries", [])
            except Exception:
                countries = []
            country_names = [str(item.get("name", "")).strip() for item in countries if str(item.get("name", "")).strip()]
            options = ", ".join(country_names[:12])
            in_spanish = str(conversation_language).lower().startswith("es")
            if in_spanish:
                content = (
                    "Para buscar por país/origen necesito que confirmes el país exacto del catálogo."
                    + (f" Países disponibles: {options}." if options else "")
                )
            else:
                content = (
                    "To search by country/origin I need you to confirm the exact catalog country."
                    + (f" Available countries: {options}." if options else "")
                )
            return AIMessage(content=content, id=getattr(response, "id", None))

    patched_calls: list[dict[str, Any]] = []
    seen_search_args: set[str] = set()
    changed = False

    for call in tool_calls:
        if not isinstance(call, dict):
            patched_calls.append(call)
            continue

        if call.get("name") != "search_used_vehicles":
            patched_calls.append(call)
            continue

        args = _coerce_tool_call_args(call.get("args"))
        if effective_parallel_mode:
            enforced_args = _sanitize_search_filters(args)
        else:
            enforced_args = _sanitize_search_filters(active_filters)
            enforced_args.update(_sanitize_search_filters(args))

            if runtime_country_id_override is not None:
                enforced_args["country_id"] = runtime_country_id_override
            elif runtime_country_intent_detected:
                enforced_args.pop("country_id", None)

            if runtime_clear_make:
                enforced_args.pop("make", None)
            if isinstance(runtime_make_override, str) and runtime_make_override.strip():
                enforced_args["make"] = runtime_make_override.strip()

        if "limit" not in enforced_args:
            enforced_args["limit"] = 5

        dedup_key = json.dumps(enforced_args, sort_keys=True, ensure_ascii=False)
        if dedup_key in seen_search_args:
            changed = True
            continue
        seen_search_args.add(dedup_key)

        patched_call = dict(call)
        patched_call["args"] = enforced_args
        patched_calls.append(patched_call)

        if enforced_args != args:
            changed = True

    if not changed:
        return response

    try:
        return response.model_copy(update={"tool_calls": patched_calls}, deep=True)
    except Exception:
        response.tool_calls = patched_calls
        return response


def _infer_quote_runtime_directive(messages: list[BaseMessage]) -> QuoteRuntimeDirective:
    if not os.getenv("OPENAI_API_KEY"):
        return QuoteRuntimeDirective()

    latest_user_text = _latest_human_text(messages)
    if not latest_user_text:
        return QuoteRuntimeDirective()

    try:
        metadata = get_inventory_metadata(db_path=_inventory_db_path())
        countries = metadata.get("countries", [])
        makes_raw = metadata.get("makes", [])
        if not countries:
            return QuoteRuntimeDirective()

        valid_country_ids = {int(item["id"]) for item in countries if item.get("id") is not None}
        valid_makes_by_key = {
            str(make).strip().lower(): str(make).strip()
            for make in makes_raw
            if isinstance(make, str) and make.strip()
        }
        countries_table = "\n".join(
            f"- id={item['id']} name={item['name']}"
            for item in countries
            if item.get("id") is not None and str(item.get("name", "")).strip()
        )
        makes_table = "\n".join(f"- {name}" for name in sorted(valid_makes_by_key.values()))
        system_prompt = f"""
You are an intent parser for vehicle search filters.

Country catalog (use only these IDs):
{countries_table}

Make catalog (use only these names):
{makes_table}

Return JSON with:
- country_id_override: integer or null
- make_override: string or null
- clear_make: boolean
- country_intent_detected: boolean
- parallel_search_mode: boolean

Rules:
1. If the LAST user message contains explicit or implicit country/origin/nationality intent
   (including demonyms), set country_intent_detected=true and assign the correct country_id_override when possible.
2. If the LAST user message explicitly asks for a brand, set make_override to the exact catalog make name.
3. If the user asks for a general country-based search and does not ask for a brand, set clear_make=true.
4. If the user explicitly asks for a brand, set clear_make=false.
5. If there is no explicit country/origin intent, set country_id_override=null and country_intent_detected=false.
6. Never return IDs outside the catalog and never return make names outside the catalog.
7. Set parallel_search_mode=true only when the user asks for two or more independent searches in the same message.
   In parallel_search_mode, set country_id_override=null, make_override=null, clear_make=false, and country_intent_detected=false.
""".strip()

        directive = _llm().with_structured_output(QuoteRuntimeDirective).invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=latest_user_text)]
        )
        if directive.country_id_override is not None and directive.country_id_override not in valid_country_ids:
            directive.country_id_override = None
        if directive.make_override is not None:
            normalized_key = str(directive.make_override).strip().lower()
            directive.make_override = valid_makes_by_key.get(normalized_key)
        if directive.parallel_search_mode:
            directive.country_id_override = None
            directive.make_override = None
            directive.clear_make = False
            directive.country_intent_detected = False
        if directive.make_override:
            directive.clear_make = False
        if directive.country_intent_detected and directive.country_id_override is None:
            directive.clear_make = True
        return directive
    except Exception:
        return QuoteRuntimeDirective()


def router_node(state: CarSalesState) -> CarSalesState:
    sync_update = _sync_state_from_tool_messages(state)
    state_ctx = _merge_updates(state, sync_update)
    messages = _trim_history(state_ctx["messages"])
    conversation_language = _resolve_conversation_language(state_ctx)

    if not os.getenv("OPENAI_API_KEY"):
        return _merge_updates(
            sync_update,
            {"route": "quote_agent", "conversation_language": conversation_language},
        )

    try:
        prompt_messages: list[BaseMessage] = [SystemMessage(content=ROUTER_SYSTEM_PROMPT)]
        if state_ctx.get("active_flow") == "contact":
            prompt_messages.append(
                SystemMessage(
                    content=(
                        "Conversation state: previous active flow is `contact`. "
                        "If the latest user message naturally continues that flow, keep `contact_agent`."
                    )
                )
            )

        prompt_messages.append(
            SystemMessage(
                content=f"Conversation language code is `{conversation_language}`."
            )
        )

        persisted_context = _render_state_context_block(state_ctx)
        if persisted_context:
            prompt_messages.append(
                SystemMessage(content="Persisted thread context:\n" + persisted_context)
            )

        decision = _llm().with_structured_output(RouteDecision).invoke(
            prompt_messages + messages
        )
        return _merge_updates(
            sync_update,
            {"route": decision.route, "conversation_language": conversation_language},
        )
    except Exception:
        return _merge_updates(
            sync_update,
            {"route": "quote_agent", "conversation_language": conversation_language},
        )


def route_from_router(state: CarSalesState) -> str:
    return state.get("route", "quote_agent")


def quote_agent_node(state: CarSalesState) -> CarSalesState:
    sync_update = _sync_state_from_tool_messages(state)
    state_ctx = _merge_updates(state, sync_update)
    messages = _trim_history(state_ctx["messages"])
    is_new_user_turn, human_count = _is_new_user_turn(state_ctx, "quote_agent_human_count")
    active_filters = dict(state_ctx.get("active_search_filters", {}))
    conversation_language = _resolve_conversation_language(state_ctx)

    if is_new_user_turn:
        turns = 1
        runtime_directive = _infer_quote_runtime_directive(state_ctx["messages"])
        runtime_country_id_override = runtime_directive.country_id_override
        runtime_make_override = runtime_directive.make_override
        runtime_clear_make = runtime_directive.clear_make
        runtime_country_intent_detected = runtime_directive.country_intent_detected
        runtime_parallel_search_mode = runtime_directive.parallel_search_mode

        if runtime_parallel_search_mode:
            # For multi-intent turns, avoid leaking previous single-intent filters.
            active_filters = {}

        if runtime_country_id_override is not None:
            active_filters["country_id"] = runtime_country_id_override
        if runtime_country_intent_detected and runtime_country_id_override is None:
            active_filters.pop("country_id", None)
        if runtime_clear_make:
            active_filters.pop("make", None)
        if isinstance(runtime_make_override, str) and runtime_make_override.strip():
            active_filters["make"] = runtime_make_override.strip()
    else:
        turns = int(state_ctx.get("quote_agent_turns", 0)) + 1
        runtime_country_id_override = state_ctx.get("runtime_country_id_override")
        runtime_make_override = state_ctx.get("runtime_make_override")
        runtime_clear_make = bool(state_ctx.get("runtime_clear_make", False))
        runtime_country_intent_detected = bool(state_ctx.get("runtime_country_intent_detected", False))
        runtime_parallel_search_mode = bool(state_ctx.get("runtime_parallel_search_mode", False))

    state_updates = {
        "route": "quote_agent",
        "active_flow": "quote",
        "conversation_language": conversation_language,
        "quote_agent_turns": turns,
        "quote_agent_human_count": human_count,
        "runtime_country_id_override": runtime_country_id_override,
        "runtime_make_override": runtime_make_override,
        "runtime_clear_make": runtime_clear_make,
        "runtime_country_intent_detected": runtime_country_intent_detected,
        "runtime_parallel_search_mode": runtime_parallel_search_mode,
        "active_search_filters": active_filters,
    }

    if turns > _max_quote_iterations_per_turn():
        return _merge_updates(
            sync_update,
            state_updates,
            {
            "messages": [
                AIMessage(
                    content=(
                        "Para evitar búsquedas automáticas en cadena, detengo este turno aquí. "
                        "Puedo reintentar con un ajuste puntual (país, año, km, precio o marca)."
                    )
                )
            ],
            },
        )

    if turns > _max_agent_tool_iterations():
        return _merge_updates(
            sync_update,
            state_updates,
            {
            "messages": [
                AIMessage(
                    content=(
                        "Detuve la ejecución para evitar un bucle de herramientas. "
                        "¿Quieres que reintente con filtros más claros?"
                    )
                )
            ],
            },
        )

    if not os.getenv("OPENAI_API_KEY"):
        return _merge_updates(
            sync_update,
            state_updates,
            {
            "messages": [
                AIMessage(
                    content=(
                        "Para usar el agente de cotización en LangSmith/Studio necesitas `OPENAI_API_KEY`. "
                        "Configúrala en `.env` y vuelve a ejecutar."
                    )
                )
            ],
            },
        )

    runtime_rules: list[str] = []
    if active_filters:
        runtime_rules.append(
            "- Use these persisted active filters as your default search baseline: "
            + json.dumps(active_filters, ensure_ascii=False)
            + "."
        )
    if runtime_parallel_search_mode:
        runtime_rules.append(
            "- The latest user message contains multiple independent search intents. "
            "Run separate search_used_vehicles calls (one call per intent) in this turn."
        )
        runtime_rules.append(
            "- Do not force one intent over the others, and do not mix constraints between intents."
        )
    if runtime_country_id_override is not None:
        runtime_rules.append(
            f"- Replace any previous country filter and use country_id={runtime_country_id_override}."
        )
    if runtime_country_intent_detected and runtime_country_id_override is None:
        runtime_rules.append(
            "- The user requested country/origin, but there is no valid country_id for this turn. "
            "Do not reuse previous country_id; ask for country clarification using catalog values before searching."
        )
    if runtime_clear_make:
        runtime_rules.append("- Do not apply a make filter unless the user explicitly asks for a brand.")
    if isinstance(runtime_make_override, str) and runtime_make_override.strip():
        runtime_rules.append(
            f"- Enforce make={runtime_make_override.strip()} exactly; do not broaden results to other brands."
        )
    runtime_rules.append(
        "- Avoid speculative chained searches (for example, trying brands on your own). "
        "If no results are found, explain active filters and request one concrete adjustment."
    )

    prompt_messages = [SystemMessage(content=QUOTE_AGENT_SYSTEM_PROMPT)]
    prompt_messages.append(
        SystemMessage(
            content=(
                f"Conversation language code is `{conversation_language}`. "
                f"Write your response in that language."
            )
        )
    )
    persisted_context = _render_state_context_block(_merge_updates(state_ctx, {"active_search_filters": active_filters}))
    if persisted_context:
        prompt_messages.append(
            SystemMessage(content="Persisted thread memory:\n" + persisted_context)
        )
    if runtime_rules:
        prompt_messages.append(
            SystemMessage(
                content="Execution rules for this turn:\n" + "\n".join(runtime_rules)
            )
        )

    catalog_lookup_in_current_turn = _has_tool_result_in_current_turn(
        state_ctx["messages"],
        "list_available_vehicle_filters",
    )
    response = _llm().bind_tools(QUOTE_TOOLS).invoke(prompt_messages + messages)
    response = _enforce_quote_tool_call_policy(
        response,
        active_filters=active_filters,
        runtime_country_id_override=runtime_country_id_override,
        runtime_make_override=runtime_make_override,
        runtime_clear_make=runtime_clear_make,
        runtime_country_intent_detected=runtime_country_intent_detected,
        runtime_parallel_search_mode=runtime_parallel_search_mode,
        conversation_language=conversation_language,
        catalog_lookup_in_current_turn=catalog_lookup_in_current_turn,
    )
    return _merge_updates(sync_update, state_updates, {"messages": [response]})


def contact_agent_node(state: CarSalesState) -> CarSalesState:
    sync_update = _sync_state_from_tool_messages(state)
    state_ctx = _merge_updates(state, sync_update)
    messages = _trim_history(state_ctx["messages"])
    is_new_user_turn, human_count = _is_new_user_turn(state_ctx, "contact_agent_human_count")
    conversation_language = _resolve_conversation_language(state_ctx)

    if is_new_user_turn:
        turns = 1
    else:
        turns = int(state_ctx.get("contact_agent_turns", 0)) + 1

    state_updates: dict[str, Any] = {
        "route": "contact_agent",
        "active_flow": "contact",
        "conversation_language": conversation_language,
        "contact_agent_turns": turns,
        "contact_agent_human_count": human_count,
    }

    if turns > _max_contact_iterations_per_turn():
        return _merge_updates(
            sync_update,
            state_updates,
            {
            "messages": [
                AIMessage(
                    content=(
                        "Para evitar un bucle, necesito solo el dato faltante para cerrar la solicitud "
                        "(vehículo o confirmación de contacto)."
                    )
                )
            ],
            },
        )

    if turns > _max_agent_tool_iterations():
        return _merge_updates(
            sync_update,
            state_updates,
            {
            "messages": [
                AIMessage(
                    content=(
                        "Detuve la ejecución para evitar un bucle de herramientas. "
                        "Confirmemos los datos de contacto y el ID del vehículo."
                    )
                )
            ],
            },
        )

    if not os.getenv("OPENAI_API_KEY"):
        return _merge_updates(
            sync_update,
            state_updates,
            {
            "messages": [
                AIMessage(
                    content=(
                        "Para usar el agente de contacto en LangSmith/Studio necesitas `OPENAI_API_KEY`. "
                        "Configúrala en `.env` y vuelve a ejecutar."
                    )
                )
            ],
            },
        )

    contact_profile_raw = state_ctx.get("known_contact_profile")
    contact_profile = contact_profile_raw if isinstance(contact_profile_raw, dict) else None
    if not contact_profile:
        contact_profile = _extract_last_contact_profile(state_ctx["messages"])

    recent_candidates_raw = state_ctx.get("last_vehicle_candidates")
    recent_candidates = (
        recent_candidates_raw
        if isinstance(recent_candidates_raw, list) and recent_candidates_raw
        else _extract_recent_vehicle_candidates(state_ctx["messages"])
    )

    selected_vehicle_id = _safe_int(state_ctx.get("selected_vehicle_id"))
    if selected_vehicle_id is None and len(recent_candidates) == 1:
        selected_vehicle_id = _safe_int(recent_candidates[0].get("id"))
    if selected_vehicle_id is not None:
        state_updates["selected_vehicle_id"] = selected_vehicle_id

    runtime_rules: list[str] = []
    if contact_profile:
        runtime_rules.append(
            "Persisted contact profile available:\n"
            f"- customer_name: {contact_profile['customer_name']}\n"
            f"- phone_number: {contact_profile['phone_number']}\n"
            f"- preferred_call_time: {contact_profile['preferred_call_time']}\n"
            "- If the user does not change these values, reuse them and do not ask again."
        )
        state_updates["known_contact_profile"] = contact_profile

    if selected_vehicle_id is not None:
        runtime_rules.append(
            f"- Target vehicle inferred from conversation memory: vehicle_id={selected_vehicle_id}."
        )

    if len(recent_candidates) > 1 and selected_vehicle_id is None:
        runtime_rules.append(
            "There are multiple vehicles in recent quote context and no selected vehicle yet. "
            "If the user asks for contact, request only minimal vehicle disambiguation."
        )

    prompt_messages = [SystemMessage(content=CONTACT_AGENT_SYSTEM_PROMPT)]
    prompt_messages.append(
        SystemMessage(
            content=(
                f"Conversation language code is `{conversation_language}`. "
                f"Write your response in that language."
            )
        )
    )
    persisted_context = _render_state_context_block(state_ctx)
    if persisted_context:
        prompt_messages.append(SystemMessage(content="Persisted thread memory:\n" + persisted_context))
    if runtime_rules:
        prompt_messages.append(
            SystemMessage(content="Execution context for this turn:\n" + "\n".join(runtime_rules))
        )

    response = _llm().bind_tools(CONTACT_TOOLS).invoke(prompt_messages + messages)
    return _merge_updates(sync_update, state_updates, {"messages": [response]})


def final_supervisor_node(state: CarSalesState) -> CarSalesState:
    sync_update = _sync_state_from_tool_messages(state)
    state_ctx = _merge_updates(state, sync_update)
    conversation_language = _resolve_conversation_language(state_ctx)
    messages = state_ctx.get("messages", [])

    if not messages:
        return _merge_updates(sync_update, {"conversation_language": conversation_language})

    last_message = messages[-1]
    if getattr(last_message, "type", None) != "ai":
        return _merge_updates(sync_update, {"conversation_language": conversation_language})

    draft_text = _message_content_as_text(getattr(last_message, "content", "")).strip()
    last_message_id = getattr(last_message, "id", None)
    if not draft_text:
        return _merge_updates(sync_update, {"conversation_language": conversation_language})

    revised_text = draft_text
    use_llm_rewriter = os.getenv("FINAL_SUPERVISOR_USE_LLM", "true").strip().lower() == "true"
    if use_llm_rewriter and os.getenv("OPENAI_API_KEY"):
        try:
            latest_user_text = _latest_human_text(messages).strip()
            active_filters = state_ctx.get("active_search_filters")
            supervisor_context: list[BaseMessage] = [
                SystemMessage(content=FINAL_RESPONSE_SYSTEM_PROMPT),
                SystemMessage(
                    content=(
                        f"Conversation language code is `{conversation_language}`. "
                        "Write the final customer answer in that same language."
                    )
                ),
            ]
            if latest_user_text:
                supervisor_context.append(
                    SystemMessage(
                        content=(
                            "Latest user request that must be respected exactly:\n"
                            f"{latest_user_text}"
                        )
                    )
                )
            if isinstance(active_filters, dict) and active_filters:
                supervisor_context.append(
                    SystemMessage(
                        content=(
                            "Active search filters used by the system (internal reference only):\n"
                            f"{json.dumps(active_filters, ensure_ascii=False)}"
                        )
                    )
                )
            revised_response = _llm().invoke(
                supervisor_context + [HumanMessage(content=draft_text)]
            )
            revised_text = _message_content_as_text(revised_response.content).strip() or draft_text
        except Exception:
            revised_text = draft_text

    final_text = " ".join(str(revised_text).split()).strip() or " ".join(str(draft_text).split()).strip()
    if not final_text:
        final_text = draft_text

    if final_text == draft_text:
        return _merge_updates(sync_update, {"conversation_language": conversation_language})

    replacement_message = AIMessage(content=final_text, id=last_message_id)
    return _merge_updates(
        sync_update,
        {
            "conversation_language": conversation_language,
            # Reuse the previous AI message id so MessagesState reducer replaces it
            # instead of appending a second user-visible assistant turn.
            "messages": [replacement_message],
        },
    )


def _route_after_agent(state: CarSalesState, tools_node_name: str) -> str:
    if not state.get("messages"):
        return END

    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []
    if tool_calls:
        return tools_node_name
    if getattr(last_message, "type", None) == "ai":
        return "final_supervisor"
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
    builder.add_node("final_supervisor", final_supervisor_node)

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
            "final_supervisor": "final_supervisor",
            END: END,
        },
    )
    builder.add_edge("quote_tools", "quote_agent")

    builder.add_conditional_edges(
        "contact_agent",
        route_after_contact_agent,
        {
            "contact_tools": "contact_tools",
            "final_supervisor": "final_supervisor",
            END: END,
        },
    )
    builder.add_edge("contact_tools", "contact_agent")
    builder.add_edge("final_supervisor", END)

    return builder.compile()


graph = build_graph()
