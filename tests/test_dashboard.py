"""Tests for dashboard generator."""
import os
import gc
import tempfile
import pytest
from china_ets_mcp.db.manager import DBManager
from china_ets_mcp.tools.dashboard import generate_dashboard


@pytest.fixture
def db_with_data():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = DBManager(path)
    db.init_db()
    for i in range(1, 11):
        db.insert_cea({
            "date": f"2025-01-{i:02d}",
            "opening_price": 90.0 + i, "high_price": 92.0 + i,
            "low_price": 88.0 + i, "closing_price": 91.0 + i,
            "listed_volume": 100000, "listed_amount": 9100000.0,
            "block_volume": 50000, "block_amount": 4550000.0,
            "total_volume": 150000, "total_amount": 13650000.0,
            "cum_volume_reported": 800000000, "cum_amount_reported": 50000000000.0,
        })
    yield db
    gc.collect()
    try:
        os.unlink(path)
    except PermissionError:
        pass


def test_generate_dashboard(db_with_data):
    fd, path = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    result = generate_dashboard(db_with_data, path)
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "plotly" in content.lower() or "Plotly" in content
    assert "CEA" in content
    os.unlink(path)
