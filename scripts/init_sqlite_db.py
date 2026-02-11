from __future__ import annotations

import argparse
import random
import sqlite3
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "dealership.db"
SCHEMA_PATH = PROJECT_ROOT / "app" / "db" / "schema.sql"


COUNTRIES = [
    "Brazil",
    "Canada",
    "China",
    "France",
    "Germany",
    "Japan",
    "Mexico",
    "Romania",
    "South Korea",
    "Sweden",
    "Thailand",
    "United States",
]

BODY_TYPES = ["Hatchback", "Pickup", "SUV", "Sedan"]
TRANSMISSION_TYPES = ["Automatic", "CVT", "Dual-Clutch", "Manual"]
FUEL_TYPES = ["Diesel", "Electric", "Flex Fuel", "Gasoline", "Hybrid", "Plug-in Hybrid"]
DRIVETRAINS = ["4WD", "AWD", "FWD", "RWD"]


def _insert_dimension(conn: sqlite3.Connection, table: str, values: list[str]) -> dict[str, int]:
    conn.executemany(f"INSERT INTO {table} (name) VALUES (?);", [(value,) for value in values])
    rows = conn.execute(f"SELECT id, name FROM {table};").fetchall()
    return {name: int(row_id) for row_id, name in rows}


def seed_reference_data(conn: sqlite3.Connection) -> None:
    _insert_dimension(conn, "countries", COUNTRIES)
    _insert_dimension(conn, "body_types", BODY_TYPES)
    _insert_dimension(conn, "transmission_types", TRANSMISSION_TYPES)
    _insert_dimension(conn, "fuel_types", FUEL_TYPES)
    _insert_dimension(conn, "drivetrains", DRIVETRAINS)


def generate_seed_vehicles(count: int = 60) -> list[dict[str, Any]]:
    """Generate deterministic used-car inventory rows."""

    rng = random.Random(20260211)

    base_catalog = [
        ("Toyota", "Corolla", "Sedan", "Gasoline", "FWD", 4, "Japan", "Automatic", "1.8L I4"),
        ("Toyota", "RAV4", "SUV", "Hybrid", "AWD", 5, "Japan", "CVT", "2.5L I4 Hybrid"),
        ("Honda", "Civic", "Sedan", "Gasoline", "FWD", 4, "Japan", "Automatic", "2.0L I4"),
        ("Honda", "CR-V", "SUV", "Gasoline", "AWD", 5, "Japan", "CVT", "1.5L Turbo"),
        ("Ford", "Escape", "SUV", "Gasoline", "AWD", 5, "United States", "Automatic", "2.0L EcoBoost"),
        ("Ford", "F-150", "Pickup", "Gasoline", "4WD", 4, "United States", "Automatic", "3.5L V6"),
        ("Chevrolet", "Onix", "Hatchback", "Gasoline", "FWD", 5, "Brazil", "Manual", "1.0L Turbo"),
        ("Chevrolet", "Equinox", "SUV", "Gasoline", "AWD", 5, "Canada", "Automatic", "1.5L Turbo"),
        ("Nissan", "Sentra", "Sedan", "Gasoline", "FWD", 4, "Mexico", "CVT", "2.0L I4"),
        ("Nissan", "X-Trail", "SUV", "Gasoline", "AWD", 5, "Japan", "CVT", "2.5L I4"),
        ("Volkswagen", "Golf", "Hatchback", "Gasoline", "FWD", 5, "Germany", "Manual", "1.4L TSI"),
        ("Volkswagen", "Tiguan", "SUV", "Gasoline", "AWD", 5, "Germany", "Automatic", "2.0L TSI"),
        ("Hyundai", "Elantra", "Sedan", "Gasoline", "FWD", 4, "South Korea", "Automatic", "2.0L I4"),
        ("Hyundai", "Tucson", "SUV", "Hybrid", "AWD", 5, "South Korea", "Automatic", "1.6L Turbo Hybrid"),
        ("Kia", "Rio", "Sedan", "Gasoline", "FWD", 4, "South Korea", "Automatic", "1.6L I4"),
        ("Kia", "Sportage", "SUV", "Gasoline", "AWD", 5, "South Korea", "Automatic", "2.5L I4"),
        ("Mazda", "Mazda3", "Sedan", "Gasoline", "FWD", 4, "Japan", "Automatic", "2.0L Skyactiv"),
        ("Mazda", "CX-5", "SUV", "Gasoline", "AWD", 5, "Japan", "Automatic", "2.5L Skyactiv"),
        ("Subaru", "Impreza", "Hatchback", "Gasoline", "AWD", 5, "Japan", "CVT", "2.0L Boxer"),
        ("Subaru", "Forester", "SUV", "Gasoline", "AWD", 5, "Japan", "CVT", "2.5L Boxer"),
        ("BMW", "320i", "Sedan", "Gasoline", "RWD", 4, "Germany", "Automatic", "2.0L Turbo"),
        ("Mercedes-Benz", "C200", "Sedan", "Gasoline", "RWD", 4, "Germany", "Automatic", "2.0L Turbo"),
        ("Audi", "A4", "Sedan", "Gasoline", "AWD", 4, "Germany", "Automatic", "2.0L TFSI"),
        ("Peugeot", "3008", "SUV", "Diesel", "FWD", 5, "France", "Automatic", "1.5L BlueHDi"),
        ("Renault", "Duster", "SUV", "Gasoline", "FWD", 5, "Romania", "Manual", "1.6L I4"),
        ("Jeep", "Compass", "SUV", "Gasoline", "4WD", 5, "Mexico", "Automatic", "2.4L I4"),
        ("Mitsubishi", "L200", "Pickup", "Diesel", "4WD", 4, "Thailand", "Manual", "2.4L Diesel"),
        ("Volvo", "XC60", "SUV", "Hybrid", "AWD", 5, "Sweden", "Automatic", "2.0L Mild Hybrid"),
        ("Tesla", "Model 3", "Sedan", "Electric", "RWD", 4, "United States", "Automatic", "Electric Motor"),
        ("BYD", "Yuan Plus", "SUV", "Electric", "FWD", 5, "China", "Automatic", "Electric Motor"),
    ]

    colors = [
        "White",
        "Black",
        "Silver",
        "Gray",
        "Blue",
        "Red",
        "Green",
        "Brown",
        "Beige",
        "Orange",
    ]

    vehicles: list[dict[str, Any]] = []
    for i in range(count):
        (
            make,
            model,
            body_type,
            fuel_type,
            drivetrain,
            doors,
            country,
            transmission,
            engine,
        ) = base_catalog[i % len(base_catalog)]

        year = 2011 + (i % 14)  # 2011..2024
        mileage_base = 180_000 - ((year - 2011) * 8_000)
        mileage_km = max(8_000, mileage_base + rng.randint(-12_000, 12_000))
        price_usd = max(
            5_500,
            7_000 + ((year - 2011) * 900) - (mileage_km // 130) + rng.randint(-1_500, 2_500),
        )
        color = colors[i % len(colors)]
        stock_code = f"UC-{year}-{i + 1:03d}"

        description = (
            f"Used {year} {make} {model} in {color}. "
            f"{mileage_km:,} km, {transmission} transmission, {fuel_type.lower()} engine."
        )

        vehicles.append(
            {
                "stock_code": stock_code,
                "country_of_origin": country,
                "year": year,
                "mileage_km": mileage_km,
                "make": make,
                "model": model,
                "color": color,
                "description": description,
                "body_type": body_type,
                "transmission_type": transmission,
                "fuel_type": fuel_type,
                "drivetrain": drivetrain,
                "number_of_doors": doors,
                "engine": engine,
                "price_usd": price_usd,
                "is_available": 1,
            }
        )

    return vehicles


def _build_reference_maps(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    maps: dict[str, dict[str, int]] = {}
    for table, key in [
        ("countries", "country"),
        ("body_types", "body_type"),
        ("transmission_types", "transmission_type"),
        ("fuel_types", "fuel_type"),
        ("drivetrains", "drivetrain"),
    ]:
        rows = conn.execute(f"SELECT id, name FROM {table};").fetchall()
        maps[key] = {name: int(row_id) for row_id, name in rows}
    return maps


def insert_vehicles(conn: sqlite3.Connection, vehicles: list[dict[str, Any]]) -> None:
    maps = _build_reference_maps(conn)

    payload: list[dict[str, Any]] = []
    for vehicle in vehicles:
        payload.append(
            {
                "stock_code": vehicle["stock_code"],
                "country_id": maps["country"][vehicle["country_of_origin"]],
                "year": vehicle["year"],
                "mileage_km": vehicle["mileage_km"],
                "make": vehicle["make"],
                "model": vehicle["model"],
                "color": vehicle["color"],
                "description": vehicle["description"],
                "body_type_id": maps["body_type"][vehicle["body_type"]],
                "transmission_type_id": maps["transmission_type"][vehicle["transmission_type"]],
                "fuel_type_id": maps["fuel_type"][vehicle["fuel_type"]],
                "drivetrain_id": maps["drivetrain"][vehicle["drivetrain"]],
                "number_of_doors": vehicle["number_of_doors"],
                "engine": vehicle["engine"],
                "price_usd": vehicle["price_usd"],
                "is_available": vehicle["is_available"],
            }
        )

    conn.executemany(
        """
        INSERT INTO vehicles (
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
            is_available
        ) VALUES (
            :stock_code,
            :country_id,
            :year,
            :mileage_km,
            :make,
            :model,
            :color,
            :description,
            :body_type_id,
            :transmission_type_id,
            :fuel_type_id,
            :drivetrain_id,
            :number_of_doors,
            :engine,
            :price_usd,
            :is_available
        );
        """,
        payload,
    )


def initialize_database(db_path: Path = DEFAULT_DB_PATH, seed_count: int = 60) -> dict[str, int]:
    """Create schema and load seed data into SQLite."""

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    vehicles = generate_seed_vehicles(count=seed_count)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(schema_sql)
        seed_reference_data(conn)
        insert_vehicles(conn, vehicles)

        vehicle_count = conn.execute("SELECT COUNT(*) FROM vehicles;").fetchone()[0]
        distinct_vehicle_count = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM vehicles;").fetchone()[0]

    return {
        "vehicles": int(vehicle_count),
        "distinct_vehicles": int(distinct_vehicle_count),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize SQLite database with used-car inventory.")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Output database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--seed-count",
        type=int,
        default=60,
        help="How many vehicle rows to seed (default: 60).",
    )
    args = parser.parse_args()

    if args.seed_count < 50:
        raise SystemExit("--seed-count must be at least 50 to satisfy project requirements.")

    summary = initialize_database(db_path=args.db_path, seed_count=args.seed_count)
    print(f"SQLite database initialized at: {args.db_path}")
    print(f"Vehicles inserted: {summary['vehicles']}")
    print(f"Distinct vehicles: {summary['distinct_vehicles']}")


if __name__ == "__main__":
    main()
