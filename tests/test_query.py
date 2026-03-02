"""Tests for query and export tools."""
import os
import gc
import tempfile
import pytest
from china_ets_mcp.db.manager import DBManager
from china_ets_mcp.tools.query import query_trading_data, get_market_summary
from china_ets_mcp.tools.exporter import export_csv, export_xlsx


@pytest.fixture
def db_with_data():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = DBManager(path)
    db.init_db()
    for i in range(1, 6):
        db.insert_cea({
            "date": f"2025-01-{i:02d}",
            "opening_price": 90.0 + i, "high_price": 92.0 + i,
            "low_price": 88.0 + i, "closing_price": 91.0 + i,
            "listed_volume": 100000 * i, "listed_amount": 9100000.0 * i,
            "block_volume": 50000 * i, "block_amount": 4550000.0 * i,
            "total_volume": 150000 * i, "total_amount": 13650000.0 * i,
            "cumulative_volume": 800000000 + 150000 * i,
            "cumulative_amount": 50000000000.0 + 13650000.0 * i,
        })
    for i in range(1, 4):
        db.insert_ccer({
            "date": f"2025-01-{i:02d}",
            "daily_volume": 500 * i, "daily_amount": 37500.0 * i,
            "avg_price": 75.0 + i,
            "cumulative_volume": 6000000 + 500 * i,
            "cumulative_amount": 450000000.0 + 37500.0 * i,
        })
    yield db
    gc.collect()
    try:
        os.unlink(path)
    except PermissionError:
        pass


def test_query_cea(db_with_data):
    result = query_trading_data(db_with_data, "cea", "2025-01-01", "2025-01-03")
    assert len(result) == 3


def test_query_ccer(db_with_data):
    result = query_trading_data(db_with_data, "ccer", "2025-01-01", "2025-01-03")
    assert len(result) == 3


def test_market_summary(db_with_data):
    summary = get_market_summary(db_with_data, "both")
    assert "cea" in summary
    assert "ccer" in summary
    assert summary["cea"]["total_trading_days"] == 5


def test_export_csv(db_with_data):
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    export_csv(db_with_data, "cea", path)
    with open(path, encoding="utf-8-sig") as f:
        lines = f.readlines()
    assert len(lines) == 6  # header + 5 rows
    os.unlink(path)


def test_export_xlsx(db_with_data):
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    export_xlsx(db_with_data, "cea", path)
    assert os.path.exists(path)
    assert os.path.getsize(path) > 0
    os.unlink(path)
