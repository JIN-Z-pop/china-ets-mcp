"""Standalone dashboard CLI — no MCP or Claude Desktop required."""
import webbrowser
from pathlib import Path

from .db.manager import DBManager
from .tools.dashboard import generate_dashboard

_BASE = Path(__file__).resolve().parent.parent.parent
_DB = _BASE / "data" / "china_ets.db"
_OUT = _BASE / "data" / "dashboard.html"


def main() -> None:
    if not _DB.exists():
        print(f"Error: {_DB} not found.")
        print("Download from: https://github.com/JIN-Z-pop/china-ets-mcp/releases")
        raise SystemExit(1)

    db = DBManager(_DB)
    db.init_db()
    path = generate_dashboard(db, str(_OUT))
    webbrowser.open(Path(path).as_uri())
    print(f"Dashboard opened: {path}")


if __name__ == "__main__":
    main()
