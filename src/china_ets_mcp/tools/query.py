"""Query engine for China ETS data."""
from ..db.manager import DBManager


def query_trading_data(db: DBManager, market: str, start_date: str, end_date: str) -> list[dict]:
    """Query trading data for a date range."""
    if market == "cea":
        return db.query_cea(start_date, end_date)
    elif market == "ccer":
        return db.query_ccer(start_date, end_date)
    else:
        raise ValueError(f"Unknown market: {market}. Use 'cea' or 'ccer'.")


def get_market_summary(db: DBManager, market: str = "both") -> dict:
    """Get market summary statistics."""
    result = {}
    if market in ("cea", "both"):
        result["cea"] = db.get_cea_summary()
    if market in ("ccer", "both"):
        result["ccer"] = db.get_ccer_summary()
    return result
