from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from app.db.vehicle_repository import (
    ALLOWED_FILTERS,
    DEFAULT_INVENTORY_DB,
    create_contact_request,
    get_vehicle_by_id,
    get_inventory_metadata,
    search_vehicles,
)

_SCHEMA_READY_PATHS: set[str] = set()
LOGGER = logging.getLogger("car_sales_tools")


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?;
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name});").fetchall()}


def _ensure_inventory_schema(db_path: Path) -> None:
    path_key = str(db_path.resolve())
    if path_key in _SCHEMA_READY_PATHS:
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from scripts.init_sqlite_db import initialize_database
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Could not import DB initialization utilities. "
            "Run from project root: python3 scripts/init_sqlite_db.py"
        ) from exc

    if not db_path.exists():
        initialize_database(db_path=db_path, seed_count=60)
        _SCHEMA_READY_PATHS.add(path_key)
        return

    with sqlite3.connect(db_path) as conn:
        has_countries = _table_exists(conn, "countries")
        has_vehicles = _table_exists(conn, "vehicles")
        if has_countries and has_vehicles and "country_id" in _column_names(conn, "vehicles"):
            _SCHEMA_READY_PATHS.add(path_key)
            return

        is_legacy = has_vehicles and "country_of_origin" in _column_names(conn, "vehicles")

    if is_legacy:
        try:
            from scripts.migrate_inventory_db import migrate_inventory_database
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Could not import DB migration utilities. "
                "Run from project root: python3 scripts/migrate_inventory_db.py --db-path data/dealership.db"
            ) from exc
        migrate_inventory_database(db_path)
        _SCHEMA_READY_PATHS.add(path_key)
        return

    initialize_database(db_path=db_path, seed_count=60)
    _SCHEMA_READY_PATHS.add(path_key)


def _inventory_db_path() -> Path:
    db_path = Path(os.getenv("DEALERSHIP_DB_PATH", DEFAULT_INVENTORY_DB))
    _ensure_inventory_schema(db_path)
    return db_path


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _mask_phone(phone_number: str) -> str:
    digits = re.sub(r"\D", "", phone_number)
    if len(digits) <= 4:
        return "***"
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"


def _safe_tool_args(raw_args: dict[str, Any]) -> dict[str, Any]:
    safe_args = dict(raw_args)
    if "phone_number" in safe_args and isinstance(safe_args["phone_number"], str):
        safe_args["phone_number"] = _mask_phone(safe_args["phone_number"])
    return safe_args


def _log_tool_event(
    tool_name: str,
    stage: str,
    args: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    status: str | None = None,
    artifacts: dict[str, Any] | None = None,
) -> None:
    if not LOGGER.handlers:
        logging.basicConfig(level=logging.INFO)

    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "stage": stage,
    }
    if args is not None:
        payload["args"] = _safe_tool_args(args)
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if status is not None:
        payload["status"] = status
    if artifacts is not None:
        payload["artifacts"] = artifacts

    LOGGER.info(json.dumps(payload, ensure_ascii=False))


@tool
def list_available_vehicle_filters() -> str:
    """List allowed search parameters and available catalog values from the database."""
    started_at = time.perf_counter()
    _log_tool_event("list_available_vehicle_filters", "start", args={})
    try:
        metadata = get_inventory_metadata(db_path=_inventory_db_path())
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_tool_event(
            "list_available_vehicle_filters",
            "end",
            args={},
            duration_ms=duration_ms,
            status="error",
            artifacts={"error": str(exc)},
        )
        return _json(
            {
                "ok": False,
                "error": "Inventory metadata is not available.",
                "details": str(exc),
            }
        )
    payload = {
        "allowed_filters": sorted(ALLOWED_FILTERS),
        "catalog": metadata,
        "notes": {
            "ids": "Use catalog IDs for dimension filters: country_id/body_type_id/transmission_type_id/fuel_type_id/drivetrain_id",
            "year": "Use year_min/year_max",
            "mileage": "Use mileage_km_min/mileage_km_max",
            "price": "Use price_usd_min/price_usd_max",
            "limit": "Recommended 3 to 8",
            "workflow": "Call this tool first, pick IDs from catalog, then run search.",
        },
    }
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    _log_tool_event(
        "list_available_vehicle_filters",
        "end",
        args={},
        duration_ms=duration_ms,
        status="ok",
        artifacts={
            "countries": len(metadata.get("countries", [])),
            "body_types": len(metadata.get("body_types", [])),
            "fuel_types": len(metadata.get("fuel_types", [])),
        },
    )
    return _json(payload)


@tool
def search_used_vehicles(
    country_id: int | None = None,
    body_type_id: int | None = None,
    transmission_type_id: int | None = None,
    fuel_type_id: int | None = None,
    drivetrain_id: int | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    mileage_km_min: int | None = None,
    mileage_km_max: int | None = None,
    make: str | None = None,
    model: str | None = None,
    color: str | None = None,
    number_of_doors: int | None = None,
    price_usd_min: int | None = None,
    price_usd_max: int | None = None,
    limit: int = 5,
) -> str:
    """Search used-car inventory using optional filters. Returns matching vehicles with IDs."""
    started_at = time.perf_counter()

    filters = {
        "country_id": country_id,
        "body_type_id": body_type_id,
        "transmission_type_id": transmission_type_id,
        "fuel_type_id": fuel_type_id,
        "drivetrain_id": drivetrain_id,
        "year_min": year_min,
        "year_max": year_max,
        "mileage_km_min": mileage_km_min,
        "mileage_km_max": mileage_km_max,
        "make": make,
        "model": model,
        "color": color,
        "number_of_doors": number_of_doors,
        "price_usd_min": price_usd_min,
        "price_usd_max": price_usd_max,
        "limit": max(1, min(limit, 10)),
    }
    _log_tool_event("search_used_vehicles", "start", args=filters)

    try:
        rows, sql, params = search_vehicles(filters=filters, db_path=_inventory_db_path())
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_tool_event(
            "search_used_vehicles",
            "end",
            args=filters,
            duration_ms=duration_ms,
            status="error",
            artifacts={"error": str(exc)},
        )
        return _json(
            {
                "ok": False,
                "error": "Vehicle search is not available.",
                "details": str(exc),
            }
        )
    compact_rows = [
        {
            "id": row["id"],
            "country_id": row["country_id"],
            "body_type_id": row["body_type_id"],
            "transmission_type_id": row["transmission_type_id"],
            "fuel_type_id": row["fuel_type_id"],
            "drivetrain_id": row["drivetrain_id"],
            "year": row["year"],
            "make": row["make"],
            "model": row["model"],
            "mileage_km": row["mileage_km"],
            "price_usd": row["price_usd"],
            "fuel_type": row["fuel_type"],
            "transmission_type": row["transmission_type"],
            "drivetrain": row["drivetrain"],
            "body_type": row["body_type"],
            "country_of_origin": row["country_of_origin"],
        }
        for row in rows
    ]

    payload = {
        "count": len(compact_rows),
        "filters_used": {k: v for k, v in filters.items() if v is not None},
        "vehicles": compact_rows,
    }

    if os.getenv("SHOW_SQL_DEBUG", "false").lower() == "true":
        payload["debug"] = {
            "sql": sql,
            "params": params,
        }

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    _log_tool_event(
        "search_used_vehicles",
        "end",
        args=filters,
        duration_ms=duration_ms,
        status="ok",
        artifacts={"rows": len(compact_rows)},
    )
    return _json(payload)


@tool
def get_vehicle_details(vehicle_id: int) -> str:
    """Get full details of one vehicle by its ID."""
    started_at = time.perf_counter()
    tool_args = {"vehicle_id": vehicle_id}
    _log_tool_event("get_vehicle_details", "start", args=tool_args)

    try:
        row = get_vehicle_by_id(vehicle_id=vehicle_id, db_path=_inventory_db_path())
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_tool_event(
            "get_vehicle_details",
            "end",
            args=tool_args,
            duration_ms=duration_ms,
            status="error",
            artifacts={"error": str(exc)},
        )
        return _json(
            {
                "found": False,
                "error": "Vehicle detail lookup is not available.",
                "details": str(exc),
            }
        )
    if not row:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_tool_event(
            "get_vehicle_details",
            "end",
            args=tool_args,
            duration_ms=duration_ms,
            status="not_found",
            artifacts={},
        )
        return _json({"found": False, "message": f"Vehicle ID {vehicle_id} not found."})

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    _log_tool_event(
        "get_vehicle_details",
        "end",
        args=tool_args,
        duration_ms=duration_ms,
        status="ok",
        artifacts={"is_available": row.get("is_available")},
    )
    return _json({"found": True, "vehicle": row})


@tool
def create_executive_call_request(
    vehicle_id: int,
    customer_name: str,
    phone_number: str,
    preferred_call_time: str,
    notes: str = "",
) -> str:
    """Create a callback request from a customer for a specific vehicle."""
    started_at = time.perf_counter()
    tool_args = {
        "vehicle_id": vehicle_id,
        "customer_name": customer_name,
        "phone_number": phone_number,
        "preferred_call_time": preferred_call_time,
    }
    _log_tool_event("create_executive_call_request", "start", args=tool_args)

    try:
        vehicle = get_vehicle_by_id(vehicle_id=vehicle_id, db_path=_inventory_db_path())
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_tool_event(
            "create_executive_call_request",
            "end",
            args=tool_args,
            duration_ms=duration_ms,
            status="error",
            artifacts={"error": str(exc)},
        )
        return _json(
            {
                "ok": False,
                "error": "Contact request service is not available.",
                "details": str(exc),
            }
        )
    if not vehicle:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_tool_event(
            "create_executive_call_request",
            "end",
            args=tool_args,
            duration_ms=duration_ms,
            status="error",
            artifacts={"error": "vehicle_not_found"},
        )
        return _json({"ok": False, "error": f"Vehicle ID {vehicle_id} does not exist."})

    if int(vehicle.get("is_available", 0)) != 1:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_tool_event(
            "create_executive_call_request",
            "end",
            args=tool_args,
            duration_ms=duration_ms,
            status="error",
            artifacts={"error": "vehicle_not_available"},
        )
        return _json({"ok": False, "error": f"Vehicle ID {vehicle_id} is not available."})

    normalized_phone = re.sub(r"[^\d+]", "", phone_number)
    if len(re.sub(r"\D", "", normalized_phone)) < 8:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_tool_event(
            "create_executive_call_request",
            "end",
            args=tool_args,
            duration_ms=duration_ms,
            status="error",
            artifacts={"error": "invalid_phone"},
        )
        return _json({"ok": False, "error": "Invalid phone number. Provide at least 8 digits."})

    try:
        request_id, created = create_contact_request(
            vehicle_id=vehicle_id,
            customer_name=customer_name.strip(),
            phone_number=normalized_phone,
            preferred_call_time=preferred_call_time.strip(),
            notes=notes.strip() or None,
            db_path=_inventory_db_path(),
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_tool_event(
            "create_executive_call_request",
            "end",
            args=tool_args,
            duration_ms=duration_ms,
            status="error",
            artifacts={"error": str(exc)},
        )
        return _json(
            {
                "ok": False,
                "error": "Could not create callback request.",
                "details": str(exc),
            }
        )

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    _log_tool_event(
        "create_executive_call_request",
        "end",
        args=tool_args,
        duration_ms=duration_ms,
        status="ok",
        artifacts={"request_id": request_id, "created": created},
    )
    return _json(
        {
            "ok": True,
            "request_id": request_id,
            "vehicle_id": vehicle_id,
            "customer_name": customer_name.strip(),
            "phone_number": normalized_phone,
            "preferred_call_time": preferred_call_time.strip(),
            "created": created,
            "message": (
                "Callback request created successfully."
                if created
                else "Duplicate callback request detected; existing request reused."
            ),
        }
    )


QUOTE_TOOLS = [
    list_available_vehicle_filters,
    search_used_vehicles,
    get_vehicle_details,
]

CONTACT_TOOLS = [
    get_vehicle_details,
    create_executive_call_request,
]

QUOTE_TOOL_NAMES = {tool.name for tool in QUOTE_TOOLS}
CONTACT_TOOL_NAMES = {tool.name for tool in CONTACT_TOOLS}
