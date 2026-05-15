# Dhan MCP Personal — NIFTY Options Trading Assistant

A read-only MCP server that connects your Dhan trading account to Claude Desktop.
Provides 21 tools covering market data, option chain analytics, historical candles,
and portfolio viewing. **No order placement. Ever.**

---

## Prerequisites

- Python 3.10 or newer
- A Dhan trading account with API access enabled
- Claude Desktop installed

---

## Setup

### 1. Clone / download the project

```
dhan-mcp-personal/
```

### 2. Create the virtual environment

```bash
cd dhan-mcp-personal
python3 -m venv .venv
```

**Activate (macOS/Linux):**
```bash
source .venv/bin/activate
```

> **Windows note:** `.venv\Scripts\activate`

You should see `(.venv)` in your prompt.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```
DHAN_CLIENT_ID=your_client_id_here
DHAN_ACCESS_TOKEN=your_access_token_here
```

Get these from [Dhan Developer Portal](https://developers.dhan.co) → My Apps.

### 5. Test connectivity (before connecting to Claude Desktop)

```bat
python test_tools.py
```

This runs all 21 tools standalone and prints pass/fail for each. Fix any
credential or network issues here before proceeding.

To test a single tool:

```bash
python test_tools.py --tool get_index_spot
python test_tools.py --tool option_chain
```

---

## Connect to Claude Desktop

Add this snippet to your Claude Desktop configuration file.

**Config file location (macOS):**
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

Get the exact paths to paste in by running this in your terminal (with `.venv` activated):

```bash
echo "Python: $(which python)"
echo "Server: $(pwd)/server.py"
```

Then add to the config:

```json
{
  "mcpServers": {
    "dhan-trading": {
      "command": "/Users/YOUR_USERNAME/path/to/dhan-mcp-personal/.venv/bin/python",
      "args": [
        "/Users/YOUR_USERNAME/path/to/dhan-mcp-personal/server.py"
      ],
      "env": {
        "DHAN_CLIENT_ID": "your_client_id_here",
        "DHAN_ACCESS_TOKEN": "your_access_token_here"
      }
    }
  }
}
```

> **Important:** Use the full absolute path to `.venv/bin/python`, not just `python`.
> This ensures Claude Desktop loads the correct environment with all dependencies.
>
> **Windows note:** Use `.venv\Scripts\python.exe` and backslash paths.

After editing, **restart Claude Desktop**. You should see "dhan-trading" appear
in the MCP tools panel (hammer icon).

---

## Tools Reference

### Market Data

| Tool | Description |
|------|-------------|
| `get_index_spot` | Current spot price for NIFTY, BANKNIFTY, FINNIFTY, SENSEX, etc. |
| `get_ltp` | Last traded price for a list of symbols |
| `get_quote` | Full OHLC + bid/ask for a list of symbols |
| `get_market_depth` | Order book depth (up to 20 levels) |
| `search_instrument` | Search instrument master by name/symbol → returns security_id |

### Option Chain

| Tool | Description |
|------|-------------|
| `get_option_expiries` | List all upcoming expiry dates for an underlying |
| `get_option_chain` | Full chain ±N strikes around ATM with OI, IV, greeks |
| `get_atm_strike` | ATM strike + CE/PE premiums for an underlying |

### Historical Data

| Tool | Description |
|------|-------------|
| `get_candles` | OHLCV candles for any timeframe and date range |
| `get_recent_candles` | Latest N candles — auto-computes from_date |
| `get_expired_option_data` | Candles for past option strikes (expiry analysis) |

### Portfolio (Read-Only)

| Tool | Description |
|------|-------------|
| `get_holdings` | Long-term demat holdings |
| `get_positions` | Today's open intraday + delivery positions |
| `get_fund_limits` | Available margin and cash balance |
| `get_order_book` | Today's orders with status |
| `get_trade_book` | Today's executed trades |

### Analytics

| Tool | Description |
|------|-------------|
| `compute_pcr` | OI-based and volume-based Put-Call Ratio |
| `compute_max_pain` | Max pain strike calculation |
| `find_oi_buildup` | Top N strikes by OI and OI change for CE/PE |
| `get_market_summary` | One-call briefing: spot, ATM, PCR, max pain, key levels |
| `refresh_instrument_master` | Force-reload the instrument CSV from Dhan's servers |

---

## Example Claude Prompts

```
What's the NIFTY spot and ATM strike for the nearest expiry?
```
```
Show me the option chain for BANKNIFTY — nearest expiry, 8 strikes around ATM.
```
```
Compute PCR and max pain for NIFTY this week.
```
```
What are my open positions and available margin?
```
```
Get NIFTY 15-minute candles for today.
```
```
Which NIFTY strikes have the highest OI buildup this expiry?
```

---

## Instrument Master Cache

The instrument master CSV is downloaded from Dhan on first run and cached
locally as `instrument_master.csv`. It auto-refreshes if older than 24 hours.

To force a refresh mid-session, ask Claude:

```
Refresh the instrument master.
```

Or run directly:

```bash
python -c "import instrument_master as im; print(im.refresh_instrument_master())"
```

---

## Logs

All tool calls are logged to `mcp_server.log` in the project directory.
Useful for debugging when a tool returns unexpected results.

```bash
tail -f mcp_server.log
```

---

## Troubleshooting

### "Symbol not found in instrument master"
Run `search_instrument` with a partial name. The instrument master uses
Dhan's trading symbols (e.g. `NIFTY25500CE` not `NIFTY 25500 CE`).

### "Dhan API error: rate limit"
Option chain is limited to 1 request per 3 seconds. If Claude calls it
repeatedly in quick succession, the server will automatically throttle.
Wait a few seconds and retry.

### Tools not appearing in Claude Desktop
1. Verify the Python path in `claude_desktop_config.json` is absolute
2. Check that `.env` credentials are correct (or set them in `env` block)
3. Check `mcp_server.log` for startup errors
4. Restart Claude Desktop completely

### "No data returned" outside market hours
Most live data endpoints return empty responses when NSE is closed.
Historical data and instrument master always work.

---

## Security Notes

- `.env` is in `.gitignore` — never commit it
- `.venv/` is in `.gitignore`
- Access token is masked in all log output
- This server is **read-only** — no order placement tools exist

---

## Rate Limits (Dhan API)

| Endpoint | Limit |
|----------|-------|
| Option chain | 1 req / 3 sec |
| Market feed (LTP/quote) | ~10 req / sec |
| Historical data | ~5 req / sec |
| Portfolio endpoints | ~5 req / sec |

The server enforces these automatically via the rate limiter.
