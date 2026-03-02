"""Dashboard HTML generator using Jinja2 + Plotly."""
import json
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from ..db.manager import DBManager


def _clean_records(records: list[dict], drop_keys: set[str] | None = None) -> list[dict]:
    """Remove unnecessary fields and replace None with 0."""
    drop = drop_keys or {"fetched_at"}
    cleaned = []
    for r in records:
        row = {k: (v if v is not None else 0) for k, v in r.items() if k not in drop}
        cleaned.append(row)
    return cleaned


def _clean_summary(summary: dict) -> dict:
    """Replace None values with sensible defaults for JSON serialization."""
    return {k: (v if v is not None else 0) for k, v in summary.items()}


def generate_dashboard(db: DBManager, output_path: str) -> str:
    """Generate interactive HTML dashboard."""
    cea_data = _clean_records(db.get_all_cea())
    ccer_data = _clean_records(db.get_all_ccer())
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
