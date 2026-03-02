"""Data export to CSV and XLSX."""
import csv
from pathlib import Path
from ..db.manager import DBManager

CEA_FIELDS = [
    "date", "opening_price", "high_price", "low_price", "closing_price",
    "listed_volume", "listed_amount", "block_volume", "block_amount",
    "total_volume", "total_amount", "cumulative_volume", "cumulative_amount",
]

CCER_FIELDS = [
    "date", "daily_volume", "daily_amount", "avg_price",
    "cumulative_volume", "cumulative_amount",
]


def export_csv(db: DBManager, market: str, output_path: str,
               start_date: str | None = None, end_date: str | None = None):
    """Export data to CSV."""
    if market == "cea":
        data = db.query_cea(start_date or "2000-01-01", end_date or "2099-12-31") if start_date or end_date else db.get_all_cea()
        fields = CEA_FIELDS
    else:
        data = db.query_ccer(start_date or "2000-01-01", end_date or "2099-12-31") if start_date or end_date else db.get_all_ccer()
        fields = CCER_FIELDS

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)


def export_xlsx(db: DBManager, market: str, output_path: str,
                start_date: str | None = None, end_date: str | None = None):
    """Export data to XLSX."""
    from openpyxl import Workbook

    if market == "cea":
        data = db.query_cea(start_date or "2000-01-01", end_date or "2099-12-31") if start_date or end_date else db.get_all_cea()
        fields = CEA_FIELDS
    else:
        data = db.query_ccer(start_date or "2000-01-01", end_date or "2099-12-31") if start_date or end_date else db.get_all_ccer()
        fields = CCER_FIELDS

    wb = Workbook()
    ws = wb.active
    ws.title = f"{market.upper()} Daily Data"
    ws.append(fields)
    for row in data:
        ws.append([row.get(f) for f in fields])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
