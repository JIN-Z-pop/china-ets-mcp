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

追加(CCER prev取違え是正・2026-08-30): 旧detect()はCCERの疎らな行同士を隣接比較して
いたため、gap_trading_days>1(非日次)の行を誤って日次騰落率として判定していた。
  (a) 前向き: detect()がgap>1の行をtriggered=0+notes"非日次"で挿入すること
      (実データの既知ケース2025-03-07・gap=268で検証・CEAは無変更であることも確認)。
  (b) 反対の答え: gap==1の通常行は従来どおり判定されること(notesに非日次が付かない)。
  (c) 後ろ向き: backfill_ccer_gap_fix()が「誤って挿入済み」の29行を是正し
      (triggered変化3行・notesのみ26行)、2回目実行は冪等(0行)であること。
  (d) サボタージュ: gap判定ロジックを無効化すると(a)が落ちる(検査は壊れたものを落とせる)。
DELETE禁止・履歴は残す(#136: metric_valueは記録のまま・判定だけ外す)。

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


def _make_test_db_no_log(real_db_path):
    """実DBをコピーし、price_anomaly_metricsに加えprice_anomaly_logも除去した一時DBを
    返す(detect()の新規挿入ロジックをまっさらな状態から検証するため。実DBのlogは既に
    CCER prev是正適用後の状態なので、素通りで正しく見えてしまう=#136を避ける)。"""
    tmp_path = tempfile.mktemp(suffix=".db")
    shutil.copy(real_db_path, tmp_path)
    conn = sqlite3.connect(tmp_path)
    conn.execute("DROP TABLE IF EXISTS price_anomaly_metrics")
    conn.execute("DROP TABLE IF EXISTS price_anomaly_log")
    conn.commit()
    conn.close()
    return tmp_path


def run():
    m = _load_module()
    fails = 0
    total = 0

    def check(name, ok, detail=""):
        nonlocal fails, total
        total += 1
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

    # --- CCER prev取違え是正: (a)前向きgap>1判定 (b)前向きgap==1は従来判定 ---
    # 実データの既知ケース(2025-03-07・gap=268・独立検証3体一致)をそのまま使う
    # (合成データを作らず実測ケースで検証=n=1逆算ではなく既知の答え合わせ)。
    test_db_path4 = _make_test_db_no_log(m.DB_PATH)
    try:
        conn4 = sqlite3.connect(test_db_path4)
        conn4.execute(m.DDL)
        m.detect(conn4, "CEA", backfill=True)
        m.detect(conn4, "CCER", backfill=True)
        conn4.commit()

        row_a = conn4.execute(
            "SELECT triggered, notes FROM price_anomaly_log WHERE market='CCER' AND date='2025-03-07'"
        ).fetchone()
        check("(a) 前向き判定: gap>1(2025-03-07・gap=268)はtriggered=0",
              row_a is not None and row_a[0] == 0, f"row={row_a}")
        check("(a) 前向き判定: notesに非日次の記載がある",
              row_a is not None and "非日次" in (row_a[1] or ""), f"notes={row_a[1] if row_a else None}")

        row_b = conn4.execute(
            "SELECT triggered, notes FROM price_anomaly_log WHERE market='CCER' AND date='2026-08-11'"
        ).fetchone()
        check("(b) 反対の答え: gap==1の通常行(2026-08-11)は従来どおりtriggered=1",
              row_b is not None and row_b[0] == 1, f"row={row_b}")
        check("(b) gap==1の通常行: notesが従来形式(非日次でない)",
              row_b is not None and "非日次" not in (row_b[1] or ""),
              f"notes={row_b[1] if row_b else None}")

        cea_count = conn4.execute(
            "SELECT COUNT(*) FROM price_anomaly_log WHERE market='CEA' AND notes LIKE '%非日次%'"
        ).fetchone()[0]
        check("(a) CEAは無変更: 非日次notesを持つCEA行=0", cea_count == 0, f"cea_count={cea_count}")

        conn4.close()
    finally:
        Path(test_db_path4).unlink(missing_ok=True)

    # --- (c) 後ろ向きbackfill_ccer_gap_fixの冪等性: 旧ロジック(gap判定なし)相当で
    # 「間違って挿入された」状態を再現してから是正する(本番運用のシナリオそのもの) ---
    test_db_path5 = _make_test_db_no_log(m.DB_PATH)
    try:
        conn5 = sqlite3.connect(test_db_path5)
        conn5.execute(m.DDL)
        original_gap_fn = m.gap_trading_days
        m.gap_trading_days = lambda *a, **kw: 1  # 旧ロジック相当(gap判定なし)で挿入
        try:
            m.detect(conn5, "CEA", backfill=True)
            m.detect(conn5, "CCER", backfill=True)
            conn5.commit()
        finally:
            m.gap_trading_days = original_gap_fn  # 是正関数自体は本来のgap_trading_daysを使う

        row_before = conn5.execute(
            "SELECT triggered FROM price_anomaly_log WHERE market='CCER' AND date='2025-03-07'"
        ).fetchone()
        check("(c) 是正前提: 旧ロジック挿入では2025-03-07がtriggered=1のまま(誤った状態を再現)",
              row_before is not None and row_before[0] == 1, f"row_before={row_before}")

        n_fix1, n_trig1, n_notes1 = m.backfill_ccer_gap_fix(conn5)
        conn5.commit()
        check("(c) 後ろ向きbackfill: 29行が是正される", n_fix1 == 29, f"n_fix1={n_fix1}")
        check("(c) 後ろ向きbackfill: うちtriggered変化=3行", n_trig1 == 3, f"n_trig1={n_trig1}")
        check("(c) 後ろ向きbackfill: うちnotesのみ=26行", n_notes1 == 26, f"n_notes1={n_notes1}")

        row_after = conn5.execute(
            "SELECT triggered, notes FROM price_anomaly_log WHERE market='CCER' AND date='2025-03-07'"
        ).fetchone()
        check("(c) 後ろ向きbackfill後: 2025-03-07がtriggered=0に是正",
              row_after is not None and row_after[0] == 0, f"row_after={row_after}")

        n_fix2, n_trig2, n_notes2 = m.backfill_ccer_gap_fix(conn5)
        conn5.commit()
        check("(c) 後ろ向きbackfill冪等性: 2回目は0行", n_fix2 == 0, f"n_fix2={n_fix2}")

        conn5.close()
    finally:
        Path(test_db_path5).unlink(missing_ok=True)

    # --- (d) サボタージュ: 前向き判定のgap判定ロジックを無効化すると(a)が落ちる ---
    test_db_path6 = _make_test_db_no_log(m.DB_PATH)
    try:
        conn6 = sqlite3.connect(test_db_path6)
        conn6.execute(m.DDL)
        original_gap_fn2 = m.gap_trading_days
        m.gap_trading_days = lambda *a, **kw: 1  # 判定を無効化(常にgap=1を返す)
        try:
            m.detect(conn6, "CCER", backfill=True)
            conn6.commit()
        finally:
            m.gap_trading_days = original_gap_fn2
        row_sab = conn6.execute(
            "SELECT triggered FROM price_anomaly_log WHERE market='CCER' AND date='2025-03-07'"
        ).fetchone()
        sabotaged_triggered = row_sab[0] if row_sab else None
        conn6.close()
        check("(d) サボタージュ確認: gap判定を無効化すると2025-03-07がtriggered=1に戻る"
              "(検査は壊れたものを落とせる)",
              sabotaged_triggered == 1, f"sabotaged_triggered={sabotaged_triggered}")
    finally:
        Path(test_db_path6).unlink(missing_ok=True)

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
          f"({total}件・実行アサーション数=checkの呼び出し回数(forループ内反復含む)・"
          f"対象=受入基準1-4,6,7(detect_metrics/upsert_metric/main統合)+"
          f"CCER prev是正(a)(b)(c)(d)(detect/backfill_ccer_gap_fix)・"
          f"非対象=実データ欠測とカレンダー正本網羅性は凍結節側で確認済み・対象外) ===")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
