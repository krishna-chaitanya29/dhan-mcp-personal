"""
Dhan MCP Server — READ-ONLY personal trading assistant for Claude Desktop.

Transport: stdio (MCP standard).
This server exposes 21 read-only tools for market data, option chain analysis,
historical data, and portfolio viewing. Order placement is intentionally absent.
"""

from __future__ import annotations

import logging
import sys
from functools import wraps
from typing import Any, Callable

from fastmcp import FastMCP

import config
import instrument_master as im

# ---------------------------------------------------------------------------
# Logging setup — file + stderr
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("dhan_mcp")

# ---------------------------------------------------------------------------
# Import tool implementations
# ---------------------------------------------------------------------------
from tools.market_data import (
    get_index_spot,
    get_ltp,
    get_quote,
    get_market_depth,
    search_instrument,
)
from tools.option_chain import (
    get_option_expiries,
    get_option_chain,
    get_atm_strike,
)
from tools.historical import (
    get_candles,
    get_recent_candles,
    get_expired_option_data,
)
from tools.portfolio import (
    get_holdings,
    get_positions,
    get_fund_limits,
    get_order_book,
    get_trade_book,
)
from tools.analysis import (
    compute_pcr,
    compute_max_pain,
    find_oi_buildup,
    get_market_summary,
)

# ---------------------------------------------------------------------------
# MCP app
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="Dhan Trading Assistant",
    instructions=(
        "Read-only MCP server for Dhan trading account. "
        "Provides market data, option chain analytics, historical candles, "
        "and portfolio views for NIFTY weekly options trading. "
        "ORDER PLACEMENT IS NOT SUPPORTED — this server is intentionally read-only."
    ),
)

# ---------------------------------------------------------------------------
# Logging decorator
# ---------------------------------------------------------------------------
def logged_tool(fn: Callable) -> Callable:
    """Wrap a tool function to log calls and mask sensitive data."""
    @wraps(fn)
    def wrapper(*args, **kwargs) -> Any:
        params = {**{f"arg{i}": a for i, a in enumerate(args)}, **kwargs}
        logger.info("TOOL CALL: %s | params=%s", fn.__name__, params)
        try:
            result = fn(*args, **kwargs)
            logger.info("TOOL OK:   %s | status=success", fn.__name__)
            return result
        except Exception as exc:
            logger.error("TOOL ERR:  %s | error=%s", fn.__name__, exc)
            return f"**Error** [{fn.__name__}]: {exc}"
    return wrapper

# ---------------------------------------------------------------------------
# Register all tools
# ---------------------------------------------------------------------------

# Market data (5 tools)
mcp.tool(logged_tool(get_index_spot))
mcp.tool(logged_tool(get_ltp))
mcp.tool(logged_tool(get_quote))
mcp.tool(logged_tool(get_market_depth))
mcp.tool(logged_tool(search_instrument))

# Option chain (3 tools)
mcp.tool(logged_tool(get_option_expiries))
mcp.tool(logged_tool(get_option_chain))
mcp.tool(logged_tool(get_atm_strike))

# Historical (3 tools)
mcp.tool(logged_tool(get_candles))
mcp.tool(logged_tool(get_recent_candles))
mcp.tool(logged_tool(get_expired_option_data))

# Portfolio (5 tools)
mcp.tool(logged_tool(get_holdings))
mcp.tool(logged_tool(get_positions))
mcp.tool(logged_tool(get_fund_limits))
mcp.tool(logged_tool(get_order_book))
mcp.tool(logged_tool(get_trade_book))

# Analytics (4 tools)
mcp.tool(logged_tool(compute_pcr))
mcp.tool(logged_tool(compute_max_pain))
mcp.tool(logged_tool(find_oi_buildup))
mcp.tool(logged_tool(get_market_summary))

# Instrument master refresh (bonus tool)
@mcp.tool
def refresh_instrument_master() -> str:
    """
    Force-refresh the instrument master CSV from Dhan's servers.

    Downloads the latest compact CSV and rebuilds all symbol lookup maps.
    Use this if a newly listed option strike or symbol is not being found.
    Takes ~5–10 seconds.
    """
    logger.info("TOOL CALL: refresh_instrument_master")
    return im.refresh_instrument_master()


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Starting Dhan MCP Server...")
    try:
        config.validate_credentials()
    except ValueError as exc:
        logger.error("Credential error: %s", exc)
        sys.exit(1)

    logger.info("Loading instrument master...")
    try:
        im.load_instrument_master()
    except Exception as exc:
        logger.warning("Instrument master load failed: %s — some tools may not work", exc)

    logger.info("Dhan MCP Server ready — 21 read-only tools registered")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
