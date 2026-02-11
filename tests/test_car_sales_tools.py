import json
import os
import sqlite3

from app.tools.car_sales_tools import (
    create_executive_call_request,
    get_vehicle_details,
    list_available_vehicle_filters,
    search_used_vehicles,
)
from scripts.init_sqlite_db import initialize_database


def test_tools_can_search_and_create_contact_request(tmp_path):
    db_path = tmp_path / "dealer.db"
    initialize_database(db_path=db_path, seed_count=60)

    os.environ["DEALERSHIP_DB_PATH"] = str(db_path)

    filter_info = json.loads(list_available_vehicle_filters.invoke({}))
    assert "allowed_filters" in filter_info
    assert "make" in filter_info["allowed_filters"]
    assert "catalog" in filter_info
    assert "countries" in filter_info["catalog"]
    japan = next(item for item in filter_info["catalog"]["countries"] if item["name"] == "Japan")
    suv = next(item for item in filter_info["catalog"]["body_types"] if item["name"] == "SUV")

    search_payload = {
        "make": "Toyota",
        "body_type_id": suv["id"],
        "price_usd_max": 35000,
        "limit": 2,
    }
    search_result = json.loads(search_used_vehicles.invoke(search_payload))
    assert search_result["count"] >= 1
    assert len(search_result["vehicles"]) <= 2

    vehicle_id = search_result["vehicles"][0]["id"]
    details = json.loads(get_vehicle_details.invoke({"vehicle_id": vehicle_id}))
    assert details["found"] is True
    assert details["vehicle"]["id"] == vehicle_id

    id_search = json.loads(
        search_used_vehicles.invoke(
            {
                "country_id": japan["id"],
                "year_min": 2015,
                "mileage_km_max": 100000,
                "limit": 5,
            }
        )
    )
    assert id_search["count"] >= 1

    request_result = json.loads(
        create_executive_call_request.invoke(
            {
                "vehicle_id": vehicle_id,
                "customer_name": "Carla Diaz",
                "phone_number": "+5491111122233",
                "preferred_call_time": "Mañana 11:30",
                "notes": "Interesada en financiación",
            }
        )
    )
    assert request_result["ok"] is True
    assert request_result["vehicle_id"] == vehicle_id


def test_tools_auto_migrate_legacy_inventory_db(tmp_path):
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
                'Legacy seeded row', 'SUV', 'CVT', 'Gasoline', 'AWD',
                5, '2.5L I4', 17743, 1
            );
            """
        )
        conn.commit()

    os.environ["DEALERSHIP_DB_PATH"] = str(db_path)

    catalog = json.loads(list_available_vehicle_filters.invoke({}))
    assert catalog.get("ok", True) is True
    assert "countries" in catalog["catalog"]
    japan = next(item for item in catalog["catalog"]["countries"] if item["name"] == "Japan")

    results = json.loads(search_used_vehicles.invoke({"country_id": japan["id"], "limit": 5}))
    assert results["count"] == 1
    assert results["vehicles"][0]["country_of_origin"] == "Japan"
