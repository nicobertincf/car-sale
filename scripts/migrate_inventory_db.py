from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.init_sqlite_db import DEFAULT_DB_PATH, SCHEMA_PATH, seed_reference_data


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type='table' AND name = ?;
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name});").fetchall()}


def _resolve_reference_id(
    conn: sqlite3.Connection,
    table_name: str,
    value: str,
) -> int:
    normalized = value.strip()
    row = conn.execute(
        f"""
        SELECT id
        FROM {table_name}
        WHERE LOWER(name) = LOWER(?)
        LIMIT 1;
        """,
        (normalized,),
    ).fetchone()
    if row:
        return int(row[0])

    cursor = conn.execute(f"INSERT INTO {table_name} (name) VALUES (?);", (normalized,))
    return int(cursor.lastrowid)


def _migrate_vehicles(source_conn: sqlite3.Connection, target_conn: sqlite3.Connection) -> int:
    source_conn.row_factory = sqlite3.Row
    rows = source_conn.execute("SELECT * FROM vehicles ORDER BY id ASC;").fetchall()

    inserted = 0
    for row in rows:
        row_data = dict(row)

        country_id = _resolve_reference_id(
            target_conn,
            "countries",
            row_data["country_of_origin"],
        )
        body_type_id = _resolve_reference_id(
            target_conn,
            "body_types",
            row_data["body_type"],
        )
        transmission_type_id = _resolve_reference_id(
            target_conn,
            "transmission_types",
            row_data["transmission_type"],
        )
        fuel_type_id = _resolve_reference_id(
            target_conn,
            "fuel_types",
            row_data["fuel_type"],
        )
        drivetrain_id = _resolve_reference_id(
            target_conn,
            "drivetrains",
            row_data["drivetrain"],
        )

        target_conn.execute(
            """
            INSERT INTO vehicles (
                id,
                stock_code,
                country_id,
                year,
                mileage_km,
                make,
                model,
                color,
                description,
                body_type_id,
                transmission_type_id,
                fuel_type_id,
                drivetrain_id,
                number_of_doors,
                engine,
                price_usd,
                is_available,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                row_data["id"],
                row_data["stock_code"],
                country_id,
                row_data["year"],
                row_data["mileage_km"],
                row_data["make"],
                row_data["model"],
                row_data["color"],
                row_data["description"],
                body_type_id,
                transmission_type_id,
                fuel_type_id,
                drivetrain_id,
                row_data["number_of_doors"],
                row_data.get("engine"),
                row_data["price_usd"],
                row_data["is_available"],
                row_data.get("created_at"),
            ),
        )
        inserted += 1

    return inserted


def _migrate_contact_requests(source_conn: sqlite3.Connection, target_conn: sqlite3.Connection) -> int:
    if not _table_exists(source_conn, "contact_requests"):
        return 0

    source_conn.row_factory = sqlite3.Row
    rows = source_conn.execute("SELECT * FROM contact_requests ORDER BY id ASC;").fetchall()

    inserted = 0
    for row in rows:
        row_data = dict(row)
        try:
            target_conn.execute(
                """
                INSERT INTO contact_requests (
                    id,
                    vehicle_id,
                    customer_name,
                    phone_number,
                    preferred_call_time,
                    notes,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    row_data["id"],
                    row_data["vehicle_id"],
                    row_data["customer_name"],
                    row_data["phone_number"],
                    row_data["preferred_call_time"],
                    row_data.get("notes"),
                    row_data.get("created_at"),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            # Skip duplicated rows that violate the normalized unique constraint.
            continue

    return inserted


def migrate_inventory_database(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with sqlite3.connect(db_path) as source_conn:
        if not _table_exists(source_conn, "vehicles"):
            raise RuntimeError("Source database does not contain a vehicles table.")

        vehicle_columns = _column_names(source_conn, "vehicles")
        if "country_id" in vehicle_columns:
            return {"migrated": 0, "contact_requests": 0, "already_migrated": 1}

        if "country_of_origin" not in vehicle_columns:
            raise RuntimeError(
                "Unsupported vehicles schema. Expected old schema with country_of_origin."
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_db_path = Path(tmp_dir) / "migrated.db"

            schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
            with sqlite3.connect(tmp_db_path) as target_conn:
                target_conn.execute("PRAGMA foreign_keys = ON;")
                target_conn.executescript(schema_sql)
                seed_reference_data(target_conn)

                migrated_vehicles = _migrate_vehicles(source_conn, target_conn)
                migrated_contacts = _migrate_contact_requests(source_conn, target_conn)
                target_conn.commit()

            backup_path = db_path.with_suffix(db_path.suffix + ".bak-pre-migration")
            shutil.copy2(db_path, backup_path)
            shutil.copy2(tmp_db_path, db_path)

    return {
        "migrated": migrated_vehicles,
        "contact_requests": migrated_contacts,
        "already_migrated": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate inventory DB to normalized schema.")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path of DB to migrate (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    summary = migrate_inventory_database(args.db_path)
    if summary["already_migrated"]:
        print(f"No-op: database is already migrated ({args.db_path}).")
        return

    print(f"Migrated DB: {args.db_path}")
    print(f"Vehicles migrated: {summary['migrated']}")
    print(f"Contact requests migrated: {summary['contact_requests']}")
    print(f"Backup created with suffix: .bak-pre-migration")


if __name__ == "__main__":
    main()
