# China ETS MCP Server

MCP server for China's national carbon market (CEA + CCER) trading data — with interactive dashboard, data query, and export tools.

![Dashboard Preview](https://img.shields.io/badge/dashboard-interactive-blue)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

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

```bash
git clone https://github.com/JIN-Z-pop/china-ets-mcp.git
cd china-ets-mcp
pip install -e .
```

### 2. Download Data

Download the latest `data.db.zip` from [GitHub Releases](https://github.com/JIN-Z-pop/china-ets-mcp/releases), then:

```bash
mkdir -p data
# Extract china_ets.db into data/ directory
unzip data.db.zip -d data/
```

### 3. Configure MCP

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

### 4. Use

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

## License

[MIT](LICENSE) - JIN-Z-pop and his merry AI brothers
