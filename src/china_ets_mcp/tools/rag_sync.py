"""RAG (Knowledge Brain) integration for registering market data."""
from datetime import datetime
from ..db.manager import DBManager


def generate_rag_markdown(db: DBManager, market: str = "both") -> str:
    """Generate Markdown content for RAG registration."""
    sections = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if market in ("cea", "both"):
        cea_summary = db.get_cea_summary()
        cea_data = db.get_all_cea()
        sections.append(f"""# CEA Daily Trading Data History

**Data Source**: Shanghai Environment & Energy Exchange
**Updated**: {now}
**Total Records**: {cea_summary.get('total_trading_days', 0)}
**Date Range**: {cea_summary.get('first_date', 'N/A')} to {cea_summary.get('last_date', 'N/A')}
**Latest Closing Price**: {cea_summary.get('latest_closing_price', 0):.2f} CNY/ton

## Recent 30 Days

| Date | Close | Volume | Amount |
|------|-------|--------|--------|""")
        for row in cea_data[-30:]:
            sections.append(
                f"| {row['date']} | {row['closing_price']:.2f} | "
                f"{row['total_volume']:,} | {row['total_amount']:,.0f} |"
            )

    if market in ("ccer", "both"):
        ccer_summary = db.get_ccer_summary()
        ccer_data = db.get_all_ccer()
        sections.append(f"""\n# CCER Daily Trading Data History

**Data Source**: CCER Official Website
**Updated**: {now}
**Total Records**: {ccer_summary.get('total_trading_days', 0)}
**Latest Avg Price**: {ccer_summary.get('latest_avg_price', 0):.2f} CNY/ton

## Recent 30 Days

| Date | Avg Price | Volume | Amount |
|------|-----------|--------|--------|""")
        for row in ccer_data[-30:]:
            sections.append(
                f"| {row['date']} | {row['avg_price']:.2f} | "
                f"{row['daily_volume']:,} | {row['daily_amount']:,.0f} |"
            )

    return "\n".join(sections)
