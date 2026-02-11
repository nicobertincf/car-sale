from __future__ import annotations

import json
import os
import re
import sqlite3
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


@tool
def list_available_vehicle_filters() -> str:
    """List allowed search parameters and available catalog values from the database."""
    try:
        metadata = get_inventory_metadata(db_path=_inventory_db_path())
    except Exception as exc:
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

    try:
        rows, sql, params = search_vehicles(filters=filters, db_path=_inventory_db_path())
    except Exception as exc:
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

    return _json(payload)


@tool
def get_vehicle_details(vehicle_id: int) -> str:
    """Get full details of one vehicle by its ID."""

    try:
        row = get_vehicle_by_id(vehicle_id=vehicle_id, db_path=_inventory_db_path())
    except Exception as exc:
        return _json(
            {
                "found": False,
                "error": "Vehicle detail lookup is not available.",
                "details": str(exc),
            }
        )
    if not row:
        return _json({"found": False, "message": f"Vehicle ID {vehicle_id} not found."})

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

    try:
        vehicle = get_vehicle_by_id(vehicle_id=vehicle_id, db_path=_inventory_db_path())
    except Exception as exc:
        return _json(
            {
                "ok": False,
                "error": "Contact request service is not available.",
                "details": str(exc),
            }
        )
    if not vehicle:
        return _json({"ok": False, "error": f"Vehicle ID {vehicle_id} does not exist."})

    if int(vehicle.get("is_available", 0)) != 1:
        return _json({"ok": False, "error": f"Vehicle ID {vehicle_id} is not available."})

    normalized_phone = re.sub(r"[^\d+]", "", phone_number)
    if len(re.sub(r"\D", "", normalized_phone)) < 8:
        return _json({"ok": False, "error": "Invalid phone number. Provide at least 8 digits."})

    try:
        request_id = create_contact_request(
            vehicle_id=vehicle_id,
            customer_name=customer_name.strip(),
            phone_number=normalized_phone,
            preferred_call_time=preferred_call_time.strip(),
            notes=notes.strip() or None,
            db_path=_inventory_db_path(),
        )
    except Exception as exc:
        return _json(
            {
                "ok": False,
                "error": "Could not create callback request.",
                "details": str(exc),
            }
        )

    return _json(
        {
            "ok": True,
            "request_id": request_id,
            "vehicle_id": vehicle_id,
            "customer_name": customer_name.strip(),
            "phone_number": normalized_phone,
            "preferred_call_time": preferred_call_time.strip(),
            "message": "Callback request created successfully.",
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
