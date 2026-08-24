# [RETIRED 2026-08-24 R-001] superseded by the unified morning pipeline (see repo history)
"""Standalone auto-fetch script for Windows Task Scheduler (05:00 daily)."""
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Add project root to path
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from china_ets_mcp.db.manager import DBManager
from china_ets_mcp.tools.fetcher_cea import fetch_cea_incremental
from china_ets_mcp.tools.fetcher_ccer import fetch_ccer_incremental
from china_ets_mcp.tools.query import get_market_summary
from china_ets_mcp.scheduler.email_report import send_daily_report


def detect_anomalies(db: DBManager, cea_result: dict, ccer_result: dict) -> list[str]:
    """Detect anomalies in fetched data."""
    alerts = []

    if cea_result.get("error"):
        alerts.append(f"CEA fetch error: {cea_result['error']}")
    if ccer_result.get("error"):
        alerts.append(f"CCER fetch error: {ccer_result['error']}")

    # Check for large price changes (>10% from previous day)
    cea_data = db.get_all_cea()
    if len(cea_data) >= 2:
        prev = cea_data[-2]["closing_price"]
        curr = cea_data[-1]["closing_price"]
        if prev > 0:
            change_pct = abs(curr - prev) / prev * 100
            if change_pct > 10:
                alerts.append(
                    f"CEA price anomaly: {change_pct:.1f}% change "
                    f"({prev:.2f} -> {curr:.2f})"
                )

    return alerts


def main():
    load_dotenv(_PROJECT_ROOT / ".env")

    print(f"[{datetime.now().isoformat()}] China ETS Auto-Fetch Starting...")

    db = DBManager(_PROJECT_ROOT / "data" / "china_ets.db")
    db.init_db()

    # Fetch data
    cea_result = fetch_cea_incremental(db)
    print(f"CEA: {cea_result}")

    ccer_result = fetch_ccer_incremental(db)
    print(f"CCER: {ccer_result}")

    # Get summaries
    summaries = get_market_summary(db, "both")

    # Detect anomalies
    alerts = detect_anomalies(db, cea_result, ccer_result)
    if alerts:
        print(f"ALERTS: {alerts}")

    # Send email report
    sender = os.getenv("GMAIL_SENDER")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("GMAIL_RECIPIENT", "jin@iges.or.jp")

    if sender and app_password:
        try:
            email_result = send_daily_report(
                sender, app_password, recipient,
                cea_result, ccer_result,
                summaries.get("cea", {}), summaries.get("ccer", {}),
                alerts,
            )
            print(f"Email sent: {email_result}")
        except Exception as e:
            print(f"Email error: {e}")
    else:
        print("GMAIL credentials not configured. Skipping email.")

    print(f"[{datetime.now().isoformat()}] Auto-Fetch Complete.")


if __name__ == "__main__":
    main()
