"""Behavioural tests: both MCP servers reject bad arguments before touching the filesystem.

Every test runs against a throw-away copy of the repository layout under ``tmp_path``:
the servers' base directory and database path are redirected there, so a test that
fails (i.e. a bad argument is wrongly accepted) can only write inside ``tmp_path``.
"""
import hashlib
import importlib
import json
import shutil
from pathlib import Path

import pytest

SERVERS = ["china_ets_mcp.server", "china_ets_mcp.server_lite"]


def _tool(mod, name):
    obj = getattr(mod, name)
    return getattr(obj, "fn", obj)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_sandbox(modname, tmp_path, monkeypatch):
    mod = importlib.import_module(modname)
    base = tmp_path / "repo"
    (base / "data").mkdir(parents=True)
    replica = base / "data" / "china_ets.db"
    real_db = Path(mod._DB_PATH)
    if real_db.exists():
        shutil.copyfile(real_db, replica)
    else:
        from china_ets_mcp.db.manager import DBManager
        DBManager(replica).init_db()
    monkeypatch.setattr(mod, "_BASE_DIR", base)
    monkeypatch.setattr(mod, "_DB_PATH", replica)
    return mod, base, replica


@pytest.fixture(scope="module", autouse=True)
def real_database_is_untouched():
    """Guard: nothing in this module may change the real database file."""
    real = Path(importlib.import_module("china_ets_mcp.server_lite")._DB_PATH)
    before = _sha256(real) if real.exists() else None
    yield
    after = _sha256(real) if real.exists() else None
    assert after == before, "a test modified the real database file"


@pytest.fixture(params=SERVERS)
def sandbox(request, tmp_path, monkeypatch):
    return _make_sandbox(request.param, tmp_path, monkeypatch)


# --- bad input: nothing may be written, and nothing may be created -------------

def test_rejects_output_path_outside_data(sandbox):
    mod, base, _ = sandbox
    target = base.parent / "outside" / "a.html"
    with pytest.raises(ValueError, match="Output path must be within"):
        _tool(mod, "generate_dashboard")(output_path=str(target))
    assert not target.exists()
    assert not target.parent.exists()


def test_rejects_market_with_path_segments(sandbox):
    mod, base, _ = sandbox
    target = (base / "data" / "exports" / ".." / ".." / "x_trading_data.csv").resolve()
    with pytest.raises(ValueError, match="market must be one of"):
        _tool(mod, "download_data")(market="../../x")  # default format (csv)
    assert not target.exists()
    assert not (base / "data" / "exports").exists()  # the check ran before any mkdir


def test_rejects_sibling_directory_of_data(sandbox):
    mod, base, _ = sandbox
    target = base / "data_evil" / "x.html"
    with pytest.raises(ValueError, match="Output path must be within"):
        _tool(mod, "generate_dashboard")(output_path=str(target))
    assert not target.exists()
    assert not target.parent.exists()


def test_rejects_overwriting_the_database_file(sandbox):
    mod, _, replica = sandbox
    before = _sha256(replica)
    with pytest.raises(ValueError, match="extensions"):
        _tool(mod, "generate_dashboard")(output_path=str(replica))
    assert _sha256(replica) == before


def test_rejects_unknown_export_format(sandbox):
    mod, base, _ = sandbox
    with pytest.raises(ValueError, match="format must be one of"):
        _tool(mod, "download_data")("cea", format="evil")
    assert not (base / "data" / "exports").exists()


def test_rejects_unknown_market_in_summary(sandbox):
    mod, _, _ = sandbox
    with pytest.raises(ValueError, match="market must be one of"):
        _tool(mod, "get_market_summary")(market="evil")


def test_rejects_unknown_market_in_query(sandbox):
    mod, _, _ = sandbox
    with pytest.raises(ValueError, match="market must be one of"):
        _tool(mod, "query_trading_data")(market="../../x", start_date="2026-01-01", end_date="2026-01-31")


def test_rejects_unknown_market_in_rag_report(tmp_path, monkeypatch):
    mod, base, _ = _make_sandbox("china_ets_mcp.server", tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="market must be one of"):
        _tool(mod, "register_to_rag")(market="evil")
    assert not (base / "data" / "rag_report.md").exists()


# --- good input: the same tools still work as before ---------------------------

def test_accepts_default_dashboard(sandbox):
    mod, base, _ = sandbox
    result = json.loads(_tool(mod, "generate_dashboard")())
    expected = (base / "data" / "dashboard.html").resolve()
    assert Path(result["path"]).resolve() == expected
    assert result["status"] == "generated"
    assert expected.exists()


def test_accepts_uppercase_html_suffix_in_a_subdirectory(sandbox):
    mod, base, _ = sandbox
    target = base / "data" / "reports" / "Report.HTML"
    _tool(mod, "generate_dashboard")(output_path=str(target))
    assert target.exists()


def test_accepts_default_csv_export(sandbox):
    mod, base, _ = sandbox
    result = json.loads(_tool(mod, "download_data")("cea"))
    assert result["format"] == "csv" and result["market"] == "cea"
    assert (base / "data" / "exports" / "cea_trading_data.csv").exists()


def test_accepts_xlsx_export(sandbox):
    mod, base, _ = sandbox
    result = json.loads(_tool(mod, "download_data")("ccer", "xlsx"))
    assert result["format"] == "xlsx" and result["market"] == "ccer"
    assert (base / "data" / "exports" / "ccer_trading_data.xlsx").exists()
