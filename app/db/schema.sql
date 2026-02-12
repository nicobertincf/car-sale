PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS contact_requests;
DROP TABLE IF EXISTS vehicles;

DROP TABLE IF EXISTS countries;
DROP TABLE IF EXISTS body_types;
DROP TABLE IF EXISTS transmission_types;
DROP TABLE IF EXISTS fuel_types;
DROP TABLE IF EXISTS drivetrains;

CREATE TABLE countries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE body_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE transmission_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE fuel_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE drivetrains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL UNIQUE,
    country_id INTEGER NOT NULL,
    year INTEGER NOT NULL CHECK (year BETWEEN 1980 AND 2100),
    mileage_km INTEGER NOT NULL CHECK (mileage_km >= 0),
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    color TEXT NOT NULL,
    description TEXT NOT NULL,
    body_type_id INTEGER NOT NULL,
    transmission_type_id INTEGER NOT NULL,
    fuel_type_id INTEGER NOT NULL,
    drivetrain_id INTEGER NOT NULL,
    number_of_doors INTEGER NOT NULL CHECK (number_of_doors BETWEEN 2 AND 6),
    engine TEXT,
    price_usd INTEGER NOT NULL CHECK (price_usd > 0),
    is_available INTEGER NOT NULL DEFAULT 1 CHECK (is_available IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (country_id) REFERENCES countries (id),
    FOREIGN KEY (body_type_id) REFERENCES body_types (id),
    FOREIGN KEY (transmission_type_id) REFERENCES transmission_types (id),
    FOREIGN KEY (fuel_type_id) REFERENCES fuel_types (id),
    FOREIGN KEY (drivetrain_id) REFERENCES drivetrains (id)
);

CREATE TABLE contact_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL,
    customer_name TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    preferred_call_time TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles (id) ON DELETE CASCADE
);

CREATE INDEX idx_vehicles_make_model ON vehicles (make, model);
CREATE INDEX idx_vehicles_year ON vehicles (year);
CREATE INDEX idx_vehicles_country_id ON vehicles (country_id);
CREATE INDEX idx_vehicles_body_type_id ON vehicles (body_type_id);
CREATE INDEX idx_vehicles_fuel_type_id ON vehicles (fuel_type_id);
CREATE INDEX idx_contact_requests_vehicle_id ON contact_requests (vehicle_id);
CREATE INDEX idx_contact_requests_dedup ON contact_requests (
    vehicle_id,
    customer_name,
    phone_number,
    preferred_call_time,
    created_at
);
