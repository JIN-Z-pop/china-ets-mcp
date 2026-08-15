"""Tests for CCER fetcher."""
import pytest
from china_ets_mcp.tools.fetcher_ccer import extract_trading_data


def test_extract_ccer_data():
    html = """
    核证自愿减排量成交量413吨，成交额31,065.37元，成交均价75.22元/吨。
    累计成交量6,340,091吨，累计成交额457,234,689.16元。
    """
    data = extract_trading_data(html, "2025年12月1日CCER市场行情")
    assert data["date"] == "2025-12-01"
    assert data["daily_volume"] == 413
    assert data["daily_amount"] == 31065.37
    assert data["avg_price"] == 75.22
    assert data["cumulative_volume"] == 6340091


def test_extract_ccer_no_date():
    html = "<p>No report</p>"
    data = extract_trading_data(html, "invalid title")
    assert data["date"] == ""
