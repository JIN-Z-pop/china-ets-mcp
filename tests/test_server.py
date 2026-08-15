"""Tests for MCP server tool registration."""
from china_ets_mcp.server import mcp


def test_tools_registered():
    # FastMCP registers tools as decorated functions
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "fetch_cea_daily" in tool_names
    assert "fetch_ccer_daily" in tool_names
    assert "fetch_all" in tool_names
    assert "query_trading_data" in tool_names
    assert "get_market_summary" in tool_names
    assert "download_data" in tool_names
    assert "generate_dashboard" in tool_names
    assert "register_to_rag" in tool_names
