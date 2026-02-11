from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY_DB = PROJECT_ROOT / "data" / "dealership.db"

ALLOWED_FILTERS = {
    "country_id",
    "body_type_id",
    "transmission_type_id",
    "fuel_type_id",
    "drivetrain_id",
    "year_min",
    "year_max",
    "mileage_km_min",
    "mileage_km_max",
    "make",
    "model",
    "color",
    "number_of_doors",
    "price_usd_min",
    "price_usd_max",
    "limit",
}


def _normalize_filters(raw_filters: dict[str, Any] | None) -> dict[str, Any]:
    if not raw_filters:
        return {}

    normalized: dict[str, Any] = {}
    for key, value in raw_filters.items():
        if key not in ALLOWED_FILTERS:
            continue
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            normalized[key] = stripped
        else:
            normalized[key] = value
    return normalized


def build_vehicle_search_query(raw_filters: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    filters = _normalize_filters(raw_filters)

    sql = """
    SELECT
        v.id,
        v.stock_code,
        v.country_id,
        c.name AS country_of_origin,
        v.year,
        v.mileage_km,
        v.make,
        v.model,
        v.color,
        v.description,
        v.body_type_id,
        bt.name AS body_type,
        v.transmission_type_id,
        tt.name AS transmission_type,
        v.fuel_type_id,
        ft.name AS fuel_type,
        v.drivetrain_id,
        dt.name AS drivetrain,
        v.number_of_doors,
        v.engine,
        v.price_usd,
        v.is_available
    FROM vehicles v
    JOIN countries c ON c.id = v.country_id
    JOIN body_types bt ON bt.id = v.body_type_id
    JOIN transmission_types tt ON tt.id = v.transmission_type_id
    JOIN fuel_types ft ON ft.id = v.fuel_type_id
    JOIN drivetrains dt ON dt.id = v.drivetrain_id
    WHERE v.is_available = 1
    """

    clauses: list[str] = []
    params: dict[str, Any] = {}

    if "country_id" in filters:
        clauses.append("v.country_id = :country_id")
        params["country_id"] = int(filters["country_id"])

    if "body_type_id" in filters:
        clauses.append("v.body_type_id = :body_type_id")
        params["body_type_id"] = int(filters["body_type_id"])

    if "transmission_type_id" in filters:
        clauses.append("v.transmission_type_id = :transmission_type_id")
        params["transmission_type_id"] = int(filters["transmission_type_id"])

    if "fuel_type_id" in filters:
        clauses.append("v.fuel_type_id = :fuel_type_id")
        params["fuel_type_id"] = int(filters["fuel_type_id"])

    if "drivetrain_id" in filters:
        clauses.append("v.drivetrain_id = :drivetrain_id")
        params["drivetrain_id"] = int(filters["drivetrain_id"])

    if "year_min" in filters:
        clauses.append("v.year >= :year_min")
        params["year_min"] = int(filters["year_min"])

    if "year_max" in filters:
        clauses.append("v.year <= :year_max")
        params["year_max"] = int(filters["year_max"])

    if "mileage_km_min" in filters:
        clauses.append("v.mileage_km >= :mileage_km_min")
        params["mileage_km_min"] = int(filters["mileage_km_min"])

    if "mileage_km_max" in filters:
        clauses.append("v.mileage_km <= :mileage_km_max")
        params["mileage_km_max"] = int(filters["mileage_km_max"])

    if "make" in filters:
        clauses.append("LOWER(v.make) = LOWER(:make)")
        params["make"] = filters["make"]

    if "model" in filters:
        clauses.append("LOWER(v.model) LIKE LOWER(:model)")
        params["model"] = f"%{filters['model']}%"

    if "color" in filters:
        clauses.append("LOWER(v.color) = LOWER(:color)")
        params["color"] = filters["color"]

    if "number_of_doors" in filters:
        clauses.append("v.number_of_doors = :number_of_doors")
        params["number_of_doors"] = int(filters["number_of_doors"])

    if "price_usd_min" in filters:
        clauses.append("v.price_usd >= :price_usd_min")
        params["price_usd_min"] = int(filters["price_usd_min"])

    if "price_usd_max" in filters:
        clauses.append("v.price_usd <= :price_usd_max")
        params["price_usd_max"] = int(filters["price_usd_max"])

    if clauses:
        sql += "\n  AND " + "\n  AND ".join(clauses)

    sql += "\nORDER BY v.year DESC, v.mileage_km ASC, v.price_usd ASC\nLIMIT :limit"
    params["limit"] = int(filters.get("limit", 5))

    return sql.strip(), params


def search_vehicles(
    filters: dict[str, Any] | None,
    db_path: Path = DEFAULT_INVENTORY_DB,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    sql, params = build_vehicle_search_query(filters)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows], sql, params


def get_vehicle_by_id(vehicle_id: int, db_path: Path = DEFAULT_INVENTORY_DB) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT
                v.id,
                v.stock_code,
                v.country_id,
                c.name AS country_of_origin,
                v.make,
                v.model,
                v.year,
                v.mileage_km,
                v.body_type_id,
                bt.name AS body_type,
                v.transmission_type_id,
                tt.name AS transmission_type,
                v.fuel_type_id,
                ft.name AS fuel_type,
                v.drivetrain_id,
                dt.name AS drivetrain,
                v.number_of_doors,
                v.price_usd,
                v.is_available
            FROM vehicles v
            JOIN countries c ON c.id = v.country_id
            JOIN body_types bt ON bt.id = v.body_type_id
            JOIN transmission_types tt ON tt.id = v.transmission_type_id
            JOIN fuel_types ft ON ft.id = v.fuel_type_id
            JOIN drivetrains dt ON dt.id = v.drivetrain_id
            WHERE v.id = ?;
            """,
            (vehicle_id,),
        ).fetchone()

    return dict(row) if row else None


def create_contact_request(
    vehicle_id: int,
    customer_name: str,
    phone_number: str,
    preferred_call_time: str,
    notes: str | None = None,
    db_path: Path = DEFAULT_INVENTORY_DB,
) -> tuple[int, bool]:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        existing_row = conn.execute(
            """
            SELECT id
            FROM contact_requests
            WHERE vehicle_id = ?
              AND customer_name = ?
              AND phone_number = ?
              AND preferred_call_time = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (vehicle_id, customer_name, phone_number, preferred_call_time),
        ).fetchone()
        if existing_row:
            return int(existing_row[0]), False

        try:
            cursor = conn.execute(
                """
                INSERT INTO contact_requests (
                    vehicle_id,
                    customer_name,
                    phone_number,
                    preferred_call_time,
                    notes
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (vehicle_id, customer_name, phone_number, preferred_call_time, notes),
            )
            conn.commit()
            return int(cursor.lastrowid), True
        except sqlite3.IntegrityError:
            dedup_row = conn.execute(
                """
                SELECT id
                FROM contact_requests
                WHERE vehicle_id = ?
                  AND customer_name = ?
                  AND phone_number = ?
                  AND preferred_call_time = ?
                ORDER BY id DESC
                LIMIT 1;
                """,
                (vehicle_id, customer_name, phone_number, preferred_call_time),
            ).fetchone()
            if not dedup_row:
                raise
        conn.commit()

    return int(dedup_row[0]), False


def _load_dimension(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(f"SELECT id, name FROM {table} ORDER BY name ASC;").fetchall()
    return [{"id": int(row["id"]), "name": row["name"]} for row in rows]


def get_inventory_metadata(db_path: Path = DEFAULT_INVENTORY_DB) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        countries = _load_dimension(conn, "countries")
        body_types = _load_dimension(conn, "body_types")
        fuel_types = _load_dimension(conn, "fuel_types")
        transmission_types = _load_dimension(conn, "transmission_types")
        drivetrains = _load_dimension(conn, "drivetrains")
        makes = [row["make"] for row in conn.execute("SELECT DISTINCT make FROM vehicles ORDER BY make ASC;").fetchall()]

    return {
        "countries": countries,
        "body_types": body_types,
        "fuel_types": fuel_types,
        "transmission_types": transmission_types,
        "drivetrains": drivetrains,
        "makes": makes,
    }
