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
import bisect
import datetime
import sqlite3
import statistics
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

# --- 多軸指標(price_anomaly_metrics) ---
# 閾値の出典識別子。出典本体は運用側の観測記録に保管されており、この値は
# その記録を引くための鍵(ファイル名のみ・パスではない)。
BASELINE_REF = "anomaly_threshold_freeze_20260830"

DDL_METRICS = """
CREATE TABLE IF NOT EXISTS price_anomaly_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    margin REAL NOT NULL,
    date TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    threshold REAL NOT NULL,
    triggered INTEGER NOT NULL,
    formula TEXT NOT NULL,
    baseline_ref TEXT,
    source_fetched_at TEXT NOT NULL,
    gap_trading_days INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(market, date, metric_name)
)
"""

# 判定式(この文字列のまま閾値の出典と対応する)。metric_valueは符号付き生値、
# vは判定式の左辺(abs適用の有無はここで決まる。margin/triggeredの計算はv基準に統一する
# ことで片側/両側の分岐自体をなくす設計)。
FORMULAS = {
    "intraday_range_pct": "intraday_range_pct > 4.60",
    "open_gap_pct_abs": "abs(open_gap_pct) > 2.40",
    "daily_return_pct_abs_ccer": "abs(daily_return_pct) > 10.00",
    "listed_volume_z": "listed_volume_z(window=直近60有効観測・当日を除く・0/NULL除外・pstdev) > 1.99",
    "block_volume_ratio_n20": "block_volume_ratio_n20 > 3.45",
}
# vにabsを適用するmetric(=キー名に_absが付くもの)。それ以外は生値がそのまま左辺(非負構造
# または片側判定のため)。
ABS_METRICS = {"open_gap_pct_abs", "daily_return_pct_abs_ccer"}
THRESHOLDS_METRICS = {
    ("CEA", "intraday_range_pct"): 4.60,
    ("CEA", "open_gap_pct_abs"): 2.40,
    ("CCER", "daily_return_pct_abs_ccer"): 10.00,
    ("CEA", "listed_volume_z"): 1.99,
    ("CEA", "block_volume_ratio_n20"): 3.45,
}

UPSERT_METRICS_SQL = """
INSERT INTO price_anomaly_metrics
    (market, margin, date, metric_name, metric_value, threshold, triggered,
     formula, baseline_ref, source_fetched_at, gap_trading_days)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(market, date, metric_name) DO UPDATE SET
    margin=excluded.margin, metric_value=excluded.metric_value,
    threshold=excluded.threshold, triggered=excluded.triggered,
    formula=excluded.formula, baseline_ref=excluded.baseline_ref,
    source_fetched_at=excluded.source_fetched_at, gap_trading_days=excluded.gap_trading_days
WHERE excluded.source_fetched_at > price_anomaly_metrics.source_fetched_at
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

    # CCERのみ: _fetch_seriesはavg_price>0で疎らな行を詰めるため、rows[i-1]は暦日で
    # 隣接するとは限らない(prev取違え是正2026-08-30)。CEA取引日カレンダーを代理とした
    # gap_trading_daysで「真の日次か」を判定し、非日次ならtriggered=0固定にする。
    # CEAは無変更(元々cea_daily自身の記録でgapが生じない=A0で自己検証済み)。
    cea_dates_sorted = None
    if market == "CCER":
        cea_dates_sorted = [
            datetime.date.fromisoformat(r[0])
            for r in conn.execute("SELECT date FROM cea_daily ORDER BY date").fetchall()
        ]

    for i in range(1, len(rows)):
        date, price = rows[i]
        if not backfill and (date, price) not in target_rows:
            continue
        prev_date, prev_price = rows[i - 1]
        ret_pct = (price - prev_price) / prev_price * 100
        notes = f"prev={prev_price} curr={price}"

        if market == "CCER":
            gtd = gap_trading_days(
                datetime.date.fromisoformat(prev_date),
                datetime.date.fromisoformat(date),
                cea_dates_sorted,
            )
            if gtd > 1:
                triggered = 0
                notes = f"非日次(gap_trading_days={gtd}・prev={prev_date}): 判定対象外"
            else:
                triggered = 1 if abs(ret_pct) > threshold else 0
        else:
            triggered = 1 if abs(ret_pct) > threshold else 0

        cur = conn.execute(
            """INSERT OR IGNORE INTO price_anomaly_log
               (market, date, metric_name, metric_value, threshold, triggered, notes)
               VALUES (?, ?, 'daily_return_pct', ?, ?, ?, ?)""",
            (market, date, round(ret_pct, 4), threshold, triggered, notes),
        )
        inserted += cur.rowcount
    return inserted


def gap_trading_days(prev_date, cur_date, cea_dates_sorted):
    """CEAの実取引日記録を市場カレンダーの代理として使ったgap(取引日単位)。
    prev_date < d <= cur_date を満たすCEA取引日の数(A0 anomaly_baseline_cea_ccer_20260830.py
    と同一ロジック)。"""
    lo = bisect.bisect_right(cea_dates_sorted, prev_date)
    hi = bisect.bisect_right(cea_dates_sorted, cur_date)
    return hi - lo


CCER_GAP_FIX_MARKER = "是正 2026-08-30: 非日次(gap="


def backfill_ccer_gap_fix(conn):
    """既存price_anomaly_log(CCER)のうち、prev取違え(疎らな行同士の比較)で誤って
    daily_return_pctとして判定されていた行(gap_trading_days>1)をtriggered=0へ是正する。
    DELETE禁止・履歴(metric_value/notesの元の文言)は残し、末尾に是正notesを追記する。
    冪等: CCER_GAP_FIX_MARKERが既にnotesに含まれる行は再更新しない(2回目以降0行)。

    戻り値: (更新行数, うちtriggered変化行数, うちnotesのみ変化行数)。29行全部が
    「判定対象外」に是正されるが、元々triggered=0だった行はtriggered自体は変わらない
    (「0にした」行と「判定しなかった」行を同じ数字で語らない・#136)。"""
    cea_dates_sorted = [
        datetime.date.fromisoformat(r[0])
        for r in conn.execute("SELECT date FROM cea_daily ORDER BY date").fetchall()
    ]
    ccer_dates = [
        r[0] for r in conn.execute(
            "SELECT date FROM ccer_daily WHERE avg_price > 0 ORDER BY date"
        ).fetchall()
    ]

    updated = 0
    triggered_changed = 0
    for i in range(1, len(ccer_dates)):
        date_s, prev_date_s = ccer_dates[i], ccer_dates[i - 1]
        gtd = gap_trading_days(
            datetime.date.fromisoformat(prev_date_s),
            datetime.date.fromisoformat(date_s),
            cea_dates_sorted,
        )
        if gtd <= 1:
            continue
        row = conn.execute(
            "SELECT id, triggered, notes FROM price_anomaly_log WHERE market='CCER' AND date=?",
            (date_s,),
        ).fetchone()
        if row is None:
            continue
        log_id, old_triggered, notes = row
        marker = f"{CCER_GAP_FIX_MARKER}{gtd})"
        if notes and CCER_GAP_FIX_MARKER in notes:
            continue
        new_notes = f"{notes} / {marker}" if notes else marker
        conn.execute(
            "UPDATE price_anomaly_log SET triggered=0, notes=? WHERE id=?",
            (new_notes, log_id),
        )
        updated += 1
        if old_triggered != 0:
            triggered_changed += 1
    return updated, triggered_changed, updated - triggered_changed


def compute_v(metric_name, metric_value):
    """判定式の左辺v。absを取るかどうかは左辺の定義そのものに属する(abs(open_gap_pct)/
    abs(daily_return_pct)は判定式に明記されている)ため、metric側で分岐せずここで一元化する。
    intraday_range_pct(非負構造)・listed_volume_z/block_volume_ratio_n20(片側判定)は
    metric_valueがそのままv。"""
    if metric_name in ABS_METRICS:
        return abs(metric_value)
    return metric_value


def upsert_metric(conn, market, date, metric_name, metric_value, gap_td, source_fetched_at):
    """margin = threshold - v・triggered = (v > threshold)。数値は6桁に丸める
    (凍結節の閾値自体は小数第2位で固定済み・vは丸めずフル精度で比較してから丸めて保存)。"""
    threshold = THRESHOLDS_METRICS[(market, metric_name)]
    v = compute_v(metric_name, metric_value)
    triggered = 1 if v > threshold else 0
    margin = threshold - v
    cur = conn.execute(
        UPSERT_METRICS_SQL,
        (market, round(margin, 6), date, metric_name, round(metric_value, 6), threshold,
         triggered, FORMULAS[metric_name], BASELINE_REF, source_fetched_at, gap_td),
    )
    return cur.rowcount


def compute_cea_series(cea_rows):
    """cea_daily全行から4指標(intraday_range_pct/open_gap_pct_abs/listed_volume_z/
    block_volume_ratio_n20)の系列を計算する。各要素=(date, metric_value, gap_trading_days,
    source_fetched_at)。SKIP件数は数字層として別途返す(#136: 代理と分かる形で出す)。

    SKIP対象(行を作らない):
      - 系列初日(prev_close不在) -> intraday/gapの対象外
      - listed_volume_z: 直近60有効観測に満たない/std60==0
      - block_volume_ratio_n20: 直近20非0日に満たない/median20==0
      - listed/block: 当日値が0またはNULL(母集団に入らない)
    """
    cea_dates_sorted = [datetime.date.fromisoformat(r[0]) for r in cea_rows]
    date_index = {r[0]: i for i, r in enumerate(cea_rows)}

    intraday, gap = [], []
    listed_vals_by_date = {}
    block_vals = []
    skip_first_day = 0

    for i, (d, o, h, l, c, lv, bv, fa) in enumerate(cea_rows):
        if lv is not None and lv != 0:
            listed_vals_by_date[d] = (lv, fa)
        if bv is not None and bv != 0:
            block_vals.append((d, bv, fa))
        if i == 0:
            skip_first_day += 1
            continue
        prev_close = cea_rows[i - 1][4]
        if prev_close and prev_close != 0:
            gtd = gap_trading_days(cea_dates_sorted[i - 1], cea_dates_sorted[i], cea_dates_sorted)
            intraday.append((d, (h - l) / prev_close * 100, gtd, fa))
            gap.append((d, (o - prev_close) / prev_close * 100, gtd, fa))

    def _gtd_for(d):
        idx = date_index[d]
        if idx == 0:
            return 1
        return gap_trading_days(cea_dates_sorted[idx - 1], cea_dates_sorted[idx], cea_dates_sorted)

    valid_dates_sorted = sorted(listed_vals_by_date.keys())
    listed_z = []
    listed_insufficient = 0
    listed_skip_std0 = 0
    for i, d in enumerate(valid_dates_sorted):
        if i < 60:
            listed_insufficient += 1
            continue
        window_vals = [listed_vals_by_date[valid_dates_sorted[j]][0] for j in range(i - 60, i)]
        std60 = statistics.pstdev(window_vals)
        if std60 == 0:
            listed_skip_std0 += 1
            continue
        mean60 = statistics.mean(window_vals)
        val, fa = listed_vals_by_date[d]
        listed_z.append((d, (val - mean60) / std60, _gtd_for(d), fa))

    block_ratio = []
    block_insufficient = 0
    block_skip_med0 = 0
    for i in range(len(block_vals)):
        d, bv, fa = block_vals[i]
        window = [v for _, v, _ in block_vals[max(0, i - 20):i]]
        if len(window) < 20:
            block_insufficient += 1
            continue
        med20 = statistics.median(window)
        if med20 == 0:
            block_skip_med0 += 1
            continue
        block_ratio.append((d, bv / med20, _gtd_for(d), fa))

    skip_counts = {
        "cea_skip_first_day": skip_first_day,
        "listed_zero_or_null": len(cea_rows) - len(listed_vals_by_date),
        "listed_insufficient_60": listed_insufficient,
        "listed_skip_std0": listed_skip_std0,
        "block_zero_or_null": len(cea_rows) - len(block_vals),
        "block_insufficient_20": block_insufficient,
        "block_skip_med0": block_skip_med0,
    }
    return {
        "intraday_range_pct": intraday,
        "open_gap_pct_abs": gap,
        "listed_volume_z": listed_z,
        "block_volume_ratio_n20": block_ratio,
    }, skip_counts, cea_dates_sorted


def compute_ccer_series(ccer_rows, cea_dates_sorted):
    """ccer_daily全行からdaily_return_pct_abs_ccerの系列を計算する。
    gap_trading_daysはCEA取引日カレンダーを代理として使う(市場によらず1本のカレンダー)。"""
    returns = []
    prev_missing = 0
    for i in range(1, len(ccer_rows)):
        d, price, fa = ccer_rows[i]
        prev_price = ccer_rows[i - 1][1]
        if not prev_price:
            prev_missing += 1
            continue
        prev_date = datetime.date.fromisoformat(ccer_rows[i - 1][0])
        cur_date = datetime.date.fromisoformat(d)
        gtd = gap_trading_days(prev_date, cur_date, cea_dates_sorted)
        returns.append((d, (price - prev_price) / prev_price * 100, gtd, fa))
    return {"daily_return_pct_abs_ccer": returns}, {"ccer_prev_missing": prev_missing}


def detect_metrics(conn, backfill=False):
    """5指標の多軸検知をprice_anomaly_metricsへupsertする。戻り値=(更新行数, SKIP件数dict,
    系列dict{(market,metric_name): [...]})。既存price_anomaly_log/detect()には触れない。"""
    cea_rows = conn.execute(
        "SELECT date, opening_price, high_price, low_price, closing_price, "
        "listed_volume, block_volume, fetched_at FROM cea_daily ORDER BY date"
    ).fetchall()
    ccer_rows = conn.execute(
        "SELECT date, avg_price, fetched_at FROM ccer_daily WHERE avg_price > 0 ORDER BY date"
    ).fetchall()

    cea_series, cea_skip, cea_dates_sorted = compute_cea_series(cea_rows)
    ccer_series, ccer_skip = compute_ccer_series(ccer_rows, cea_dates_sorted)

    series_map = {
        ("CEA", "intraday_range_pct"): cea_series["intraday_range_pct"],
        ("CEA", "open_gap_pct_abs"): cea_series["open_gap_pct_abs"],
        ("CEA", "listed_volume_z"): cea_series["listed_volume_z"],
        ("CEA", "block_volume_ratio_n20"): cea_series["block_volume_ratio_n20"],
        ("CCER", "daily_return_pct_abs_ccer"): ccer_series["daily_return_pct_abs_ccer"],
    }

    target_dates = {}
    if not backfill:
        for (market, _metric), series in series_map.items():
            target_dates.setdefault(market, set()).update(d for d, *_ in series[-5:])

    upserted = 0
    for (market, metric_name), series in series_map.items():
        for d, val, gtd, fa in series:
            if not backfill and d not in target_dates.get(market, set()):
                continue
            upserted += upsert_metric(conn, market, d, metric_name, val, gtd, fa)

    skip_counts = {**cea_skip, **ccer_skip}
    return upserted, skip_counts, series_map


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

    # CCER prev取違え是正(既存行の遡及是正・冪等・DELETE禁止)
    n_gap_fix, n_triggered_changed, n_notes_only = backfill_ccer_gap_fix(conn)
    conn.commit()
    print(f"CCER gap fix: {n_gap_fix}行更新(非日次是正) / "
          f"うちtriggered変化={n_triggered_changed}行・notesのみ={n_notes_only}行")

    # --- 多軸指標(price_anomaly_metrics) ---
    conn.execute(DDL_METRICS)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(price_anomaly_metrics)").fetchall()}
    expected_cols = {"market", "margin", "date", "metric_name", "metric_value", "threshold",
                     "triggered", "formula", "baseline_ref", "source_fetched_at",
                     "gap_trading_days"}
    missing = expected_cols - cols
    assert not missing, f"price_anomaly_metrics: schema不一致 missing={missing}"

    # baseline_ref移行(旧フルパス文字列が残っていれば現行の識別子へ揃える。冪等・毎回実行可)
    cur = conn.execute(
        "UPDATE price_anomaly_metrics SET baseline_ref=? "
        "WHERE baseline_ref IS NULL OR baseline_ref != ?",
        (BASELINE_REF, BASELINE_REF),
    )
    if cur.rowcount:
        print(f"baseline_ref migration: {cur.rowcount} rows updated to '{BASELINE_REF}'")
    conn.commit()

    n_metrics, skip_counts, series_map = detect_metrics(conn, backfill=args.backfill)
    conn.commit()
    print(f"\nmetrics: {n_metrics} rows upserted (5指標・{'backfill' if args.backfill else '直近5件/系列'})")
    print("  [走査範囲] " + " / ".join(f"{m}={len(s)}件" for (mk, m), s in series_map.items()))
    print("  [SKIP件数(数字層)] " + " / ".join(f"{k}={v}" for k, v in skip_counts.items()))

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

    # 分母併記(#136): triggered=0には「異常でないと判定した」行と「判定していない
    # (非日次で対象外)」行が混ざる。市場別に総行数・対象外(非日次)・判定対象・発火を
    # 分けて出す(CEAは対象外0行=判定分母が総行数と一致することも明示)。
    for market in ("CEA", "CCER"):
        cur = conn.execute(
            "SELECT COUNT(*) FROM price_anomaly_log WHERE market=?", (market,),
        )
        total_rows = cur.fetchone()[0]
        cur = conn.execute(
            "SELECT COUNT(*) FROM price_anomaly_log WHERE market=? AND notes LIKE '%非日次%'",
            (market,),
        )
        excluded = cur.fetchone()[0]
        judged = total_rows - excluded
        fired = per_market.get(market, 0)
        rate = fired / judged * 100 if judged else 0.0
        print(f"  [{market} 分母] {total_rows}行中 判定対象={judged}・対象外(非日次)={excluded}・"
              f"発火={fired}件({rate:.1f}%=判定分母基準)")

    cur = conn.execute(
        "SELECT market, date, metric_value, threshold FROM price_anomaly_log WHERE triggered=1 ORDER BY date DESC LIMIT 15"
    )
    print("\n=== Recent triggered anomalies ===")
    for r in cur.fetchall():
        print(f"  {r[0]} {r[1]}: {r[2]:+.2f}% (threshold={r[3]}%)")

    print("\n=== metrics ALERT summary (5指標・母集団を明記) ===")
    cur = conn.execute(
        "SELECT market, metric_name, COUNT(*) FROM price_anomaly_metrics "
        "WHERE triggered=1 GROUP BY market, metric_name ORDER BY market, metric_name"
    )
    for m, name, n in cur.fetchall():
        print(f"  {m} {name}: 全履歴trigger = {n}件")
    cur = conn.execute(
        "SELECT market, metric_name, date, metric_value, margin FROM price_anomaly_metrics "
        "WHERE triggered=1 ORDER BY date DESC LIMIT 15"
    )
    print("\n=== Recent triggered metrics ===")
    for r in cur.fetchall():
        print(f"  {r[0]} {r[1]} {r[2]}: value={r[3]:+.4f} margin={r[4]:+.4f}")
    conn.close()


if __name__ == "__main__":
    main()
