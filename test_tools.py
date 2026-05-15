"""
Standalone test script — exercises all 21 tools without MCP transport.
Run this to verify Dhan API connectivity before connecting to Claude Desktop.

Usage:
    python test_tools.py
    python test_tools.py --tool get_index_spot   # run a single tool
"""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import Callable

# Ensure .env is loaded before any import
from dotenv import load_dotenv
load_dotenv()

import config
import instrument_master as im
from tools.market_data import (
    get_index_spot, get_ltp, get_quote, get_market_depth, search_instrument,
)
from tools.option_chain import (
    get_option_expiries, get_option_chain, get_atm_strike,
)
from tools.historical import (
    get_candles, get_recent_candles, get_expired_option_data,
)
from tools.portfolio import (
    get_holdings, get_positions, get_fund_limits, get_order_book, get_trade_book,
)
from tools.analysis import (
    compute_pcr, compute_max_pain, find_oi_buildup, get_market_summary,
)

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
SKIP = "\033[93m~ SKIP\033[0m"


def run(name: str, fn: Callable, *args, **kwargs) -> bool:
    print(f"\n{'─'*60}")
    print(f"  {name}")
    print(f"{'─'*60}")
    try:
        result = fn(*args, **kwargs)
        print(result)
        ok = result is not None and "**Error**" not in str(result)
        print(f"\n  → {PASS if ok else FAIL}")
        return ok
    except Exception:
        traceback.print_exc()
        print(f"\n  → {FAIL}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Dhan MCP tools standalone")
    parser.add_argument("--tool", default=None, help="Run a single tool by function name")
    args = parser.parse_args()

    # Validate credentials first
    try:
        config.validate_credentials()
    except ValueError as e:
        print(f"[ERROR] {e}\nCopy .env.example → .env and fill in your credentials.")
        sys.exit(1)

    print("\nLoading instrument master...")
    try:
        im.load_instrument_master()
        print(f"  Loaded {len(im._symbol_map):,} symbols")
    except Exception as e:
        print(f"  WARNING: {e} — symbol-dependent tests may fail")

    # ---------- Test suite ----------
    tests: list[tuple[str, Callable, tuple, dict]] = [
        # Market data
        ("get_index_spot(NIFTY)",         get_index_spot,      ("NIFTY",), {}),
        ("get_index_spot(BANKNIFTY)",     get_index_spot,      ("BANKNIFTY",), {}),
        ("get_ltp([NIFTY])",              get_ltp,             (["NIFTY"],), {}),
        ("get_quote([RELIANCE])",         get_quote,           (["RELIANCE"],), {}),
        ("get_market_depth(RELIANCE)",    get_market_depth,    ("RELIANCE",), {"levels": 5}),
        ("search_instrument(NIFTY)",      search_instrument,   ("NIFTY",), {}),

        # Option chain
        ("get_option_expiries(NIFTY)",    get_option_expiries, ("NIFTY",), {}),
        ("get_option_chain(NIFTY)",       get_option_chain,    ("NIFTY",), {"expiry": "nearest", "strikes_range": 5}),
        ("get_atm_strike(NIFTY)",         get_atm_strike,      ("NIFTY",), {}),

        # Historical
        ("get_recent_candles(NIFTY,DAY)", get_recent_candles,  ("NIFTY", "DAY"), {"count": 10}),
        ("get_recent_candles(NIFTY,15)",  get_recent_candles,  ("NIFTY", "15"),  {"count": 20}),
        ("get_candles(RELIANCE,DAY)",     get_candles,
            ("RELIANCE", "DAY", "2025-01-01", "2025-01-15"), {}),

        # Portfolio (may return empty outside market hours — that's fine)
        ("get_holdings()",                get_holdings,        (), {}),
        ("get_positions()",               get_positions,       (), {}),
        ("get_fund_limits()",             get_fund_limits,     (), {}),
        ("get_order_book()",              get_order_book,      (), {}),
        ("get_trade_book()",              get_trade_book,      (), {}),

        # Analytics
        ("compute_pcr(NIFTY)",            compute_pcr,         ("NIFTY",), {}),
        ("compute_max_pain(NIFTY)",       compute_max_pain,    ("NIFTY",), {}),
        ("find_oi_buildup(NIFTY)",        find_oi_buildup,     ("NIFTY",), {"top_n": 3}),
        ("get_market_summary(NIFTY)",     get_market_summary,  ("NIFTY",), {}),
    ]

    if args.tool:
        tests = [(n, f, a, k) for n, f, a, k in tests if args.tool.lower() in n.lower()]
        if not tests:
            print(f"No test found matching '{args.tool}'")
            sys.exit(1)

    passed = failed = 0
    for name, fn, a, k in tests:
        ok = run(name, fn, *a, **k)
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n{'═'*60}")
    print(f"  Results: {passed} passed, {failed} failed out of {passed+failed} tests")
    print(f"{'═'*60}\n")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
