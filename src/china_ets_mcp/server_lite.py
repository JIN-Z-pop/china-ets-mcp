"""China ETS MCP Server (Lite) — Dashboard & Data Query Tools.

Public-facing server with 4 read-only tools for querying and visualizing
China's national carbon market (CEA/CCER) trading data.
"""
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from .db.manager import DBManager
from .tools.query import query_trading_data as _query, get_market_summary as _summary
from .tools.exporter import export_csv, export_xlsx
from .tools.dashboard import generate_dashboard as _gen_dashboard

mcp = FastMCP("china-ets-mcp")

_BASE_DIR = Path(__file__).parent.parent.parent
_DB_PATH = _BASE_DIR / "data" / "china_ets.db"
_VALID_MARKETS = ("cea", "ccer")


def _get_db() -> DBManager:
    db = DBManager(_DB_PATH)
    db.init_db()
    return db


def _validate_market(market: str, allow_both: bool = False) -> None:
    valid = (*_VALID_MARKETS, "both") if allow_both else _VALID_MARKETS
    if market not in valid:
        raise ValueError(f"market must be one of {valid}, got '{market}'")


def _validate_output_path(path: str) -> Path:
    resolved = Path(path).resolve()
    allowed = (_BASE_DIR / "data").resolve()
    if not str(resolved).startswith(str(allowed)):
        raise ValueError(f"Output path must be within {allowed}")
    return resolved


@mcp.tool()
def query_trading_data(market: str, start_date: str, end_date: str) -> str:
    """Query historical trading data for a date range.

    Args:
        market: 'cea' or 'ccer'
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    """
    _validate_market(market)
    db = _get_db()
    data = _query(db, market, start_date, end_date)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def get_market_summary(market: str = "both") -> str:
    """Get market summary statistics (latest price, historical stats).

    Args:
        market: 'cea', 'ccer', or 'both' (default: 'both')
    """
    _validate_market(market, allow_both=True)
    db = _get_db()
    summary = _summary(db, market)
    return json.dumps(summary, ensure_ascii=False)


@mcp.tool()
def download_data(market: str, format: str = "csv", start_date: str | None = None, end_date: str | None = None) -> str:
    """Export trading data as CSV or XLSX file.

    Args:
        market: 'cea' or 'ccer'
        format: 'csv' or 'xlsx' (default: 'csv')
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
    """
    _validate_market(market)
    db = _get_db()
    output_dir = _BASE_DIR / "data" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)

    ext = "xlsx" if format == "xlsx" else "csv"
    filename = f"{market}_trading_data.{ext}"
    output_path = str(output_dir / filename)

    if format == "xlsx":
        export_xlsx(db, market, output_path, start_date, end_date)
    else:
        export_csv(db, market, output_path, start_date, end_date)

    return json.dumps({"path": output_path, "format": format, "market": market})


@mcp.tool()
def generate_dashboard(output_path: str | None = None) -> str:
    """Generate interactive Plotly HTML dashboard with all market data.

    Args:
        output_path: Optional custom output path (default: data/dashboard.html)
    """
    db = _get_db()
    path = output_path or str(_BASE_DIR / "data" / "dashboard.html")
    _validate_output_path(path)
    result = _gen_dashboard(db, path)
    return json.dumps({"path": result, "status": "generated"})


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
