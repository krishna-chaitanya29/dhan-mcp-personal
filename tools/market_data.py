"""
Market data tools: LTP, quotes, depth, index spot, instrument search.
All functions return LLM-friendly strings.

SDK method mapping (dhanhq v2.1.0):
  ticker_data(securities)  → LTP only
  ohlc_data(securities)    → LTP + OHLC
  quote_data(securities)   → LTP + OHLC + depth + OI + volume
"""

from __future__ import annotations

import logging

import dhan_client
import instrument_master as im
from utils.formatters import fmt_number, records_to_table, error_msg
from utils.rate_limiter import throttle
import config

logger = logging.getLogger(__name__)

# Index → (security_id_int, exchange_segment)
INDEX_MAP: dict[str, tuple[int, str]] = {
    "NIFTY":      (13,  "IDX_I"),
    "BANKNIFTY":  (25,  "IDX_I"),
    "FINNIFTY":   (27,  "IDX_I"),
    "MIDCPNIFTY": (442, "IDX_I"),
    "SENSEX":     (51,  "BSE_EQ"),
    "BANKEX":     (421, "BSE_EQ"),
}


def _extract(resp: dict, segment: str, sec_id: str | int) -> dict:
    """Dig into the nested data → data → segment → sec_id structure safely."""
    outer = resp.get("data", {})
    if not isinstance(outer, dict):
        return {}
    inner = outer.get("data", {})
    if not isinstance(inner, dict):
        return {}
    seg_data = inner.get(segment, {})
    if not isinstance(seg_data, dict):
        return {}
    return seg_data.get(str(sec_id), {})


def get_index_spot(index: str) -> str:
    """
    Get the current spot price and day OHLC for a major index.

    Supported indices: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, BANKEX.
    Returns LTP with open, high, low, and day change.
    """
    key = index.upper().replace(" ", "")
    if key not in INDEX_MAP:
        return (
            f"Unknown index '{index}'. "
            f"Supported: {', '.join(INDEX_MAP)}"
        )
    try:
        throttle("ltp", config.DEFAULT_RATE_LIMIT)
        sec_id, segment = INDEX_MAP[key]
        client = dhan_client.get_dhan()
        resp = client.ohlc_data({segment: [sec_id]})
        rec  = _extract(resp, segment, sec_id)
        ltp  = rec.get("last_price", 0)
        ohlc = rec.get("ohlc", {})
        chg  = ltp - ohlc.get("close", ltp)
        pct  = (chg / ohlc.get("close", ltp) * 100) if ohlc.get("close") else 0
        return (
            f"**{key}** LTP: {fmt_number(ltp)}  |  "
            f"Chg: {fmt_number(chg)} ({fmt_number(pct)}%)\n"
            f"Open: {fmt_number(ohlc.get('open', 'N/A'))}  "
            f"High: {fmt_number(ohlc.get('high', 'N/A'))}  "
            f"Low: {fmt_number(ohlc.get('low', 'N/A'))}  "
            f"Prev Close: {fmt_number(ohlc.get('close', 'N/A'))}"
        )
    except Exception as exc:
        logger.error("get_index_spot(%s): %s", index, exc)
        return error_msg("get_index_spot", exc)


def get_ltp(symbols: list[str]) -> str:
    """
    Get Last Traded Price for one or more instruments.

    Accepts a list of trading symbols (e.g. ["RELIANCE", "INFY"]).
    Resolves symbols via instrument master and returns a price table.
    """
    if not symbols:
        return "Provide at least one symbol."
    try:
        throttle("ltp", config.DEFAULT_RATE_LIMIT)
        client = dhan_client.get_dhan()
        feed_req: dict[str, list[int]] = {}
        sym_map: dict[str, tuple[str, str]] = {}

        for sym in symbols:
            try:
                sec_id, segment = im.resolve_to_security_id(sym)
                feed_req.setdefault(segment, []).append(int(sec_id))
                sym_map[sym] = (sec_id, segment)
            except ValueError as e:
                logger.warning("Skipping %s: %s", sym, e)

        if not feed_req:
            return "None of the provided symbols could be resolved."

        resp = client.ticker_data(feed_req)
        rows = []
        for sym, (sec_id, segment) in sym_map.items():
            rec = _extract(resp, segment, sec_id)
            rows.append({
                "Symbol": sym,
                "LTP":    fmt_number(rec.get("last_price", "N/A")),
            })
        return records_to_table(rows)
    except Exception as exc:
        logger.error("get_ltp: %s", exc)
        return error_msg("get_ltp", exc)


def get_quote(symbols: list[str]) -> str:
    """
    Get full OHLC quote for one or more instruments.

    Returns open, high, low, close, LTP, volume, OI, and circuit limits.
    Uses quote_data which includes all available market fields.
    """
    if not symbols:
        return "Provide at least one symbol."
    try:
        throttle("quote", config.DEFAULT_RATE_LIMIT)
        client = dhan_client.get_dhan()
        feed_req: dict[str, list[int]] = {}
        sym_map: dict[str, tuple[str, str]] = {}

        for sym in symbols:
            try:
                sec_id, segment = im.resolve_to_security_id(sym)
                feed_req.setdefault(segment, []).append(int(sec_id))
                sym_map[sym] = (sec_id, segment)
            except ValueError as e:
                logger.warning("Skipping %s: %s", sym, e)

        if not feed_req:
            return "None of the provided symbols could be resolved."

        resp = client.quote_data(feed_req)
        lines = []
        for sym, (sec_id, segment) in sym_map.items():
            rec  = _extract(resp, segment, sec_id)
            ohlc = rec.get("ohlc", {})
            ltp  = rec.get("last_price", 0)
            chg  = ltp - ohlc.get("close", ltp)
            pct  = (chg / ohlc.get("close", ltp) * 100) if ohlc.get("close") else 0
            lines.append(
                f"**{sym}**  LTP: {fmt_number(ltp)}  "
                f"Chg: {fmt_number(chg)} ({fmt_number(pct)}%)\n"
                f"  Open: {fmt_number(ohlc.get('open'))}  "
                f"High: {fmt_number(ohlc.get('high'))}  "
                f"Low: {fmt_number(ohlc.get('low'))}  "
                f"Close: {fmt_number(ohlc.get('close'))}  "
                f"Vol: {fmt_number(rec.get('volume'), 0)}  "
                f"OI: {fmt_number(rec.get('oi'), 0)}"
            )
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_quote: %s", exc)
        return error_msg("get_quote", exc)


def get_market_depth(symbol: str, levels: int = 5) -> str:
    """
    Get order book depth for an instrument (up to 5 bid/ask levels).

    Returns bid and ask price-quantity pairs from the live order book.
    Note: Dhan's quote_data provides 5 depth levels maximum.

    Args:
        symbol: Trading symbol (e.g. "RELIANCE", "NIFTY25000CE").
        levels: Number of depth levels to show (max 5, default 5).
    """
    levels = min(levels, 5)
    try:
        throttle("depth", config.DEFAULT_RATE_LIMIT)
        sec_id, segment = im.resolve_to_security_id(symbol)
        client = dhan_client.get_dhan()
        resp = client.quote_data({segment: [int(sec_id)]})
        rec   = _extract(resp, segment, sec_id)
        depth = rec.get("depth", {})
        buys  = depth.get("buy", [])[:levels]
        sells = depth.get("sell", [])[:levels]

        rows = []
        for i in range(max(len(buys), len(sells))):
            b = buys[i]  if i < len(buys)  else {}
            s = sells[i] if i < len(sells) else {}
            rows.append({
                "Bid Price": fmt_number(b.get("price", "")),
                "Bid Qty":   fmt_number(b.get("quantity", ""), 0),
                "Ask Price": fmt_number(s.get("price", "")),
                "Ask Qty":   fmt_number(s.get("quantity", ""), 0),
            })

        ltp = fmt_number(rec.get("last_price", "N/A"))
        header = f"**Market Depth — {symbol}** | LTP: {ltp}\n"
        return header + records_to_table(rows)
    except Exception as exc:
        logger.error("get_market_depth(%s): %s", symbol, exc)
        return error_msg("get_market_depth", exc)


def search_instrument(query: str) -> str:
    """
    Search the instrument master by symbol, name, or keyword.

    Returns security_id, exchange segment, instrument type, expiry, and
    strike for up to 20 matching instruments. Use this to find the correct
    trading symbol before calling other tools.
    """
    try:
        results = im.search_instruments(query, max_results=20)
        if not results:
            return f"No instruments found for query: '{query}'"
        cols = [
            "SEM_TRADING_SYMBOL", "SEM_SMST_SECURITY_ID",
            "SEM_EXM_EXCH_ID", "SEM_INSTRUMENT_NAME",
            "SEM_EXPIRY_DATE", "SEM_STRIKE_PRICE", "SEM_OPTION_TYPE",
        ]
        rename = {
            "SEM_TRADING_SYMBOL":   "Symbol",
            "SEM_SMST_SECURITY_ID": "Security_ID",
            "SEM_EXM_EXCH_ID":      "Segment",
            "SEM_INSTRUMENT_NAME":  "Instrument",
            "SEM_EXPIRY_DATE":      "Expiry",
            "SEM_STRIKE_PRICE":     "Strike",
            "SEM_OPTION_TYPE":      "Type",
        }
        rows = [
            {rename.get(c, c): str(r.get(c, "")) for c in cols}
            for r in results
        ]
        return f"**Search results for '{query}':**\n" + records_to_table(rows)
    except Exception as exc:
        logger.error("search_instrument(%s): %s", query, exc)
        return error_msg("search_instrument", exc)
