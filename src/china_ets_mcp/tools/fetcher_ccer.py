"""CCER (China Certified Emission Reduction) daily trading data fetcher.

Data source: CCER Official Website
JSON API: https://www.ccer.com.cn/wcm/ccer/data/2502lshq.json
"""
import re
import json
import time
import requests
from ..db.manager import DBManager

BASE_URL = "https://www.ccer.com.cn/wcm/ccer/html/"
JSON_URL = "https://www.ccer.com.cn/wcm/ccer/data/2502lshq.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.ccer.com.cn/wcm/ccer/html/2502lshq/index.html",
}
REQUEST_DELAY = 0.3


def extract_trading_data(html_content: str, title: str) -> dict:
    """Extract CCER trading data from report page HTML."""
    data = {
        "date": "",
        # daily_volume/daily_amount/avg_price の既定0は維持(原典が無取引日に0を明示し、
        # 統一正本側 load_ccer が (avg_price==0 and vol==0) で no_trade を判定するため)。
        "daily_volume": 0, "daily_amount": 0.0,
        "avg_price": 0.0,
        # 累計2列の既定はNone。原典が累计を載せない日の0代入は偽の事実になる
        # (2026-08-21 ETS-DB全面精査で188/357行を実測)。欠測はNULLで表す。
        # 🔴 同一ロジックの兄弟実装: C:\Users\jin_z\ccer_daily_data_collector.py(毎朝の実行体)
        "cumulative_volume": None, "cumulative_amount": None,
    }

    date_match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title)
    if date_match:
        y, m, d = date_match.groups()
        data["date"] = f"{y}-{m.zfill(2)}-{d.zfill(2)}"

    # Strip HTML tags so label/number separators like 成交量</span>224,348吨
    # don't break the \s* separators below (2026-06-08 224kt parse-fail fix。
    # 2026-08-22: 兄弟実装(毎朝collector)にのみ入っていた修正を対称移植=drift解消)
    html_content = re.sub(r"<[^>]+>", "", html_content)

    patterns = {
        "daily_volume": (r"(?<!累计)成交量\s*([0-9,]+)\s*吨", lambda x: int(x.replace(",", ""))),
        "daily_amount": (r"(?<!累计)成交额\s*([0-9,.]+)\s*元", lambda x: float(x.replace(",", ""))),
        "avg_price": (r"成交均价\s*([0-9,.]+)\s*元/吨", lambda x: float(x.replace(",", ""))),
        "cumulative_volume": (r"累计成交量\s*([0-9,]+)\s*吨", lambda x: int(x.replace(",", ""))),
        "cumulative_amount": (r"累计成交额\s*([0-9,.]+)\s*元", lambda x: float(x.replace(",", ""))),
    }

    for key, (pattern, converter) in patterns.items():
        match = re.search(pattern, html_content)
        if match:
            data[key] = converter(match.group(1))

    return data


def fetch_ccer_incremental(db: DBManager) -> dict:
    """Fetch new CCER data since last recorded date. Returns summary dict."""
    latest_date = db.get_latest_date("ccer")
    existing_dates = set()
    if latest_date:
        existing = db.get_all_ccer()
        existing_dates = {r["date"] for r in existing}

    # Fetch JSON index
    try:
        resp = requests.get(JSON_URL, headers=HEADERS, timeout=30)
        resp.encoding = "utf-8"
        records = json.loads(resp.text).get("rows", [])
    except Exception as e:
        db.log_fetch("ccer", 0, "error", str(e))
        return {"market": "ccer", "new_records": 0, "error": str(e)}

    new_records = 0
    for record in records:
        title = record.get("title", "")
        url = record.get("url", "")

        # Quick date check from title
        date_match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title)
        if date_match:
            y, m, d = date_match.groups()
            date_str = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
            if date_str in existing_dates:
                continue

        # Fetch detail page
        try:
            full_url = BASE_URL + url
            page_resp = requests.get(full_url, headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }, timeout=30)
            page_resp.encoding = "utf-8"
            data = extract_trading_data(page_resp.text, title)

            if data["date"] and data["date"] not in existing_dates:
                inserted = db.insert_ccer(data)
                new_records += inserted
                existing_dates.add(data["date"])
        except Exception:
            continue

        time.sleep(REQUEST_DELAY)

    db.log_fetch("ccer", new_records, "success", f"Fetched {new_records} new records")
    return {"market": "ccer", "new_records": new_records, "latest_date": db.get_latest_date("ccer")}
