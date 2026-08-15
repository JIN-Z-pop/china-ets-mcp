"""China ETS MCP Server — CEA/CCER trading data collection and analysis."""
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from .db.manager import DBManager
from .tools.fetcher_cea import fetch_cea_incremental
from .tools.fetcher_ccer import fetch_ccer_incremental
from .tools.query import query_trading_data as _query, get_market_summary as _summary
from .tools.exporter import export_csv, export_xlsx
from .tools.dashboard import generate_dashboard as _gen_dashboard
from .tools.rag_sync import generate_rag_markdown

mcp = FastMCP("china-ets-mcp")

# Default paths
_BASE_DIR = Path(__file__).parent.parent.parent
_DB_PATH = _BASE_DIR / "data" / "china_ets.db"


def _get_db() -> DBManager:
    db = DBManager(_DB_PATH)
    db.init_db()
    return db


@mcp.tool()
def fetch_cea_daily(year: int | None = None) -> str:
    """Fetch latest CEA (Carbon Emission Allowance) daily trading data from Shanghai Exchange.

    Incrementally fetches only new records not yet in the database.
    Args:
        year: Specific year to fetch (default: all years from 2021)
    """
    db = _get_db()
    result = fetch_cea_incremental(db, year)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def fetch_ccer_daily() -> str:
    """Fetch latest CCER (China Certified Emission Reduction) daily trading data.

    Uses hidden JSON API for efficient incremental collection.
    """
    db = _get_db()
    result = fetch_ccer_incremental(db)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def fetch_all() -> str:
    """Fetch both CEA and CCER daily trading data in one call."""
    db = _get_db()
    cea_result = fetch_cea_incremental(db)
    ccer_result = fetch_ccer_incremental(db)
    return json.dumps({"cea": cea_result, "ccer": ccer_result}, ensure_ascii=False)


@mcp.tool()
def query_trading_data(market: str, start_date: str, end_date: str) -> str:
    """Query historical trading data for a date range.

    Args:
        market: 'cea' or 'ccer'
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    """
    db = _get_db()
    data = _query(db, market, start_date, end_date)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def get_market_summary(market: str = "both") -> str:
    """Get market summary statistics (latest price, historical stats).

    Args:
        market: 'cea', 'ccer', or 'both' (default: 'both')
    """
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
    """Generate interactive React+Plotly HTML dashboard with all market data.

    Args:
        output_path: Optional custom output path (default: data/dashboard.html)
    """
    db = _get_db()
    path = output_path or str(_BASE_DIR / "data" / "dashboard.html")
    result = _gen_dashboard(db, path)
    return json.dumps({"path": result, "status": "generated"})


@mcp.tool()
def register_to_rag(market: str = "both") -> str:
    """Generate Markdown report for Knowledge Brain RAG registration.

    Args:
        market: 'cea', 'ccer', or 'both' (default: 'both')
    """
    db = _get_db()
    markdown = generate_rag_markdown(db, market)
    output_path = _BASE_DIR / "data" / "rag_report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return json.dumps({
        "path": str(output_path),
        "market": market,
        "status": "generated",
        "note": "Use kb_register or kb_update to register this file to RAG",
    })


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
