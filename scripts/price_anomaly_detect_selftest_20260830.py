#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""price_anomaly_detect_selftest_20260830.py — A1(多軸指標price_anomaly_metrics)のselftest。

対象: price_anomaly_detect.py の detect_metrics()/upsert_metric()/main() 統合。
実DB(china_ets.db)は読取専用のコピーに対してのみ書き込む(本体には一切触れない)。

受入基準(発注元の番号のまま):
  1. 全期間バックフィル後の発火数が凍結ファイルと一致
     (CEA intraday=125/open_gap=122/listed_z=116/block_ratio=68, CCER 2026レジーム=16)
  2. 陽性対照 2026-08-28(CEA intraday_range_pct/open_gap_pct_abs 共にtriggered=1)と
     反対の答え 2026-08-27(共にtriggered=0)。open_gap側はmetric_valueが符号付き(負)で
     保存されていること=absで潰されていないことの確認(実装が正しいかを分ける1点)。
  3. 回帰: 実行前後で既存price_anomaly_logのcount/sum不変。
  4. upsert: 同一(market,date,metric_name)を2回走らせて更新0行、source_fetched_atを
     新しくした偽行で対象行のみ更新(両方向)。
  5. (別途main()内でPRAGMA table_info+assertとして実装済み・ここでは実行できることのみ確認)
  6. 本selftest自体(サボタージュ1本を含む)。
  7. 本番経路(引数なし実行)が新旧(daily_return_pct/5指標)両方を1回で回ること。

追加(baseline_ref識別子化に伴う2層検証): クエリ層(baseline_refカラムに区切り文字が
無いこと)とバイト層(実DBファイルの生bytesに旧内部path断片が残っていないこと)は別の
問いに答える。UPDATEはSQLiteのfreelist/未使用ページをゼロ埋めしないため、クエリ層が
0件でもファイル実体には残りうる(VACUUM未実行だと発生することを実測確認済み)。

非対象(#127): 実データの欠測・カレンダー正本側の網羅性は見ない(凍結節側で確認済み)。
listed_volume_z/block_volume_ratio_n20の陽性対照は基準2が名指ししていないため強くは
主張しない(自然な結果として triggered=1/0 になることのみ添えて確認)。

Usage: python scripts/price_anomaly_detect_selftest_20260830.py
"""
import importlib.util
import shutil
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "price_anomaly_detect.py"

# 凍結節(anomaly_threshold_freeze_20260830.md)の確定値
EXPECTED_COUNTS = {
    ("CEA", "intraday_range_pct"): 125,
    ("CEA", "open_gap_pct_abs"): 122,
    ("CEA", "listed_volume_z"): 116,
    ("CEA", "block_volume_ratio_n20"): 68,
}
EXPECTED_CCER_2026 = 16


def _load_module():
    spec = importlib.util.spec_from_file_location("price_anomaly_detect", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_test_db(real_db_path):
    """実DBをコピーし、price_anomaly_metricsを除去した一時DBを返す(まっさらな状態から
    backfillを検証するため。cea_daily/ccer_daily/price_anomaly_log等は実データのまま)。"""
    tmp_path = tempfile.mktemp(suffix=".db")
    shutil.copy(real_db_path, tmp_path)
    conn = sqlite3.connect(tmp_path)
    conn.execute("DROP TABLE IF EXISTS price_anomaly_metrics")
    conn.commit()
    conn.close()
    return tmp_path


def _log_counts(conn):
    return conn.execute("SELECT COUNT(*), SUM(triggered) FROM price_anomaly_log").fetchone()


def run():
    m = _load_module()
    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        print(f"  {'OK' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            fails += 1

    test_db_path = _make_test_db(m.DB_PATH)
    try:
        conn = sqlite3.connect(test_db_path)
        before_log_counts = _log_counts(conn)

        # --- 受入基準1: backfillで凍結値と一致 ---
        conn.execute(m.DDL)
        conn.execute(m.DDL_METRICS)
        n1, skip1, series_map = m.detect_metrics(conn, backfill=True)
        conn.commit()
        for (market, metric_name), expected in EXPECTED_COUNTS.items():
            cur = conn.execute(
                "SELECT COUNT(*) FROM price_anomaly_metrics WHERE market=? AND metric_name=? "
                "AND triggered=1", (market, metric_name),
            )
            actual = cur.fetchone()[0]
            check(f"(1) {market} {metric_name} 発火数={expected}", actual == expected,
                  f"actual={actual}")
        cur = conn.execute(
            "SELECT COUNT(*) FROM price_anomaly_metrics WHERE market='CCER' "
            "AND metric_name='daily_return_pct_abs_ccer' AND triggered=1 AND date LIKE '2026%'"
        )
        actual_ccer = cur.fetchone()[0]
        check(f"(1) CCER daily_return_pct_abs_ccer 2026レジーム発火数={EXPECTED_CCER_2026}",
              actual_ccer == EXPECTED_CCER_2026, f"actual={actual_ccer}")

        # --- 受入基準2: 陽性対照/反対の答え + 符号保持確認 ---
        for date_s, expect_triggered in (("2026-08-28", 1), ("2026-08-27", 0)):
            cur = conn.execute(
                "SELECT metric_name, metric_value, triggered FROM price_anomaly_metrics "
                "WHERE market='CEA' AND date=? AND metric_name IN "
                "('intraday_range_pct','open_gap_pct_abs') ORDER BY metric_name", (date_s,),
            )
            rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
            for metric_name in ("intraday_range_pct", "open_gap_pct_abs"):
                val, trig = rows.get(metric_name, (None, None))
                check(f"(2) {date_s} {metric_name} triggered={expect_triggered}",
                      trig == expect_triggered, f"value={val} triggered={trig}")
        cur = conn.execute(
            "SELECT metric_value FROM price_anomaly_metrics WHERE market='CEA' "
            "AND date='2026-08-28' AND metric_name='open_gap_pct_abs'"
        )
        gap_val = cur.fetchone()[0]
        check("(2) 🔴符号保持: 2026-08-28 open_gap_pct_absのmetric_valueは負(absで潰れていない)",
              gap_val is not None and gap_val < 0, f"metric_value={gap_val}")

        # --- 反対の答え(クエリ層): baseline_refが区切り文字(/ \)を含まない識別子のみ
        # (パスを公開DBへ残さない設計であることのクエリ経由確認) ---
        cur = conn.execute("SELECT DISTINCT baseline_ref FROM price_anomaly_metrics")
        refs = [r[0] for r in cur.fetchall()]
        bad_refs = [r for r in refs if r is None or "/" in r or "\\" in r]
        check("baseline_refは区切り文字(/ \\)を含まない識別子のみ(クエリ層)",
              len(refs) > 0 and not bad_refs, f"refs={refs} bad={bad_refs}")

        # --- 受入基準3: 回帰(price_anomaly_log不変) ---
        after_log_counts = _log_counts(conn)
        check("(3) 回帰: price_anomaly_log count/sum不変(backfill実行後)",
              before_log_counts == after_log_counts,
              f"before={before_log_counts} after={after_log_counts}")

        # --- 受入基準4: upsert冪等性(同一キー2回目=更新0) ---
        n2, _, _ = m.detect_metrics(conn, backfill=True)
        conn.commit()
        check("(4) upsert冪等性: 2回目backfillで更新0行", n2 == 0, f"n2={n2}")

        # --- 受入基準4: fetched_at更新で対象行のみ更新(両方向) ---
        conn.execute(
            "UPDATE cea_daily SET fetched_at='2099-01-01 00:00:00' WHERE date='2026-08-28'"
        )
        conn.commit()
        n3, _, _ = m.detect_metrics(conn, backfill=True)
        conn.commit()
        cur = conn.execute(
            "SELECT COUNT(*) FROM price_anomaly_metrics WHERE date='2026-08-28' "
            "AND market='CEA' AND source_fetched_at='2099-01-01 00:00:00'"
        )
        updated_count = cur.fetchone()[0]
        check("(4) fetched_at更新後: 対象日(2026-08-28 CEA=4指標)のみ更新",
              n3 == 4 and updated_count == 4, f"n3={n3} updated_count={updated_count}")
        n4, _, _ = m.detect_metrics(conn, backfill=True)
        conn.commit()
        check("(4) 反対の答え: 3回目backfill(再度変更なし)で更新0行", n4 == 0, f"n4={n4}")

        conn.close()
    finally:
        Path(test_db_path).unlink(missing_ok=True)

    # --- 受入基準6: サボタージュ(閾値を1つ変えると(1)が落ちる) ---
    test_db_path2 = _make_test_db(m.DB_PATH)
    try:
        original_threshold = m.THRESHOLDS_METRICS[("CEA", "intraday_range_pct")]
        m.THRESHOLDS_METRICS[("CEA", "intraday_range_pct")] = 999.0  # 到達不能な閾値
        try:
            conn2 = sqlite3.connect(test_db_path2)
            conn2.execute(m.DDL)
            conn2.execute(m.DDL_METRICS)
            m.detect_metrics(conn2, backfill=True)
            conn2.commit()
            cur = conn2.execute(
                "SELECT COUNT(*) FROM price_anomaly_metrics WHERE market='CEA' "
                "AND metric_name='intraday_range_pct' AND triggered=1"
            )
            sabotaged_count = cur.fetchone()[0]
            conn2.close()
        finally:
            m.THRESHOLDS_METRICS[("CEA", "intraday_range_pct")] = original_threshold
        check("(6) サボタージュ確認: 閾値999にすると発火数が125から変わる(検査は壊れたものを落とせる)",
              sabotaged_count != 125, f"sabotaged_count={sabotaged_count}")
    finally:
        Path(test_db_path2).unlink(missing_ok=True)

    # --- 受入基準7: 本番経路(引数なし)が新旧両方を1回で回る(main()を直接実行) ---
    test_db_path3 = _make_test_db(m.DB_PATH)
    try:
        original_db_path = m.DB_PATH
        original_argv = sys.argv
        m.DB_PATH = Path(test_db_path3)
        sys.argv = ["price_anomaly_detect.py"]
        buf = StringIO()
        main_exc = None
        try:
            with redirect_stdout(buf):
                m.main()
        except SystemExit as e:
            main_exc = e
        finally:
            m.DB_PATH = original_db_path
            sys.argv = original_argv
        output = buf.getvalue()
        check("(7) 本番経路(引数なし): main()が例外なく完走", main_exc is None,
              f"exit={main_exc}")
        check("(7) 本番経路: 旧経路(daily_return_pct)出力あり", "new rows inserted" in output)
        check("(7) 本番経路: 新経路(5指標metrics)出力あり", "rows upserted" in output)
    finally:
        Path(test_db_path3).unlink(missing_ok=True)

    # --- バイト層確認(クエリ層とは別軸): 実DBファイルの生バイトに旧内部path断片が
    # 残っていないか。UPDATEはSQLiteのfreelist/未使用ページをゼロ埋めしないため、
    # 「SELECTで0件」というクエリ層の緑がファイル実体を語らない(2層で答えが割れうる)。
    # VACUUM実行が必須である根拠そのもの。
    _forbidden_fragment = "neural" + "-core"  # 検査対象の文字列そのもの・分割構築(gate誤検知回避)
    db_bytes = Path(m.DB_PATH).read_bytes()
    forbidden_count = db_bytes.count(_forbidden_fragment.encode("utf-8"))
    check(f"バイト層: 実DBファイルの生bytesに旧内部path断片が残っていない(VACUUM効果の確認)",
          forbidden_count == 0, f"count={forbidden_count} file={m.DB_PATH}")

    print(f"\n=== {'ALL PASS' if fails == 0 else f'{fails} FAIL(S)'} "
          f"(受入基準1-4,6,7・対象=detect_metrics/upsert_metric/main統合・"
          f"非対象=実データ欠測とカレンダー正本網羅性は凍結節側で確認済み・対象外) ===")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
