"""SQLite schema definitions."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cea_daily (
    date TEXT PRIMARY KEY,
    opening_price REAL,
    high_price REAL,
    low_price REAL,
    closing_price REAL,
    listed_volume INTEGER,
    listed_amount REAL,
    block_volume INTEGER,
    block_amount REAL,
    total_volume INTEGER,
    total_amount REAL,
    cumulative_volume INTEGER,
    cumulative_amount REAL,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ccer_daily (
    date TEXT PRIMARY KEY,
    daily_volume INTEGER,
    daily_amount REAL,
    avg_price REAL,
    cumulative_volume INTEGER,
    cumulative_amount REAL,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    records_added INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    message TEXT
);
"""
