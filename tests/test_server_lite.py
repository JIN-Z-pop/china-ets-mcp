"""Tests for Lite MCP server tool registration."""
from china_ets_mcp.server_lite import mcp


def test_lite_tools_registered():
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "query_trading_data" in tool_names
    assert "get_market_summary" in tool_names
    assert "download_data" in tool_names
    assert "generate_dashboard" in tool_names


def test_lite_no_private_tools():
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "fetch_cea_daily" not in tool_names
    assert "fetch_ccer_daily" not in tool_names
    assert "fetch_all" not in tool_names
    assert "register_to_rag" not in tool_names
