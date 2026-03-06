# China ETS MCP Server

MCP server for China's national carbon market (CEA + CCER) trading data — with interactive dashboard, data query, and export tools.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/MCP-compatible-blue)

> **[Live Dashboard Demo](https://jin-z-pop.github.io/china-ets-mcp/)** — Click to explore China ETS data interactively. No installation required.

## Features

- **Market Data Query** — Query historical CEA and CCER trading data by date range
- **Market Summary** — Get latest prices, price ranges, and trading statistics
- **Data Export** — Download trading data as CSV or XLSX
- **Interactive Dashboard** — Generate a Plotly-based HTML dashboard with candlestick charts, volume analysis, and multi-language support (EN/CN/JA/KO)

## Data Sources

| Market | Source | Coverage |
|--------|--------|----------|
| **CEA** (Carbon Emission Allowance) | Shanghai Environment and Energy Exchange | 2021-07 ~ present |
| **CCER** (China Certified Emission Reduction) | CCER Official (ccer.com.cn) | 2024-01 ~ present |

## Quick Start

### 1. Install

**Recommended** (auto-manages Python version):
```bash
git clone https://github.com/JIN-Z-pop/china-ets-mcp.git
cd china-ets-mcp
uv sync
```

Or with pip (requires Python 3.11+):
```bash
pip install -e .
```

### 2. Download Data

Download the latest `data.db.zip` from [GitHub Releases](https://github.com/JIN-Z-pop/china-ets-mcp/releases), then:

```bash
mkdir -p data
# Extract china_ets.db into data/ directory
unzip data.db.zip -d data/
```

### 3. View Dashboard (No MCP Required)

```bash
uv run china-ets-dashboard
```

Or with pip install:

```bash
china-ets-dashboard
```

This generates an interactive HTML dashboard and opens it in your browser.

### 4. Configure MCP (Optional)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "china-ets": {
      "command": "python",
      "args": ["-m", "china_ets_mcp.server_lite"],
      "env": {
        "DATA_DIR": "/path/to/china-ets-mcp/data"
      }
    }
  }
}
```

Or use the CLI entry point:

```json
{
  "mcpServers": {
    "china-ets": {
      "command": "china-ets-mcp-lite"
    }
  }
}
```

### 5. Use with Claude

Once configured, you can ask Claude:

- *"Show me the latest CEA market summary"*
- *"Query CEA trading data from 2025-01-01 to 2025-06-30"*
- *"Download CCER data as CSV"*
- *"Generate a dashboard for China carbon market data"*

## MCP Tools

| Tool | Description |
|------|-------------|
| `query_trading_data` | Query CEA or CCER historical data by date range |
| `get_market_summary` | Get latest prices, stats, and market overview |
| `download_data` | Export data as CSV or XLSX |
| `generate_dashboard` | Create interactive HTML dashboard with Plotly charts |

## Dashboard

The generated dashboard includes:

- CEA price trend (line chart)
- CEA candlestick + volume analysis
- Annual price distribution (box plot)
- Monthly trading volume heatmap
- CCER average price trend
- Multi-language support (English, Chinese, Japanese, Korean)

## Project Structure

```
china-ets-mcp/
├── src/china_ets_mcp/
│   ├── server_lite.py       # MCP server (4 tools)
│   ├── tools/
│   │   ├── query.py         # Data query engine
│   │   ├── exporter.py      # CSV/XLSX export
│   │   └── dashboard.py     # Dashboard generator
│   └── db/
│       ├── models.py        # SQLite schema
│       └── manager.py       # Database operations
├── dashboard/
│   └── template.html        # Plotly + i18n template
├── tests/                   # Test suite
├── examples/                # Sample data
└── data/                    # SQLite database (not in repo)
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

## Data Updates

Trading data is updated periodically via GitHub Releases. Check the [Releases page](https://github.com/JIN-Z-pop/china-ets-mcp/releases) for the latest data.

## Disclaimer

This tool is provided for research and educational purposes only. The authors make no warranties regarding accuracy, completeness, or fitness for any particular purpose, and accept no liability for any loss or damage arising from its use. Use of this tool is entirely at your own risk.

本工具仅供研究与教育目的使用。作者不对其准确性、完整性或特定用途的适用性作任何保证，亦不对因使用本工具而产生的任何损失或损害承担责任。使用本工具的风险由用户自行承担。

## License

[MIT](LICENSE) - JIN-Z-pop and his merry AI brothers
