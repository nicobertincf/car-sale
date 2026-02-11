import sqlite3

from scripts.init_sqlite_db import initialize_database


def test_sqlite_seed_creates_required_tables_and_rows(tmp_path):
    db_path = tmp_path / "inventory.db"
    summary = initialize_database(db_path=db_path, seed_count=60)

    assert summary["vehicles"] >= 50
    assert summary["distinct_vehicles"] >= 50

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
        assert "vehicles" in tables
        assert "contact_requests" in tables

        vehicle_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(vehicles);").fetchall()
        }
        required_vehicle_columns = {
            "country_of_origin",
            "year",
            "mileage_km",
            "make",
            "model",
            "color",
            "description",
            "body_type",
            "transmission_type",
            "fuel_type",
            "drivetrain",
            "number_of_doors",
        }
        assert required_vehicle_columns.issubset(vehicle_columns)

        contact_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(contact_requests);").fetchall()
        }
        required_contact_columns = {
            "vehicle_id",
            "customer_name",
            "phone_number",
            "preferred_call_time",
        }
        assert required_contact_columns.issubset(contact_columns)

        foreign_keys = conn.execute("PRAGMA foreign_key_list(contact_requests);").fetchall()
        assert any(fk[2] == "vehicles" and fk[3] == "vehicle_id" and fk[4] == "id" for fk in foreign_keys)

