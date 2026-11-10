#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""price_anomaly_seq_selftest_20261110.py — 行が増えない登録で連番を進めないことの検査。

対象: price_anomaly_detect.py の detect() と upsert_metric() の登録(price_anomaly_log /
price_anomaly_metrics)。どちらもAUTOINCREMENTの表で、INSERT文を実行するだけで(キー衝突で
行が増えなくても)sqlite_sequenceが進む。修正後は「同じキーの行が在れば挿入しない」形になっていること。

この検査が答える問い:
  「修正後のコードは、(a)行が増えない登録で連番を進めず、(b)行が増える登録では増えた行数
    だけ進め、(c)表の中身は修正前のコードと1行も違わないか」

判定は定数でなく不変量:
  修正前コード: 連番の増分 = INSERT文の実行回数(行が増えたかどうかに依らない)
  修正後コード: INSERT文の実行回数 > 0 かつ 連番の増分 = 増えた行数
  (NOT EXISTSが偽でもINSERT文自体は実行される=0行。文の実行回数はこの検査がtrace callbackで数える)

「修正前コード」は git の commit から取り出す(作業ツリーのHEADには依らない)。本番DBは
一時dirへコピーしたものに対してだけ実行し、本番ファイルは読むだけ(前後でsha256が不変)。

走査範囲外: 公開ページ・他の表・下流の表示・source_fetched_atがNULLの入力は見ていない。

Usage: python scripts/price_anomaly_seq_selftest_20261110.py [--db PATH]
終了コード: 0=全項目PASS・較正すべて想定どおり / 1=不合格 / 2=検査自体の不良(実行せずに止まった)
"""
import argparse
import collections
import contextlib
import difflib
import hashlib
import importlib.util
import io
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
MODULE_REL = "scripts/price_anomaly_detect.py"
WORKTREE_MODULE = REPO_ROOT / MODULE_REL
DEFAULT_DB = REPO_ROOT / "data" / "china_ets.db"
BEFORE_COMMIT = "0047a38"  # 修正前のコードを含む commit
TABLES = ("price_anomaly_log", "price_anomaly_metrics")
SHORT = {"price_anomaly_log": "log", "price_anomaly_metrics": "metrics"}
SCENARIO_TAGS = ("none", "missing", "stale", "equal fetch", "newer")  # 修正前後比較の仕込み5種の短い名前
EXISTING_SELFTESTS = (
    "price_anomaly_detect_selftest_20260830.py",
    "composite_rule_selftest_20260831.py",
)
INSERT_RE = re.compile(
    r"^\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(price_anomaly_log|price_anomaly_metrics)\b", re.I
)

Snap = collections.namedtuple("Snap", "seq rows digest")
Delta = collections.namedtuple("Delta", "dseq drows attempts before after")
Run = collections.namedtuple("Run", "label version delta stdout")
Item = collections.namedtuple("Item", "name ok lines calib")  # calib=(fell:bool, detail) or None


class InstrumentError(Exception):
    """検査自体の不良(検査対象の合否ではない)。実行せずに止まる=終了コード2。"""


def progress(msg):
    print(f"  ... {msg}", file=sys.stderr, flush=True)


def sha12(data):
    return hashlib.sha256(data).hexdigest()[:12]


def file_fingerprint(path):
    p = Path(path)
    st = p.stat()
    return (hashlib.sha256(p.read_bytes()).hexdigest(), st.st_size, st.st_mtime_ns)


# ---------------------------------------------------------------- 一時dirと隔離

class Ctx:
    """一時dirの根と本番DBの場所。一時dirの外へは一切書かない・開かない。"""

    def __init__(self, root, prod):
        self.root = Path(root).resolve()
        self.prod = Path(prod).resolve()

    def inside(self, path):
        rp = Path(path).resolve()
        return rp != self.prod and rp.is_relative_to(self.root)

    def fresh_copy(self, name):
        dst = self.root / name
        shutil.copyfile(self.prod, dst)  # 本番は読むだけ
        return dst


def open_ro(db):
    return sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)


def open_rw(db, ctx):
    if not ctx.inside(db):
        raise InstrumentError(f"一時dir外のDBへは書かない: {db}")
    return sqlite3.connect(str(db))


def table_state(db):
    """2表それぞれの(連番, 行数, 中身ハッシュ)。中身=idとcreated_atを除く全列を
    (market, date, metric_name)順に並べた内容。"""
    con = open_ro(db)
    try:
        seqs = dict(con.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
        out = {}
        for t in TABLES:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")
                    if r[1] not in ("id", "created_at")]
            rows = con.execute(
                f"SELECT {', '.join(cols)} FROM {t} ORDER BY market, date, metric_name"
            ).fetchall()
            out[t] = Snap(int(seqs.get(t, 0)), len(rows), sha12(repr(rows).encode("utf-8")))
        return out
    finally:
        con.close()


# ---------------------------------------------------------------- コードの読み込みと差し替え

def fetch_before_source():
    cp = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{BEFORE_COMMIT}:{MODULE_REL}"],
        capture_output=True,
    )
    if cp.returncode != 0 or not cp.stdout:
        raise InstrumentError(f"修正前コードを取り出せない: git show {BEFORE_COMMIT}:{MODULE_REL}")
    return cp.stdout


def load_module(source_bytes, name, workdir):
    path = Path(workdir) / f"{name}.py"
    path.write_bytes(source_bytes)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 読み込みだけではDBを開かない
    return mod


def bind_db(mod, db):
    mod.DB_PATH = Path(db)  # main()は呼び出し時にモジュールのDB_PATHを読む


def assert_isolated(mod, db, ctx):
    p = Path(mod.DB_PATH).resolve()
    if p != Path(db).resolve():
        raise AssertionError(f"DB_PATH が一時コピーでない: {p}")
    if not ctx.inside(p):
        raise AssertionError(f"DB_PATH が一時dirの外(または本番): {p}")


def mutate(text, old, new, expect):
    n = text.count(old)
    if n != expect:
        raise InstrumentError(f"較正用の差し替え箇所が想定数でない: {old!r} が {n} 回(想定 {expect})")
    return text.replace(old, new)


class Tracer:
    """2表へのINSERT文の実行回数を数える(行が増えたかどうかは問わない)。"""

    def __init__(self):
        self.counts = {t: 0 for t in TABLES}

    def __call__(self, statement):
        m = INSERT_RE.match(statement)
        if m:
            self.counts[m.group(1).lower()] += 1


def make_shim(ctx, tracer):
    shim = types.SimpleNamespace(
        **{k: getattr(sqlite3, k) for k in dir(sqlite3) if not k.startswith("__")}
    )

    def guarded_connect(database, *args, **kwargs):
        if not ctx.inside(database):
            raise RuntimeError(f"一時dir外のDBは開かない: {database}")
        conn = sqlite3.connect(database, *args, **kwargs)
        conn.set_trace_callback(tracer)
        return conn

    shim.connect = guarded_connect
    return shim


def run_main(mod, db, args, ctx):
    assert_isolated(mod, db, ctx)  # 外れていたら実行しない
    tracer = Tracer()
    saved_sqlite, saved_argv = mod.sqlite3, sys.argv
    mod.sqlite3 = make_shim(ctx, tracer)
    sys.argv = [Path(mod.__file__).name] + list(args)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mod.main()
    finally:
        mod.sqlite3, sys.argv = saved_sqlite, saved_argv
    return buf.getvalue(), dict(tracer.counts)


def measure(label, version, mod, db, ctx, args=(), ledger=None):
    bind_db(mod, db)
    before = table_state(db)
    out, att = run_main(mod, db, args, ctx)
    after = table_state(db)
    delta = {
        t: Delta(after[t].seq - before[t].seq, after[t].rows - before[t].rows,
                 att[t], before[t], after[t])
        for t in TABLES
    }
    if ledger is not None:
        for t in TABLES:
            ledger.append((label, version, t, delta[t].dseq, delta[t].drows, delta[t].attempts))
    return Run(label, version, delta, out)


def fmt_run(r):
    return " ・ ".join(
        f"{SHORT[t]} Δseq={r.delta[t].dseq} Δrows={r.delta[t].drows} INSERT文={r.delta[t].attempts}"
        for t in TABLES
    )


def unchanged(d):
    return d.before.digest == d.after.digest


def new_ok(d):
    """修正後の正しい姿: INSERT文は実行され(>0)、連番の増分=増えた行数。"""
    return d.attempts > 0 and d.dseq == d.drows


def old_shape(d):
    """修正前の姿: 連番の増分=INSERT文の実行回数(行の増減に依らない)。"""
    return d.attempts > 0 and d.dseq == d.attempts


def require_counted(run, what):
    for t in TABLES:
        if run.delta[t].attempts == 0:
            raise InstrumentError(f"{what}: INSERT文を1回も数えていない({SHORT[t]})=計数が対象に届いていない")


# ---------------------------------------------------------------- 仕込み(一時コピーへ)

def seed_none(db, ctx):
    return "仕込みなし"


def seed_missing_rows(db, ctx):
    con = open_rw(db, ctx)
    try:
        d_log = con.execute("SELECT max(date) FROM price_anomaly_log WHERE market='CCER'").fetchone()[0]
        n_log = con.execute("DELETE FROM price_anomaly_log WHERE market='CCER' AND date=?", (d_log,)).rowcount
        d_met = con.execute("SELECT max(date) FROM price_anomaly_metrics WHERE market='CCER'").fetchone()[0]
        n_met = con.execute("DELETE FROM price_anomaly_metrics WHERE market='CCER' AND date=?", (d_met,)).rowcount
        con.commit()
    finally:
        con.close()
    if (n_log, n_met) != (1, 1):
        raise InstrumentError(f"行欠落の仕込みが1行ずつにならない: log={n_log} metrics={n_met}")
    return f"CCER最新日の行を削除: log {d_log}={n_log}行 / metrics {d_met}={n_met}行"


def _seed_metrics_latest_cea(db, ctx, set_sql, label):
    con = open_rw(db, ctx)
    try:
        d = con.execute("SELECT max(date) FROM price_anomaly_metrics WHERE market='CEA'").fetchone()[0]
        n = con.execute(
            f"UPDATE price_anomaly_metrics SET {set_sql} WHERE market='CEA' AND date=?", (d,)
        ).rowcount
        n_equal = con.execute(
            "SELECT count(*) FROM price_anomaly_metrics m JOIN cea_daily c ON c.date=m.date "
            "WHERE m.market='CEA' AND m.date=? AND m.source_fetched_at=c.fetched_at", (d,)
        ).fetchone()[0]
        con.commit()
    finally:
        con.close()
    if n == 0:
        raise InstrumentError(f"仕込み対象が0行: {label}")
    return d, n, n_equal


def seed_stale_store(db, ctx):
    d, n, _ = _seed_metrics_latest_cea(
        db, ctx, "source_fetched_at='2000-01-01 00:00:00', metric_value=metric_value+1000",
        "古い格納")
    return f"CEA最新日 {d} のmetrics {n}行を、古いsource_fetched_at＋別値にした"


def seed_equal_fetch(db, ctx):
    d, n, n_equal = _seed_metrics_latest_cea(
        db, ctx,
        "source_fetched_at=(SELECT c.fetched_at FROM cea_daily c WHERE c.date=price_anomaly_metrics.date), "
        "metric_value=metric_value+1000",
        "等しいfetched_at＋別値")
    if n_equal != n:
        raise InstrumentError(f"等しいfetched_atの仕込みが成立していない: {n_equal}/{n}")
    return f"CEA最新日 {d} のmetrics {n}行を、等しいsource_fetched_at＋別値にした(等しい行={n_equal})"


def seed_newer_store(db, ctx):
    d, n, _ = _seed_metrics_latest_cea(
        db, ctx, "source_fetched_at='2099-01-01 00:00:00', metric_value=metric_value+1000",
        "格納の方が新しい")
    return f"CEA最新日 {d} のmetrics {n}行を、新しいsource_fetched_at＋別値にした"


# ---------------------------------------------------------------- 項目

def item_isolation_pre(ctx, mods, unbound_mod):
    """本番を書かない(実行前の半分): 読み込んだ2版のDB_PATHが一時コピーであること。"""
    db = ctx.fresh_copy("isolation.db")
    for ver, mod in mods.items():
        bind_db(mod, db)
        try:
            assert_isolated(mod, db, ctx)
        except AssertionError as e:
            raise InstrumentError(f"{ver}: 隔離の確認に失敗(実行せずに止める): {e}")
    # 較正: DB_PATHを差し替えない版ではassertが落ちる・一時dir外への接続は拒否される
    fell_assert = False
    try:
        assert_isolated(unbound_mod, db, ctx)
    except AssertionError:
        fell_assert = True
    fell_guard = False
    try:
        make_shim(ctx, Tracer()).connect(str(ctx.prod))
    except RuntimeError:
        fell_guard = True
    fell = fell_assert and fell_guard
    return Item(
        "production database untouched (isolation before runs)", True,
        ["読み込んだ修正前・修正後の2版とも DB_PATH＝一時コピー(本番ではない)をassertで確認"],
        (fell, f"差し替えない版でassertが落ちる={fell_assert}・一時dir外への接続を拒否={fell_guard}"),
    )


def item_noop(ctx, mods, baseline, ledger):
    lines, ok = [], True
    db = ctx.fresh_copy("noop_after.db")
    bytes_before = hashlib.sha256(db.read_bytes()).hexdigest()
    bytes_after = None
    for i in (1, 2):
        r = measure(f"no-op #{i}", "after", mods["after"], db, ctx, ledger=ledger)
        if i == 1:
            bytes_after = hashlib.sha256(db.read_bytes()).hexdigest()
        good = all(new_ok(r.delta[t]) and r.delta[t].drows == 0 and unchanged(r.delta[t])
                   and r.delta[t].after.digest == baseline[t].digest for t in TABLES)
        ok &= good
        lines.append(f"{'OK' if good else 'NG'} 修正後 {i}回目(仕込みなし): {fmt_run(r)} ・中身ハッシュ=実行前と一致")
    lines.append(f"見た行数: log {baseline['price_anomaly_log'].rows}行・metrics "
                 f"{baseline['price_anomaly_metrics'].rows}行(中身ハッシュは全行)")
    lines.append("参考(判定に使わない): 1回目の実行前後でDBファイルのバイト列は "
                 + ("同一" if bytes_before == bytes_after else "変化あり"))
    # 較正: 修正前コードでは同じ実行で連番が進む(INSERT文の実行回数ぶん)
    dbo = ctx.fresh_copy("noop_before.db")
    fell, det = True, []
    for i in (1, 2):
        r = measure(f"no-op #{i}", "before", mods["before"], dbo, ctx, ledger=ledger)
        require_counted(r, "no-op(修正前)")
        shape = all(old_shape(r.delta[t]) and r.delta[t].dseq != r.delta[t].drows for t in TABLES)
        fell &= shape
        det.append(f"{i}回目 {fmt_run(r)}")
    return Item("no-op run keeps sequence", ok, lines,
                (fell, "修正前コード(連番=INSERT文の実行回数・行は増えない): " + " / ".join(det)))


def item_missing_rows(ctx, mods, baseline, ledger, skip_insert_mod):
    db = ctx.fresh_copy("missing_after.db")
    note = seed_missing_rows(db, ctx)
    r = measure("missing rows", "after", mods["after"], db, ctx, ledger=ledger)
    ok = all(new_ok(r.delta[t]) and r.delta[t].drows == 1 and r.delta[t].dseq == 1
             and r.delta[t].after.digest == baseline[t].digest for t in TABLES)
    lines = [note, f"{'OK' if ok else 'NG'} 修正後 1回: {fmt_run(r)} ・中身ハッシュ=元と一致(行が戻った)"]
    # 較正: INSERTを実行しない版では行が戻らず、ハッシュが元と一致しない
    dbm = ctx.fresh_copy("missing_mutant.db")
    seed_missing_rows(dbm, ctx)
    rm = measure("missing rows", "mutant", skip_insert_mod, dbm, ctx)
    fell = all(rm.delta[t].after.digest != baseline[t].digest and rm.delta[t].drows == 0 for t in TABLES)
    return Item("missing rows are restored", ok, lines,
                (fell, "INSERTを実行しない版: 両表とも行が戻らず中身ハッシュが元と不一致="
                       + str(all(rm.delta[t].after.digest != baseline[t].digest for t in TABLES))))


def item_stale_store(ctx, mods, baseline, ledger, older_only_mod):
    db = ctx.fresh_copy("stale_after.db")
    note = seed_stale_store(db, ctx)
    r = measure("stale stored", "after", mods["after"], db, ctx, ledger=ledger)
    ok = all(new_ok(r.delta[t]) and r.delta[t].dseq == 0 and r.delta[t].drows == 0
             and r.delta[t].after.digest == baseline[t].digest for t in TABLES)
    lines = [note, f"{'OK' if ok else 'NG'} 修正後 1回: {fmt_run(r)} ・中身ハッシュ=元と一致(その日の全行が元の値に戻った)"]
    dbm = ctx.fresh_copy("stale_mutant.db")
    seed_stale_store(dbm, ctx)
    rm = measure("stale stored", "mutant", older_only_mod, dbm, ctx)
    differs = rm.delta["price_anomaly_metrics"].after.digest != baseline["price_anomaly_metrics"].digest
    return Item("stale stored rows are refreshed", ok, lines,
                (differs, f"比較を『<』にした版: 元の値に戻らず中身ハッシュが元と不一致={differs}"))


def item_identical_contents(ctx, mods, baseline, ledger, equal_updates_mod):
    scenarios = [
        ("no changes", seed_none),
        ("missing rows", seed_missing_rows),
        ("stale stored", seed_stale_store),
        ("equal fetch time + different value", seed_equal_fetch),
        ("stored is newer + different value", seed_newer_store),
    ]
    lines, ok, runs_equal_case = [], True, None
    for idx, (name, seed) in enumerate(scenarios):
        runs = {}
        for ver in ("before", "after"):
            db = ctx.fresh_copy(f"scn{idx}_{ver}.db")
            note = seed(db, ctx)
            runs[ver] = measure(f"cmp {SCENARIO_TAGS[idx]}", ver, mods[ver], db, ctx, ledger=ledger)
        same = all(runs["before"].delta[t].after.digest == runs["after"].delta[t].after.digest
                   for t in TABLES)
        n_lines = {v: [ln.strip() for ln in runs[v].stdout.splitlines()
                       if "inserted" in ln or "upserted" in ln] for v in runs}
        same_n = n_lines["before"] == n_lines["after"]
        same_out = runs["before"].stdout == runs["after"].stdout
        extra = ""
        if idx in (3, 4):  # 別値のまま残るのが正
            kept = runs["after"].delta["price_anomaly_metrics"].after.digest != baseline["price_anomaly_metrics"].digest
            same &= kept
            extra = f" ・別値のまま残った={kept}"
        good = same and same_n and same_out
        ok &= good
        if idx == 3:
            runs_equal_case = runs
        lines.append(f"{'OK' if good else 'NG'} {name}: 2表の中身一致={same} ・出力行のN一致={same_n} "
                     f"({'; '.join(n_lines['after'])}) ・標準出力全体一致={same_out}{extra}")
        lines.append(f"    仕込み: {note}")
    # 較正: 比較を『>=』にした版は、等しいfetched_at＋別値で修正前と中身が食い違う
    dbm = ctx.fresh_copy("equal_mutant.db")
    seed_equal_fetch(dbm, ctx)
    rm = measure("cmp equal fetch", "mutant", equal_updates_mod, dbm, ctx)
    differs = (rm.delta["price_anomaly_metrics"].after.digest
               != runs_equal_case["before"].delta["price_anomaly_metrics"].after.digest)
    return Item("old and new code leave identical contents", ok, lines,
                (differs, f"比較を『>=』にした版: 等しいfetched_at＋別値で修正前と中身が不一致={differs}"))


def item_backfill(ctx, mods, baseline, ledger):
    db = ctx.fresh_copy("backfill_after.db")
    r = measure("backfill", "after", mods["after"], db, ctx, args=["--backfill"], ledger=ledger)
    ok = all(new_ok(r.delta[t]) and r.delta[t].drows == 0 and r.delta[t].dseq == 0
             and r.delta[t].after.digest == baseline[t].digest
             and r.delta[t].after.rows == baseline[t].rows for t in TABLES)
    lines = [f"{'OK' if ok else 'NG'} 修正後 --backfill 1回: {fmt_run(r)} ・行数不変"
             f"(log {baseline['price_anomaly_log'].rows}・metrics {baseline['price_anomaly_metrics'].rows})・中身ハッシュ不変"]
    dbo = ctx.fresh_copy("backfill_before.db")
    ro = measure("backfill", "before", mods["before"], dbo, ctx, args=["--backfill"], ledger=ledger)
    require_counted(ro, "backfill(修正前)")
    fell = all(old_shape(ro.delta[t]) and ro.delta[t].drows == 0 and ro.delta[t].dseq > 0
               and unchanged(ro.delta[t]) for t in TABLES)
    return Item("backfill keeps sequence", ok, lines,
                (fell, "修正前コードの--backfill: 中身不変のまま連番が進む: " + fmt_run(ro)))


def item_ledger(ledger, calib_old_seen):
    lines = [f"{'run':<16}{'code':<8}{'table':<10}{'Δseq':>7}{'Δrows':>7}{'INSERT文':>9}"]
    ok = True
    for label, ver, t, dseq, drows, att in ledger:
        mark = ""
        if ver == "after":
            good = att > 0 and dseq == drows
            ok &= good
            mark = "" if good else "  <-- 不変量違反"
        lines.append(f"{label:<16}{ver:<8}{SHORT[t]:<10}{dseq:>7}{drows:>7}{att:>9}{mark}")
    lines.append("判定: 修正後(after)の全行で INSERT文>0 かつ Δseq＝Δrows。修正前(before)は参考表示(連番=INSERT文の回数)")
    lines.append(f"{'OK' if calib_old_seen else 'NG'} この表は違反を表示できる: 修正前コードの行に Δseq≠Δrows が現れる"
                 "(較正は no-op の項目と同じ実行で兼ねる)")
    return Item("sequence vs rows table", ok and calib_old_seen, lines, None)


def item_existing_selftests(ctx, old_bytes, new_bytes):
    home = ctx.root / "home"
    db_dir = home / "Desktop" / "china-ets-mcp" / "data"
    db_dir.mkdir(parents=True)
    env = dict(os.environ, USERPROFILE=str(home), HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    outputs = {}
    for ver, src in (("before", old_bytes), ("after", new_bytes)):
        d = ctx.root / f"selftests_{ver}"
        d.mkdir()
        (d / "price_anomaly_detect.py").write_bytes(src)
        for name in EXISTING_SELFTESTS:
            shutil.copyfile(SCRIPTS_DIR / name, d / name)
        for name in EXISTING_SELFTESTS:
            shutil.copyfile(ctx.prod, db_dir / "china_ets.db")  # 毎回まっさらなコピー(ホームを差し替えて実行)
            cp = subprocess.run([sys.executable, "-X", "utf8", str(d / name)],
                                capture_output=True, env=env, cwd=str(d), timeout=900)
            outputs[(ver, name)] = (cp.returncode, cp.stdout.decode("utf-8", errors="replace"))
    lines, ok = [], True
    for name in EXISTING_SELFTESTS:
        rb, ob = outputs[("before", name)]
        ra, oa = outputs[("after", name)]
        same = (rb == ra and ob == oa and ob.strip() != "")
        ok &= same
        n_ok = len(re.findall(r"^\s*OK:", ob, re.M))
        n_fail = len(re.findall(r"^\s*FAIL:", ob, re.M))
        all_pass = "ALL PASS" in ob
        lines.append(f"{'OK' if same else 'NG'} {name}: 標準出力の差分={'なし' if ob == oa else 'あり'} ・"
                     f"終了コード 修正前={rb}/修正後={ra} ・出力{len(ob.splitlines())}行 ・"
                     f"OK行={n_ok}/FAIL行={n_fail}/ALL PASS表示={all_pass}")
        if ob != oa:
            diff = list(difflib.unified_diff(ob.splitlines(), oa.splitlines(), "before", "after", lineterm="", n=0))
            lines.extend("    " + ln for ln in diff[:12])
    return Item("existing selftests unchanged", ok, lines, None)


def item_isolation_post(before_fp, prod):
    after_fp = file_fingerprint(prod)
    same = before_fp == after_fp
    return Item("production database untouched (after all runs)", same,
                [f"本番ファイルの sha256・サイズ・更新時刻 が実行の前後で{'不変' if same else '変化した'} "
                 f"(sha256先頭12桁 {before_fp[0][:12]} → {after_fp[0][:12]}・{after_fp[1]} bytes)"], None)


# ---------------------------------------------------------------- 本体

def print_item(it):
    print(f"[{'PASS' if it.ok else 'FAIL'}] {it.name}")
    for ln in it.lines:
        print(f"    {ln}")
    if it.calib is not None:
        print(f"    較正({'想定どおり落ちた' if it.calib[0] else '落ちなかった=検査自体の不良'}): {it.calib[1]}")


def run(prod):
    before_fp = file_fingerprint(prod)
    old_bytes = fetch_before_source()
    new_bytes = WORKTREE_MODULE.read_bytes()
    new_text = new_bytes.decode("utf-8")
    print("=== 行が増えない登録で連番を進めないことの検査 ===")
    print(f"修正前コード(git {BEFORE_COMMIT}:{MODULE_REL})  sha256先頭12桁={sha12(old_bytes)}")
    print(f"作業ツリー側({MODULE_REL})             sha256先頭12桁={sha12(new_bytes)}")
    print(f"sqlite {sqlite3.sqlite_version} / python {sys.version.split()[0]} / 本番DB(読取のみ)="
          f"{prod.relative_to(REPO_ROOT).as_posix() if prod.is_relative_to(REPO_ROOT) else prod.name}"
          f" sha256先頭12桁={before_fp[0][:12]} {before_fp[1]} bytes")
    print()
    items, ledger = [], []
    with tempfile.TemporaryDirectory(prefix="seqchk_", ignore_cleanup_errors=True) as td:
        ctx = Ctx(td, prod)
        mods = {"before": load_module(old_bytes, "pad_before", ctx.root),
                "after": load_module(new_bytes, "pad_after", ctx.root)}
        unbound = load_module(new_bytes, "pad_unbound", ctx.root)
        skip_insert = load_module(
            mutate(new_text, "WHERE NOT EXISTS", "WHERE 0 AND NOT EXISTS", 2).encode("utf-8"),
            "pad_skip_insert", ctx.root)
        older_only = load_module(
            mutate(new_text, "? > source_fetched_at", "? < source_fetched_at", 1).encode("utf-8"),
            "pad_older_only", ctx.root)
        equal_updates = load_module(
            mutate(new_text, "? > source_fetched_at", "? >= source_fetched_at", 1).encode("utf-8"),
            "pad_equal_updates", ctx.root)
        baseline = table_state(ctx.fresh_copy("baseline.db"))

        progress("隔離の確認")
        iso_pre = item_isolation_pre(ctx, mods, unbound)
        progress("no-op run keeps sequence")
        items.append(item_noop(ctx, mods, baseline, ledger))
        progress("missing rows are restored")
        items.append(item_missing_rows(ctx, mods, baseline, ledger, skip_insert))
        progress("stale stored rows are refreshed")
        items.append(item_stale_store(ctx, mods, baseline, ledger, older_only))
        progress("old and new code leave identical contents")
        items.append(item_identical_contents(ctx, mods, baseline, ledger, equal_updates))
        progress("backfill keeps sequence")
        items.append(item_backfill(ctx, mods, baseline, ledger))
        old_violates = any(ver == "before" and dseq != drows for _l, ver, _t, dseq, drows, _a in ledger)
        items.append(item_ledger(ledger, old_violates))
        progress("existing selftests unchanged(子プロセスで実行)")
        items.append(item_existing_selftests(ctx, old_bytes, new_bytes))
    iso_post = item_isolation_post(before_fp, prod)
    items.insert(0, Item("production database untouched", iso_pre.ok and iso_post.ok,
                         iso_pre.lines + iso_post.lines, iso_pre.calib))

    for it in items:
        print_item(it)
    calibs = [it.calib for it in items if it.calib is not None]
    fell = sum(1 for c in calibs if c[0])
    all_ok = all(it.ok for it in items) and fell == len(calibs)
    print()
    print(f"=== {'ALL PASS' if all_ok else 'FAIL'} (項目 {sum(1 for i in items if i.ok)}/{len(items)}) ・ 較正 {fell}/{len(calibs)} ===")
    print("走査範囲外: 公開ページ・他の表・下流の表示・source_fetched_atがNULLの入力は見ていない")
    return 0 if all_ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(DEFAULT_DB), help="検査の元にする本番DB(読むだけ)")
    args = ap.parse_args()
    prod = Path(args.db).resolve()
    if not prod.is_file():
        print(f"DBが見つからない: {prod}")
        return 2
    try:
        return run(prod)
    except InstrumentError as e:
        print(f"検査自体の不良(実行せずに止めた): {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
