PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS contact_requests;
DROP TABLE IF EXISTS vehicles;

CREATE TABLE vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL UNIQUE,
    country_of_origin TEXT NOT NULL,
    year INTEGER NOT NULL CHECK (year BETWEEN 1980 AND 2100),
    mileage_km INTEGER NOT NULL CHECK (mileage_km >= 0),
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    color TEXT NOT NULL,
    description TEXT NOT NULL,
    body_type TEXT NOT NULL,
    transmission_type TEXT NOT NULL CHECK (
        transmission_type IN ('Automatic', 'Manual', 'CVT', 'Dual-Clutch')
    ),
    fuel_type TEXT NOT NULL CHECK (
        fuel_type IN ('Gasoline', 'Diesel', 'Hybrid', 'Plug-in Hybrid', 'Electric', 'Flex Fuel')
    ),
    drivetrain TEXT NOT NULL CHECK (drivetrain IN ('FWD', 'RWD', 'AWD', '4WD')),
    number_of_doors INTEGER NOT NULL CHECK (number_of_doors BETWEEN 2 AND 6),
    engine TEXT,
    price_usd INTEGER NOT NULL CHECK (price_usd > 0),
    is_available INTEGER NOT NULL DEFAULT 1 CHECK (is_available IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
CREATE INDEX idx_contact_requests_vehicle_id ON contact_requests (vehicle_id);
