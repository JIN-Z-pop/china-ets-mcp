"""CEA/CCER価格急変動 自動検知。

日次騰落率が市場別の閾値を超えたらprice_anomaly_logへ記録する。
閾値は2026-08-12時点の実測(直近60営業日 pstdev)から決定:
  CEA:  stdev=0.73% max|ret|=2.18%  -> 閾値3%
  CCER: stdev=5.35% (直近40営業日) -> 閾値10%
市場ごとにボラティリティ水準が大きく異なるため、単一閾値は使わない。

Usage:
  python price_anomaly_detect.py --backfill   # 全履歴を再計算
  python price_anomaly_detect.py              # 直近レコードのみ(日次運用向け)
"""
import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / "Desktop" / "china-ets-mcp" / "data" / "china_ets.db"
THRESHOLDS = {"CEA": 3.0, "CCER": 10.0}
# 毎朝運用のALERT監視は「この日以降の新規trigger」を数える。
# 全履歴(2021-07~)のtrigger累計は歴史的変動の蓄積であり、監視対象と混同しない。
MONITORING_BASELINE = "2026-08-16"

DDL = """
CREATE TABLE IF NOT EXISTS price_anomaly_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL CHECK(market IN ('CEA','CCER')),
    date TEXT NOT NULL,
    metric_name TEXT NOT NULL DEFAULT 'daily_return_pct',
    metric_value REAL NOT NULL,
    threshold REAL NOT NULL,
    triggered INTEGER NOT NULL,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(market, date)
)
"""


def _fetch_series(conn, market):
    if market == "CEA":
        cur = conn.execute(
            "SELECT date, closing_price FROM cea_daily WHERE closing_price > 0 ORDER BY date"
        )
    else:
        cur = conn.execute(
            "SELECT date, avg_price FROM ccer_daily WHERE avg_price > 0 ORDER BY date"
        )
    return cur.fetchall()


def detect(conn, market, backfill=False):
    rows = _fetch_series(conn, market)
    threshold = THRESHOLDS[market]
    target_rows = rows if backfill else rows[-5:]
    inserted = 0
    for i in range(1, len(rows)):
        date, price = rows[i]
        if not backfill and (date, price) not in target_rows:
            continue
        prev_price = rows[i - 1][1]
        ret_pct = (price - prev_price) / prev_price * 100
        triggered = 1 if abs(ret_pct) > threshold else 0
        cur = conn.execute(
            """INSERT OR IGNORE INTO price_anomaly_log
               (market, date, metric_name, metric_value, threshold, triggered, notes)
               VALUES (?, ?, 'daily_return_pct', ?, ?, ?, ?)""",
            (market, date, round(ret_pct, 4), threshold, triggered,
             f"prev={prev_price} curr={price}"),
        )
        inserted += cur.rowcount
    return inserted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="全履歴を再計算")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.execute(DDL)
    for market in ("CEA", "CCER"):
        n = detect(conn, market, backfill=args.backfill)
        print(f"{market}: {n} new rows inserted")
    conn.commit()

    print("\n=== ALERT summary (母集団を明記) ===")
    cur = conn.execute(
        "SELECT COUNT(*) FROM price_anomaly_log WHERE triggered=1 AND date >= ?",
        (MONITORING_BASELINE,),
    )
    new_count = cur.fetchone()[0]
    print(f"  [監視対象] 恒久配線({MONITORING_BASELINE})以降の新規trigger = {new_count}件")
    cur = conn.execute(
        "SELECT market, COUNT(*) FROM price_anomaly_log WHERE triggered=1 GROUP BY market"
    )
    per_market = dict(cur.fetchall())
    total = sum(per_market.values())
    breakdown = " / ".join(f"{m} {n}" for m, n in sorted(per_market.items()))
    print(f"  [歴史累計] 全履歴trigger = {total}件 ({breakdown}) — 監視対象と混同しない")

    cur = conn.execute(
        "SELECT market, date, metric_value, threshold FROM price_anomaly_log WHERE triggered=1 ORDER BY date DESC LIMIT 15"
    )
    print("\n=== Recent triggered anomalies ===")
    for r in cur.fetchall():
        print(f"  {r[0]} {r[1]}: {r[2]:+.2f}% (threshold={r[3]}%)")
    conn.close()


if __name__ == "__main__":
    main()
