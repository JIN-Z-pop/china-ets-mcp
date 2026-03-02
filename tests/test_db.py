"""Tests for database manager."""
import os
import tempfile
import pytest
from china_ets_mcp.db.manager import DBManager


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    mgr = DBManager(path)
    mgr.init_db()
    yield mgr
    import gc; gc.collect()
    try:
        os.unlink(path)
    except PermissionError:
        pass


def test_init_creates_tables(db):
    tables = db.get_tables()
    assert "cea_daily" in tables
    assert "ccer_daily" in tables
    assert "fetch_log" in tables


def test_insert_cea_record(db):
    record = {
        "date": "2025-01-15",
        "opening_price": 90.0, "high_price": 91.5,
        "low_price": 89.0, "closing_price": 90.5,
        "listed_volume": 100000, "listed_amount": 9050000.0,
        "block_volume": 50000, "block_amount": 4525000.0,
        "total_volume": 150000, "total_amount": 13575000.0,
        "cumulative_volume": 800000000, "cumulative_amount": 50000000000.0,
    }
    inserted = db.insert_cea(record)
    assert inserted == 1
    # Duplicate should be ignored
    inserted2 = db.insert_cea(record)
    assert inserted2 == 0


def test_insert_ccer_record(db):
    record = {
        "date": "2025-01-15",
        "daily_volume": 500, "daily_amount": 37500.0,
        "avg_price": 75.0,
        "cumulative_volume": 6000000, "cumulative_amount": 450000000.0,
    }
    inserted = db.insert_ccer(record)
    assert inserted == 1


def test_query_cea_date_range(db):
    for i in range(1, 4):
        db.insert_cea({
            "date": f"2025-01-{i:02d}",
            "opening_price": 90.0 + i, "high_price": 91.0 + i,
            "low_price": 89.0 + i, "closing_price": 90.0 + i,
            "listed_volume": 100000, "listed_amount": 9000000.0,
            "block_volume": 0, "block_amount": 0.0,
            "total_volume": 100000, "total_amount": 9000000.0,
            "cumulative_volume": 800000000, "cumulative_amount": 50000000000.0,
        })
    results = db.query_cea("2025-01-01", "2025-01-02")
    assert len(results) == 2


def test_get_latest_cea_date(db):
    assert db.get_latest_date("cea") is None
    db.insert_cea({
        "date": "2025-06-15",
        "opening_price": 90.0, "high_price": 91.0,
        "low_price": 89.0, "closing_price": 90.0,
        "listed_volume": 100000, "listed_amount": 9000000.0,
        "block_volume": 0, "block_amount": 0.0,
        "total_volume": 100000, "total_amount": 9000000.0,
        "cumulative_volume": 800000000, "cumulative_amount": 50000000000.0,
    })
    assert db.get_latest_date("cea") == "2025-06-15"


def test_log_fetch(db):
    db.log_fetch("cea", 5, "success", "OK")
    logs = db.get_fetch_logs(limit=1)
    assert len(logs) == 1
    assert logs[0]["market"] == "cea"
    assert logs[0]["records_added"] == 5


def test_get_cea_summary(db):
    db.insert_cea({
        "date": "2025-01-01",
        "opening_price": 90.0, "high_price": 95.0,
        "low_price": 85.0, "closing_price": 92.0,
        "listed_volume": 100000, "listed_amount": 9200000.0,
        "block_volume": 0, "block_amount": 0.0,
        "total_volume": 100000, "total_amount": 9200000.0,
        "cumulative_volume": 800000000, "cumulative_amount": 50000000000.0,
    })
    summary = db.get_cea_summary()
    assert summary["total_trading_days"] == 1
    assert summary["latest_closing_price"] == 92.0
