"""Dashboard HTML generator using Jinja2 + Plotly."""
import json
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from ..db.manager import DBManager


def _clean_records(records: list[dict], drop_keys: set[str] | None = None,
                   keep_none_keys: frozenset[str] = frozenset()) -> list[dict]:
    """Remove unnecessary fields and replace None with 0.

    keep_none_keys の列は None を残す(累計系: 欠測を0と表示すると「累計ゼロ」という
    偽の事実になるため。2026-08-22 列分離に伴う是正)。
    """
    drop = drop_keys or {"fetched_at"}
    cleaned = []
    for r in records:
        row = {k: (v if (v is not None or k in keep_none_keys) else 0)
               for k, v in r.items() if k not in drop}
        cleaned.append(row)
    return cleaned


# CEA表示用: 累計はcum_*_derived(日次totalの全史累積・全行値あり)へ一本化(2026-08-22)。
# 旧cumulative_*は出所混成の凍結列で新規行はNULL — None→0置換すると偽ゼロがHTMLに出る。
# reported(原典公表値・欠測あり)は分析用でありラベルなしの表示には出さない。
_CEA_DROP = {"fetched_at", "cum_volume_reported", "cum_amount_reported",
             "cum_volume_derived", "cum_amount_derived"}


def _cea_display(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        row = dict(r)
        row["cumulative_volume"] = row.get("cum_volume_derived")
        row["cumulative_amount"] = row.get("cum_amount_derived")
        out.append(row)
    return out


def _clean_summary(summary: dict) -> dict:
    """Replace None values with sensible defaults for JSON serialization."""
    return {k: (v if v is not None else 0) for k, v in summary.items()}


def generate_dashboard(db: DBManager, output_path: str) -> str:
    """Generate interactive HTML dashboard."""
    cea_data = _clean_records(_cea_display(db.get_all_cea()), drop_keys=_CEA_DROP)
    ccer_data = _clean_records(db.get_all_ccer(),
                               keep_none_keys=frozenset({"cumulative_volume", "cumulative_amount"}))
    cea_summary = _clean_summary(db.get_cea_summary())
    ccer_summary = _clean_summary(db.get_ccer_summary())

    template_dir = Path(__file__).parent.parent.parent.parent / "dashboard"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("template.html")

    html = template.render(
        cea_data_json=json.dumps(cea_data, ensure_ascii=False),
        ccer_data_json=json.dumps(ccer_data, ensure_ascii=False),
        cea_summary_json=json.dumps(cea_summary, ensure_ascii=False),
        ccer_summary_json=json.dumps(ccer_summary, ensure_ascii=False),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
