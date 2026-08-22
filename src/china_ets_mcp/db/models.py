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
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    cum_volume_reported INTEGER,
    cum_amount_reported REAL,
    cum_volume_derived INTEGER,
    cum_amount_derived REAL
);
-- cea_daily 累計列の列分離(2026-08-22): cumulative_* は出所混成(原典公表値×日次積み上げ)のため
-- 非推奨・凍結。原典公表値=cum_*_reported / 日次total_*の全史累積=cum_*_derived。
-- 列順は既存DBへのALTER TABLE ADD COLUMN(末尾追加)と一致させている。

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
