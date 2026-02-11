import sqlite3

from app.db.vehicle_repository import (
    build_vehicle_search_query,
    create_contact_request,
    get_vehicle_by_id,
    get_inventory_metadata,
    search_vehicles,
)
from scripts.init_sqlite_db import initialize_database


def test_build_vehicle_query_uses_allowed_parameterized_filters():
    sql, params = build_vehicle_search_query(
        {
            "make": "Toyota",
            "body_type_id": 3,
            "price_usd_max": 26000,
            "mileage_km_max": 90000,
            "unsupported_field": "ignore-me",
        }
    )

    assert "unsupported_field" not in sql
    assert ":make" in sql
    assert ":body_type_id" in sql
    assert ":price_usd_max" in sql
    assert ":mileage_km_max" in sql

    assert params["make"] == "Toyota"
    assert params["body_type_id"] == 3
    assert params["price_usd_max"] == 26000
    assert params["mileage_km_max"] == 90000


def test_search_vehicles_and_create_contact_request(tmp_path):
    db_path = tmp_path / "dealer.db"
    initialize_database(db_path=db_path, seed_count=60)

    results, _, _ = search_vehicles(
        {
            "make": "Toyota",
            "price_usd_max": 45000,
            "limit": 3,
        },
        db_path=db_path,
    )

    assert len(results) > 0
    vehicle_id = int(results[0]["id"])

    vehicle = get_vehicle_by_id(vehicle_id, db_path=db_path)
    assert vehicle is not None
    assert vehicle["id"] == vehicle_id

    request_id = create_contact_request(
        vehicle_id=vehicle_id,
        customer_name="Ana Perez",
        phone_number="+541112345678",
        preferred_call_time="Mañana 10:00",
        notes="Interesada en prueba de manejo.",
        db_path=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, vehicle_id, customer_name, phone_number, preferred_call_time
            FROM contact_requests
            WHERE id = ?;
            """,
            (request_id,),
        ).fetchone()

    assert row is not None
    assert row[1] == vehicle_id
    assert row[2] == "Ana Perez"


def test_search_vehicles_by_catalog_ids_and_metadata(tmp_path):
    db_path = tmp_path / "dealer_ids.db"
    initialize_database(db_path=db_path, seed_count=60)

    metadata = get_inventory_metadata(db_path=db_path)
    japan_country = next(item for item in metadata["countries"] if item["name"] == "Japan")

    results, _, params = search_vehicles(
        {
            "country_id": japan_country["id"],
            "year_min": 2015,
            "mileage_km_max": 100000,
            "limit": 10,
        },
        db_path=db_path,
    )

    assert params["country_id"] == japan_country["id"]
    assert all(row["country_of_origin"] == "Japan" for row in results)

    country_names = {row["name"] for row in metadata["countries"]}
    assert "Japan" in country_names
