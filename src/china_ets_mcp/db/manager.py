"""Database manager for China ETS data."""
import sqlite3
from datetime import datetime
from pathlib import Path
from .models import SCHEMA_SQL


class DBManager:
    def __init__(self, db_path: str | Path = "data/china_ets.db"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def close(self):
        """Ensure no lingering connections (for Windows file cleanup)."""
        pass  # Each method opens/closes its own connection via context manager

    def init_db(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def get_tables(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return [r["name"] for r in rows]

    def insert_cea(self, record: dict) -> int:
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO cea_daily
                    (date, opening_price, high_price, low_price, closing_price,
                     listed_volume, listed_amount, block_volume, block_amount,
                     total_volume, total_amount, cumulative_volume, cumulative_amount)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (record["date"], record["opening_price"], record["high_price"],
                     record["low_price"], record["closing_price"],
                     record["listed_volume"], record["listed_amount"],
                     record["block_volume"], record["block_amount"],
                     record["total_volume"], record["total_amount"],
                     record["cumulative_volume"], record["cumulative_amount"]),
                )
                return 1
            except sqlite3.IntegrityError:
                return 0

    def insert_ccer(self, record: dict) -> int:
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO ccer_daily
                    (date, daily_volume, daily_amount, avg_price,
                     cumulative_volume, cumulative_amount)
                    VALUES (?,?,?,?,?,?)""",
                    (record["date"], record["daily_volume"], record["daily_amount"],
                     record["avg_price"], record["cumulative_volume"],
                     record["cumulative_amount"]),
                )
                return 1
            except sqlite3.IntegrityError:
                return 0

    def query_cea(self, start_date: str, end_date: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cea_daily WHERE date BETWEEN ? AND ? ORDER BY date",
                (start_date, end_date),
            ).fetchall()
            return [dict(r) for r in rows]

    def query_ccer(self, start_date: str, end_date: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ccer_daily WHERE date BETWEEN ? AND ? ORDER BY date",
                (start_date, end_date),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_cea(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cea_daily ORDER BY date"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_ccer(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ccer_daily ORDER BY date"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_latest_date(self, market: str) -> str | None:
        _TABLES = {"cea": "cea_daily", "ccer": "ccer_daily"}
        table = _TABLES.get(market)
        if table is None:
            raise ValueError(f"Unknown market: {market}. Use 'cea' or 'ccer'.")
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT MAX(date) as max_date FROM {table}"
            ).fetchone()
            return row["max_date"] if row else None

    def log_fetch(self, market: str, records_added: int, status: str, message: str):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO fetch_log (market, fetched_at, records_added, status, message)
                VALUES (?, ?, ?, ?, ?)""",
                (market, datetime.now().isoformat(), records_added, status, message),
            )

    def get_fetch_logs(self, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fetch_log ORDER BY fetched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_cea_summary(self) -> dict:
        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_trading_days,
                    MIN(date) as first_date,
                    MAX(date) as last_date,
                    MIN(closing_price) as min_price,
                    MAX(closing_price) as max_price,
                    AVG(closing_price) as avg_price,
                    (SELECT closing_price FROM cea_daily ORDER BY date DESC LIMIT 1) as latest_closing_price
                FROM cea_daily
                WHERE closing_price > 0
            """).fetchone()
            return dict(row) if row else {}

    def get_ccer_summary(self) -> dict:
        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_trading_days,
                    MIN(date) as first_date,
                    MAX(date) as last_date,
                    MIN(avg_price) as min_price,
                    MAX(avg_price) as max_price,
                    AVG(avg_price) as avg_price,
                    (SELECT avg_price FROM ccer_daily ORDER BY date DESC LIMIT 1) as latest_avg_price
                FROM ccer_daily
                WHERE avg_price > 0
            """).fetchone()
            return dict(row) if row else {}
