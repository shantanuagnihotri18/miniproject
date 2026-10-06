"""Thin data-access layer. SQL is standard with '?' placeholders; to move to PostgreSQL/MySQL swap get_conn()
(and the placeholder style / AUTOINCREMENT syntax) in this one file."""
import json
import os
import sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT, latitude REAL NOT NULL, longitude REAL NOT NULL, area_sqft REAL NOT NULL,
    predicted_price REAL NOT NULL, predicted_price_per_sqft REAL NOT NULL, prediction_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, property_id INTEGER REFERENCES properties(id), latitude REAL NOT NULL,
    longitude REAL NOT NULL, address TEXT, city TEXT, locality TEXT);
CREATE TABLE IF NOT EXISTS facilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT, property_id INTEGER REFERENCES properties(id), name TEXT, type TEXT,
    latitude REAL, longitude REAL, distance_km REAL, source TEXT);
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, property_id INTEGER NOT NULL REFERENCES properties(id),
    predicted_price_per_sqft REAL NOT NULL, estimated_total_value REAL NOT NULL, lower_estimate REAL NOT NULL,
    upper_estimate REAL NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL, details_json TEXT);
"""


def db_path():
    p = os.getenv("DATABASE_PATH", "database/property.db")
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def get_conn():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(db_path()), exist_ok=True)
    with get_conn() as c:
        c.executescript(SCHEMA)


def save_prediction(result, location, facilities):
    """Stores property, location, nearest facilities and prediction in one transaction. Returns prediction id."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO properties (latitude, longitude, area_sqft, predicted_price, predicted_price_per_sqft, prediction_date) VALUES (?,?,?,?,?,?)",
                (result["latitude"], result["longitude"], result["area_sqft"], result["estimated_property_value"],
                 result["predicted_price_per_sqft"], now))
            pid = cur.lastrowid
            conn.execute("INSERT INTO locations (property_id, latitude, longitude, address, city, locality) VALUES (?,?,?,?,?,?)",
                         (pid, result["latitude"], result["longitude"], location.get("address"), location.get("city"), location.get("locality")))
            conn.executemany(
                "INSERT INTO facilities (property_id, name, type, latitude, longitude, distance_km, source) VALUES (?,?,?,?,?,?,?)",
                [(pid, f["name"], f["type"], f["latitude"], f["longitude"], f["distance_km"], result["facility_source"]) for f in facilities[:40]])
            cur = conn.execute(
                "INSERT INTO predictions (property_id, predicted_price_per_sqft, estimated_total_value, lower_estimate, upper_estimate, model_name, created_at) VALUES (?,?,?,?,?,?,?)",
                (pid, result["predicted_price_per_sqft"], result["estimated_property_value"], result["lower_estimate"],
                 result["upper_estimate"], result["model"], now))
            prid = cur.lastrowid
            result = dict(result, id=prid, created_at=now)
            conn.execute("UPDATE predictions SET details_json = ? WHERE id = ?", (json.dumps(result), prid))
        return prid, now
    finally:
        conn.close()


def get_prediction(pid):
    with get_conn() as c:
        row = c.execute("SELECT details_json FROM predictions WHERE id = ?", (pid,)).fetchone()
    return json.loads(row["details_json"]) if row and row["details_json"] else None


def history(limit=100):
    with get_conn() as c:
        rows = c.execute(
            """SELECT p.id, p.created_at, pr.latitude, pr.longitude, pr.area_sqft, p.predicted_price_per_sqft,
                      p.estimated_total_value, p.lower_estimate, p.upper_estimate, p.model_name, l.locality, l.address
               FROM predictions p JOIN properties pr ON pr.id = p.property_id
               LEFT JOIN locations l ON l.property_id = pr.id ORDER BY p.id DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]
