"""Tests for CEA fetcher."""
import pytest
from china_ets_mcp.tools.fetcher_cea import (
    extract_report_urls,
    extract_trading_data,
)


def test_extract_report_urls():
    html = '<a href="/c/2025-01-15/12345.shtml">Report</a>'
    urls = extract_report_urls(html)
    assert len(urls) == 1
    assert urls[0][0] == "2025-01-15"


def test_extract_trading_data_full():
    html = """
    开盘价52.19元/吨，最高价52.28元/吨，最低价51.21元/吨，收盘价51.34元/吨。
    挂牌协议交易成交量1,234吨，成交额63,453.06元。
    大宗协议交易成交量5,000吨，成交额256,700.00元。
    累计成交量820,000,000吨，累计成交额54,000,000,000.00元。
    """
    data = extract_trading_data(html, "2025-01-15")
    assert data["closing_price"] == 51.34
    assert data["opening_price"] == 52.19
    assert data["listed_volume"] == 1234
    assert data["block_volume"] == 5000
    assert data["cum_volume_reported"] == 820000000


def test_extract_trading_data_no_price():
    html = "<p>No data today</p>"
    data = extract_trading_data(html, "2025-01-15")
    assert data is None
