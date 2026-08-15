"""CEA (Carbon Emission Allowance) daily trading data fetcher.

Data source: Shanghai Environment & Energy Exchange
URL: https://overview.cneeex.com/qgtpfqjy/mrgk/
"""
import re
import time
import requests
from datetime import datetime
from ..db.manager import DBManager

BASE_URL = "https://overview.cneeex.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
    "Referer": "https://overview.cneeex.com/",
}
REQUEST_DELAY = 0.5


def extract_report_urls(html_content: str) -> list[tuple[str, str]]:
    """Extract (date, url) pairs from list page HTML."""
    pattern = r"/c/(\d{4}-\d{2}-\d{2})/(\d+)\.shtml"
    matches = re.findall(pattern, html_content)
    return [(date_str, f"{BASE_URL}/c/{date_str}/{rid}.shtml") for date_str, rid in matches]


def extract_trading_data(html_content: str, date_str: str) -> dict | None:
    """Extract trading data from individual report page."""
    data = {
        "date": date_str,
        "opening_price": 0.0, "high_price": 0.0,
        "low_price": 0.0, "closing_price": 0.0,
        "listed_volume": 0, "listed_amount": 0.0,
        "block_volume": 0, "block_amount": 0.0,
        "total_volume": 0, "total_amount": 0.0,
        "cumulative_volume": 0, "cumulative_amount": 0.0,
    }

    patterns = {
        "opening_price": (r"开盘价[：:\s]*([0-9.]+)\s*元/吨", float),
        "high_price": (r"最高价[：:\s]*([0-9.]+)\s*元/吨", float),
        "low_price": (r"最低价[：:\s]*([0-9.]+)\s*元/吨", float),
        "closing_price": (r"收盘价[：:\s]*([0-9.]+)\s*元/吨", float),
        "listed_volume": (r"挂牌协议交易成交量[：:\s]*([0-9,]+)\s*吨", lambda x: int(x.replace(",", ""))),
        "listed_amount": (r"挂牌协议交易.*?成交额[：:\s]*([0-9,.]+)\s*元", lambda x: float(x.replace(",", ""))),
        "block_volume": (r"大宗协议交易成交量[：:\s]*([0-9,]+)\s*吨", lambda x: int(x.replace(",", ""))),
        "block_amount": (r"大宗协议交易.*?成交额[：:\s]*([0-9,.]+)\s*元", lambda x: float(x.replace(",", ""))),
        "cumulative_volume": (r"累计成交量[：:\s]*([0-9,]+)\s*吨", lambda x: int(x.replace(",", ""))),
        "cumulative_amount": (r"累计成交额[：:\s]*([0-9,.]+)\s*元", lambda x: float(x.replace(",", ""))),
    }

    for key, (pattern, converter) in patterns.items():
        match = re.search(pattern, html_content)
        if match:
            data[key] = converter(match.group(1))

    data["total_volume"] = data["listed_volume"] + data["block_volume"]
    data["total_amount"] = data["listed_amount"] + data["block_amount"]

    return data if data["closing_price"] > 0 else None


def _fetch_page(url: str) -> str | None:
    """Fetch page content with error handling."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.encoding = "utf-8"
        return resp.text if resp.status_code == 200 else None
    except Exception:
        return None


def fetch_cea_incremental(db: DBManager, year: int | None = None) -> dict:
    """Fetch new CEA data since last recorded date. Returns summary dict."""
    latest_date = db.get_latest_date("cea")
    target_year = year or datetime.now().year
    years = [target_year] if year else list(range(2021, target_year + 1))

    new_records = 0
    seen_dates = set()

    # Load existing dates to skip
    if latest_date:
        existing = db.get_all_cea()
        seen_dates = {r["date"] for r in existing}

    for yr in years:
        base_list_url = f"{BASE_URL}/qgtpfqjy/mrgk/{yr}n/"
        for page_num in range(1, 21):
            url = base_list_url if page_num == 1 else f"{base_list_url}index_{page_num}.shtml"
            time.sleep(REQUEST_DELAY)
            html = _fetch_page(url)
            if not html:
                break

            report_urls = extract_report_urls(html)
            if not report_urls:
                break

            for date_str, report_url in report_urls:
                if date_str in seen_dates:
                    continue
                seen_dates.add(date_str)
                time.sleep(REQUEST_DELAY)

                report_html = _fetch_page(report_url)
                if not report_html:
                    continue

                data = extract_trading_data(report_html, date_str)
                if data:
                    inserted = db.insert_cea(data)
                    new_records += inserted

    status = "success" if new_records >= 0 else "error"
    db.log_fetch("cea", new_records, status, f"Fetched {new_records} new records")

    return {"market": "cea", "new_records": new_records, "latest_date": db.get_latest_date("cea")}
