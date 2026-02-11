import sqlite3

from app.db.vehicle_repository import search_vehicles
from scripts.migrate_inventory_db import migrate_inventory_database


def test_migrate_inventory_db_from_old_schema(tmp_path):
    db_path = tmp_path / "legacy.db"

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL UNIQUE,
                country_of_origin TEXT NOT NULL,
                year INTEGER NOT NULL,
                mileage_km INTEGER NOT NULL,
                make TEXT NOT NULL,
                model TEXT NOT NULL,
                color TEXT NOT NULL,
                description TEXT NOT NULL,
                body_type TEXT NOT NULL,
                transmission_type TEXT NOT NULL,
                fuel_type TEXT NOT NULL,
                drivetrain TEXT NOT NULL,
                number_of_doors INTEGER NOT NULL,
                engine TEXT,
                price_usd INTEGER NOT NULL,
                is_available INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE contact_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                preferred_call_time TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        conn.execute(
            """
            INSERT INTO vehicles (
                stock_code, country_of_origin, year, mileage_km, make, model, color,
                description, body_type, transmission_type, fuel_type, drivetrain,
                number_of_doors, engine, price_usd, is_available
            ) VALUES (
                'UC-2022-001', 'Japan', 2022, 90590, 'Nissan', 'X-Trail', 'Gray',
                'Seeded from old schema', 'SUV', 'CVT', 'Gasoline', 'AWD',
                5, '2.5L I4', 17743, 1
            );
            """
        )
        conn.execute(
            """
            INSERT INTO contact_requests (
                vehicle_id, customer_name, phone_number, preferred_call_time, notes
            ) VALUES (
                1, 'Nicolas Bertin', '+56967297181', '18:00', 'Legacy request'
            );
            """
        )
        conn.commit()

    summary = migrate_inventory_database(db_path=db_path)
    assert summary["already_migrated"] == 0
    assert summary["migrated"] == 1
    assert summary["contact_requests"] == 1

    with sqlite3.connect(db_path) as conn:
        vehicle_columns = {row[1] for row in conn.execute("PRAGMA table_info(vehicles);").fetchall()}
        assert "country_id" in vehicle_columns
        assert "country_of_origin" not in vehicle_columns

        requests_count = conn.execute("SELECT COUNT(*) FROM contact_requests;").fetchone()[0]
        assert requests_count == 1

    with sqlite3.connect(db_path) as conn:
        japan_id = conn.execute("SELECT id FROM countries WHERE name = 'Japan';").fetchone()[0]

    results, _, _ = search_vehicles(
        {"country_id": japan_id, "year_min": 2015, "mileage_km_max": 100000},
        db_path=db_path,
    )
    assert len(results) == 1
    assert results[0]["country_of_origin"] == "Japan"
