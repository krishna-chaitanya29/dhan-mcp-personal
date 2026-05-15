# Dhan MCP — Personal Trading Assistant for Claude

> A read-only [Model Context Protocol](https://modelcontextprotocol.io) server that gives Claude live access to your Dhan trading account. Option chain analytics, OI buildup, PCR, max pain, historical candles, portfolio reads — all callable in natural language from Claude Desktop.
>
> **No order placement. Ever. AI advises. Human decides.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/FastMCP-2.11-purple.svg)](https://gofastmcp.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Status: Personal use](https://img.shields.io/badge/status-personal--use-orange.svg)]()

---

## Why this exists

Generic LLMs are powerful but blind to your world. Claude doesn't know your broker's API, can't see live NIFTY prices, can't read your portfolio.

This server fixes that — for one trader, on one MacBook, with one broker. It exposes 21 read-only tools to Claude over MCP. The model decides what to call; the server fetches it from Dhan's API; the model writes the brief.

Same architecture works for any private data source — internal docs, your calendar, a company DB, a clinical EMR. This repo is the trading-data version of that pattern.

## What you can ask Claude

```
What's the NIFTY market summary for the nearest expiry?
Compute PCR and max pain for BANKNIFTY this week.
Show me the OI buildup — top 5 CE and PE strikes for NIFTY.
What are my open positions and available margin?
Get NIFTY 15-minute candles for today.
```

## Architecture

```
You → Claude Desktop → Anthropic API (decides which tool)
                   ↓
                stdio
                   ↓
              MCP server (this repo) → Dhan REST API → NSE/BSE
```

Trust boundary: your laptop. Your access token never leaves your machine. Anthropic sees tool results, never credentials.

## Prerequisites

- Python 3.10+ (tested on 3.13)
- A Dhan trading account with API access enabled
- Claude Desktop installed

## Setup

### 1. Clone

```bash
git clone https://github.com/krishna-chaitanya29/dhan-mcp-personal.git
cd dhan-mcp-personal
```

### 2. Create the virtual environment

```bash
python3 -m venv .venv
```

**Activate (macOS / Linux):**
```bash
source .venv/bin/activate
```

**Activate (Windows):**
```bash
.venv\Scripts\activate
```

You should see `(.venv)` in your prompt.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:

```
DHAN_CLIENT_ID=your_client_id_here
DHAN_ACCESS_TOKEN=your_access_token_here
```

Get these from [Dhan Developer Portal](https://developers.dhan.co) → My Apps.

### 5. Test before wiring into Claude Desktop

```bash
python test_tools.py
```

Runs all 21 tools standalone, prints pass/fail. Fix credential or network issues here, not after Claude Desktop is involved.

Single-tool mode:
```bash
python test_tools.py --tool get_index_spot
```

## Connect to Claude Desktop

**Config file location:**

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

Get your exact paths (run from project root with `.venv` active):
```bash
echo "Python: $(which python)"
echo "Server: $(pwd)/server.py"
```

Add to the config:

```json
{
  "mcpServers": {
    "dhan-trading": {
      "command": "/absolute/path/to/dhan-mcp-personal/.venv/bin/python",
      "args": [
        "/absolute/path/to/dhan-mcp-personal/server.py"
      ],
      "env": {
        "DHAN_CLIENT_ID": "your_client_id_here",
        "DHAN_ACCESS_TOKEN": "your_access_token_here"
      }
    }
  }
}
```

> Use the **absolute** path to `.venv/bin/python`, not just `python`. Claude Desktop launches from `/` and won't find your venv otherwise.
>
> **Windows note:** `.venv\Scripts\python.exe` with double-backslashes in JSON.

After editing, **fully quit Claude Desktop** (`Cmd+Q` on macOS — not just close the window) and reopen. The tools appear in the hammer/tools icon.

## Tools

### Market data
| Tool | Description |
| --- | --- |
| `get_index_spot` | Current spot for NIFTY, BANKNIFTY, FINNIFTY, SENSEX |
| `get_ltp` | Last traded price for one or more symbols |
| `get_quote` | Full OHLC + bid/ask for one or more symbols |
| `get_market_depth` | Order book depth (up to 20 levels) |
| `search_instrument` | Symbol → security_id lookup from instrument master |

### Option chain
| Tool | Description |
| --- | --- |
| `get_option_expiries` | All upcoming expiry dates for an underlying |
| `get_option_chain` | Full chain ±N strikes around ATM (OI, IV, Greeks) |
| `get_atm_strike` | ATM strike + CE/PE premiums |

### Historical
| Tool | Description |
| --- | --- |
| `get_candles` | OHLCV for any timeframe and date range |
| `get_recent_candles` | Latest N candles — auto-computes from_date |
| `get_expired_option_data` | Past expiry option candles for backtesting |

### Portfolio (read-only)
| Tool | Description |
| --- | --- |
| `get_holdings` | Long-term demat holdings |
| `get_positions` | Today's open intraday + delivery positions |
| `get_fund_limits` | Available margin and cash balance |
| `get_order_book` | Today's orders with status |
| `get_trade_book` | Today's executed trades |

### Derived analytics
| Tool | Description |
| --- | --- |
| `compute_pcr` | OI-based and volume-based Put-Call Ratio |
| `compute_max_pain` | Max pain strike for an expiry |
| `find_oi_buildup` | Top N CE/PE strikes by OI and OI change |
| `get_market_summary` | One-call briefing: spot, ATM, PCR, max pain, key levels |
| `refresh_instrument_master` | Force-reload the instrument CSV |

## Example output

A real run of `get_market_summary("NIFTY")`:

```
# NIFTY Market Summary — Expiry: 2026-05-12

Spot:       23,815.85
ATM Strike: 23800
PCR (OI):   0.570 → Bearish
Max Pain:   23900

Top CE OI (resistance): 25000, 24000, 24500
Top PE OI (support):    23500, 23000, 23800

ATM CE: LTP 120.80  IV 19.25%
ATM PE: LTP 70.95   IV 15.30%
```

## Instrument master cache

The instrument master CSV is downloaded from Dhan on first run and cached as `instrument_master.csv`. Auto-refreshes when older than 24 hours.

Force refresh mid-session:
```
Refresh the instrument master.
```

Or directly:
```bash
python -c "import instrument_master as im; print(im.refresh_instrument_master())"
```

## Logs

Every tool call is logged to `mcp_server.log` in the project directory.

```bash
tail -f mcp_server.log
```

## Troubleshooting

<details>
<summary><strong>Tools not appearing in Claude Desktop</strong></summary>

1. Python path in config must be absolute — `/usr/bin/python` won't work
2. Check `.env` credentials or the `env` block in the config
3. Open `mcp_server.log` for startup errors
4. Fully quit Claude Desktop (`Cmd+Q`), don't just close the window
</details>

<details>
<summary><strong>"Symbol not found in instrument master"</strong></summary>

Run `search_instrument` with a partial name. Dhan's trading symbols are unspaced — `NIFTY25500CE`, not `NIFTY 25500 CE`.
</details>

<details>
<summary><strong>"Dhan API error: rate limit"</strong></summary>

Option chain is capped at 1 request per 3 seconds. The server throttles automatically — just wait.
</details>

<details>
<summary><strong>"No data returned" outside market hours</strong></summary>

Live endpoints return empty when NSE is closed. Historical data and instrument master always work.
</details>

<details>
<summary><strong>Server crashes with Pydantic / FastMCP error on startup</strong></summary>

Version mismatch between FastMCP and Pydantic. Pin to known-good combo:
```bash
pip install --force-reinstall "fastmcp==2.11.0" "pydantic>=2.11.7" "pydantic-settings>=2.7.0"
```
</details>

## Rate limits (Dhan API)

| Endpoint | Limit |
| --- | --- |
| Option chain | 1 req / 3 sec |
| Market feed (LTP / quote) | ~10 req / sec |
| Historical data | ~5 req / sec |
| Portfolio | ~5 req / sec |

Server enforces these via the rate limiter in `utils/`.

## Security

- `.env` is gitignored — never committed
- `.venv/` is gitignored
- Access token is masked in all log output
- Read-only by design — no order placement, modification, or cancellation tools exist in the codebase
- Read-only is not just policy. It's enforced by absence of code.

## What this is not

- Not a trading bot. Tools only read.
- Not financial advice. Output is data and analytics; decisions are yours.
- Not affiliated with Dhan, Anthropic, or any broker.
- Not for production trading without your own review of every tool's output.

## Built with

- [FastMCP](https://gofastmcp.com) — Python framework for MCP servers
- [dhanhq](https://pypi.org/project/dhanhq/) — official Dhan Python SDK
- [pandas](https://pandas.pydata.org) — instrument master and tabular handling
- [Claude Code](https://www.anthropic.com/claude-code) — scaffolded much of this repo; the architecture, guardrails, and review are mine

## License

MIT — see [LICENSE](LICENSE).

## Author

**Krishna Chaitanya** — final-year CS, building agentic systems.

Open to AI engineering / FinTech roles for 2026. [LinkedIn](https://www.linkedin.com/in/<your-handle>) · [GitHub](https://github.com/krishna-chaitanya29)

If this was useful, ⭐ the repo. Issues and PRs welcome.
