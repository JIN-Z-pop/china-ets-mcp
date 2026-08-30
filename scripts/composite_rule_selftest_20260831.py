"""複合ルール(axes_fired_count >= 3)の自己検査 — 2026-08-31

この検査が答える問い:
  「4軸の発火数を数える計算が、実際にデータへ届いており、
    かつ条件次第で“発火する/しない”の**両方向**に転ぶか」

この検査が答えない問い(非対象範囲):
  ・閾値そのものの妥当性(凍結値=anomaly_threshold_freeze_20260830)
  ・4軸それぞれの計算式の正しさ(=既存 price_anomaly_detect_selftest_20260830.py の担当)
  ・CCERへの適用可否(構造上1軸のみ=非適用。NON_COVERAGEに明記済)

陽性対照(反対の答えを出すケースを1本必置):
  全ケースが同じ判定を期待する検査は、壊れていても緑になる。
  そこで閾値を下げ切る/上げ切る2条件を必ず含め、
  「発火が増える」「発火が0になる」ことを確認する。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import price_anomaly_detect as pad  # noqa: E402


def fired_days(series_map, thresholds):
    """与えた閾値でCEA 4軸の同日発火数を数え、3軸以上の日を返す。
    price_anomaly_detect.compute_composite_series と同じ規則(4軸未揃いは判定対象外)。"""
    per_date = {}
    for name in pad.CEA_AXIS_METRICS:
        thr = thresholds[name]
        for d, val, _gtd, _fa in series_map[("CEA", name)]:
            v = pad.compute_v(name, val)
            slot = per_date.setdefault(d, {"fired": 0, "n": 0})
            slot["n"] += 1
            slot["fired"] += 1 if v > thr else 0
    n_axes = len(pad.CEA_AXIS_METRICS)
    judged = [d for d, s in per_date.items() if s["n"] == n_axes]
    fired = [d for d in judged if per_date[d]["fired"] >= 3]
    return sorted(fired), len(judged)


def main():
    conn = sqlite3.connect(pad.DB_PATH)
    _n, _skips, series_map = pad.detect_metrics(conn, backfill=True)
    conn.rollback()  # 検査は書き込まない

    real = {m: pad.THRESHOLDS_METRICS[("CEA", m)] for m in pad.CEA_AXIS_METRICS}
    loose = {m: -1e9 for m in pad.CEA_AXIS_METRICS}   # 全軸が必ず発火する
    strict = {m: 1e9 for m in pad.CEA_AXIS_METRICS}   # 全軸が絶対発火しない

    results = []

    base, judged = fired_days(series_map, real)
    results.append(("本番閾値", len(base), judged, None))

    lo, judged_lo = fired_days(series_map, loose)
    # 期待: 閾値を下げ切れば判定対象の全日が4軸発火 -> 3軸以上=全日
    results.append(("陽性対照(閾値を下げ切る)", len(lo), judged_lo, judged_lo))

    hi, judged_hi = fired_days(series_map, strict)
    # 期待: 閾値を上げ切れば1軸も発火しない -> 3軸以上=0日
    results.append(("陰性対照(閾値を上げ切る)", len(hi), judged_hi, 0))

    print("=== 複合ルール 自己検査 ===")
    ok = True
    for label, n_fired, judged_n, expected in results:
        verdict = ""
        if expected is not None:
            passed = (n_fired == expected)
            ok &= passed
            verdict = f"  期待={expected} -> {'PASS' if passed else 'FAIL'}"
        print(f"  {label:26} 発火={n_fired:4}日 / 判定対象={judged_n}日{verdict}")

    # DBに保存された結果と、この場で計算した結果が一致するか(=届いているか)
    saved = [r[0] for r in conn.execute(
        "SELECT date FROM price_anomaly_metrics WHERE market='CEA' "
        "AND metric_name='axes_fired_count' AND triggered=1 ORDER BY date"
    ).fetchall()]
    match = (saved == base)
    ok &= match
    print(f"\n  DB保存分と再計算の一致: {'PASS' if match else 'FAIL'} "
          f"(DB={len(saved)}日 / 再計算={len(base)}日)")
    if not match:
        print(f"    DBのみ: {sorted(set(saved) - set(base))}")
        print(f"    再計算のみ: {sorted(set(base) - set(saved))}")

    # 両対照が同じ答えを返したら、検査自体が壊れている
    if len(lo) == len(hi):
        ok = False
        print("\n  [FAIL] 陽性対照と陰性対照が同じ結果 = 検査が閾値に反応していない")

    conn.close()
    print(f"\n=== {'ALL PASS' if ok else 'FAIL'} ===")
    print("非対象範囲: 閾値の妥当性 / 各軸の計算式の正しさ / CCERへの適用可否")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
