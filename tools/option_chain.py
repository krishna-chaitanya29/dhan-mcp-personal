"""
Option chain tools: expiries, full chain, ATM strike.
Rate-limited to 1 request per 3 seconds per Dhan API policy.

SDK method: option_chain(under_security_id: int, under_exchange_segment: str, expiry: str)
Response:   r['data']['data']['oc'] → {strike_str: {'ce': {...}, 'pe': {...}}}
            r['data']['data']['last_price'] → underlying spot price
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import dhan_client
import instrument_master as im
from utils.formatters import records_to_table, fmt_number, error_msg
from utils.rate_limiter import throttle
import config

logger = logging.getLogger(__name__)

# Index → (security_id int, exchange_segment str) for option_chain API
_UNDERLYING: dict[str, tuple[int, str]] = {
    "NIFTY":      (13,  "IDX_I"),
    "BANKNIFTY":  (25,  "IDX_I"),
    "FINNIFTY":   (27,  "IDX_I"),
    "MIDCPNIFTY": (442, "IDX_I"),
    "SENSEX":     (51,  "BSE_EQ"),
    "BANKEX":     (421, "BSE_EQ"),
}


def _nearest_expiry(underlying: str) -> str:
    """
    Return nearest upcoming expiry via SDK expiry_list.
    Falls back to next Tuesday (NIFTY SEBI rule) if SDK call fails.
    """
    try:
        ul = underlying.upper()
        sec_id, segment = _resolve_underlying(ul)
        client = dhan_client.get_dhan()
        resp = client.expiry_list(under_security_id=sec_id, under_exchange_segment=segment)
        dates = resp.get("data", {}).get("data", [])
        today = date.today().isoformat()
        upcoming = [d for d in dates if d >= today]
        if upcoming:
            return upcoming[0]
    except Exception as e:
        logger.warning("expiry_list fallback: %s", e)

    # Fallback: next Tuesday
    today_d = date.today()
    days_ahead = (1 - today_d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (today_d + timedelta(days=days_ahead)).isoformat()


def _resolve_underlying(underlying: str) -> tuple[int, str]:
    """Return (security_id, segment) for a named underlying, or raise ValueError."""
    ul = underlying.upper()
    if ul in _UNDERLYING:
        return _UNDERLYING[ul]
    raise ValueError(
        f"Unknown underlying '{underlying}'. "
        f"Supported: {', '.join(_UNDERLYING)}. "
        "For stock options, use search_instrument() to find the security_id."
    )


def _resolve_expiry(underlying: str, expiry: str) -> str:
    if expiry.lower() == "nearest":
        return _nearest_expiry(underlying)
    return expiry


def _parse_oc(oc: dict) -> list[dict]:
    """Parse the 'oc' dict into a flat list of per-strike rows."""
    rows = []
    for strike_str, sides in oc.items():
        strike = float(strike_str)
        ce = sides.get("ce", {})
        pe = sides.get("pe", {})
        rows.append({
            "_strike_float": strike,
            "Strike":     int(strike),
            "CE_LTP":     ce.get("last_price", 0),
            "CE_OI":      ce.get("oi", 0),
            "CE_PrevOI":  ce.get("previous_oi", 0),
            "CE_Vol":     ce.get("volume", 0),
            "CE_IV":      ce.get("implied_volatility", 0),
            "CE_Delta":   ce.get("greeks", {}).get("delta", 0),
            "CE_Bid":     ce.get("top_bid_price", 0),
            "CE_Ask":     ce.get("top_ask_price", 0),
            "CE_SecID":   ce.get("security_id", ""),
            "PE_LTP":     pe.get("last_price", 0),
            "PE_OI":      pe.get("oi", 0),
            "PE_PrevOI":  pe.get("previous_oi", 0),
            "PE_Vol":     pe.get("volume", 0),
            "PE_IV":      pe.get("implied_volatility", 0),
            "PE_Delta":   pe.get("greeks", {}).get("delta", 0),
            "PE_Bid":     pe.get("top_bid_price", 0),
            "PE_Ask":     pe.get("top_ask_price", 0),
            "PE_SecID":   pe.get("security_id", ""),
        })
    return sorted(rows, key=lambda r: r["_strike_float"])


def get_option_expiries(underlying: str) -> str:
    """
    List all available option expiry dates for an index or stock.

    Args:
        underlying: Index name (e.g. "NIFTY", "BANKNIFTY", "FINNIFTY").

    Returns expiry dates sorted ascending, with the nearest labelled.
    """
    try:
        sec_id, segment = _resolve_underlying(underlying.upper())
        client = dhan_client.get_dhan()
        resp = client.expiry_list(under_security_id=sec_id, under_exchange_segment=segment)
        dates = resp.get("data", {}).get("data", [])
        if not dates:
            return f"No upcoming expiries returned for '{underlying}'."
        today = date.today().isoformat()
        upcoming = [d for d in dates if d >= today]
        lines = [f"**{underlying.upper()} Option Expiries:**"]
        for i, d in enumerate(upcoming):
            tag = " ← nearest" if i == 0 else ""
            lines.append(f"  {i+1}. {d}{tag}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_option_expiries(%s): %s", underlying, exc)
        return error_msg("get_option_expiries", exc)


def get_option_chain(
    underlying: str,
    expiry: str = "nearest",
    strikes_range: int = 10,
) -> str:
    """
    Fetch the full option chain for an index and expiry.

    Shows ±`strikes_range` strikes around ATM with LTP, OI, OI change,
    volume, IV, delta, and bid/ask for both CE and PE.

    Args:
        underlying:    Index (e.g. "NIFTY", "BANKNIFTY", "FINNIFTY").
        expiry:        Expiry date "YYYY-MM-DD" or "nearest" (default).
        strikes_range: Strikes above and below ATM to include (default 10).

    Rate-limited to 1 call per 3 seconds.
    """
    try:
        throttle("option_chain", config.OPTION_CHAIN_RATE_LIMIT)
        expiry_date = _resolve_expiry(underlying.upper(), expiry)
        sec_id, segment = _resolve_underlying(underlying.upper())
        client = dhan_client.get_dhan()

        resp = client.option_chain(
            under_security_id=sec_id,
            under_exchange_segment=segment,
            expiry=expiry_date,
        )
        if resp.get("status") != "success":
            return (
                f"Dhan API returned failure for {underlying} option chain. "
                f"This usually means a rate limit was hit — wait a few seconds and retry."
            )
        outer = resp.get("data", {})
        inner = outer.get("data", outer) if isinstance(outer, dict) else {}
        spot  = float(inner.get("last_price", 0)) if isinstance(inner, dict) else 0
        oc    = inner.get("oc", {}) if isinstance(inner, dict) else {}

        if not oc:
            return f"No option chain data for {underlying} expiry {expiry_date}."

        all_rows = _parse_oc(oc)
        all_strikes = [r["_strike_float"] for r in all_rows]

        if spot and all_strikes:
            atm = min(all_strikes, key=lambda s: abs(s - spot))
            atm_idx = all_strikes.index(atm)
            lo  = max(0, atm_idx - strikes_range)
            hi  = min(len(all_rows), atm_idx + strikes_range + 1)
            display = all_rows[lo:hi]
        else:
            atm = 0
            display = all_rows

        # OI change = current OI − previous OI
        for r in display:
            r["CE_OI_Chg"] = r["CE_OI"] - r["CE_PrevOI"]
            r["PE_OI_Chg"] = r["PE_OI"] - r["PE_PrevOI"]

        cols = ["Strike",
                "CE_LTP", "CE_OI", "CE_OI_Chg", "CE_Vol", "CE_IV", "CE_Delta",
                "PE_LTP", "PE_OI", "PE_OI_Chg", "PE_Vol", "PE_IV", "PE_Delta"]

        fmt_rows = []
        for r in display:
            fmt_rows.append({
                "Strike":     r["Strike"],
                "CE_LTP":     fmt_number(r["CE_LTP"]),
                "CE_OI":      fmt_number(r["CE_OI"], 0),
                "CE_OI_Chg":  fmt_number(r["CE_OI_Chg"], 0),
                "CE_Vol":     fmt_number(r["CE_Vol"], 0),
                "CE_IV":      fmt_number(r["CE_IV"]),
                "CE_Delta":   fmt_number(r["CE_Delta"], 3),
                "PE_LTP":     fmt_number(r["PE_LTP"]),
                "PE_OI":      fmt_number(r["PE_OI"], 0),
                "PE_OI_Chg":  fmt_number(r["PE_OI_Chg"], 0),
                "PE_Vol":     fmt_number(r["PE_Vol"], 0),
                "PE_IV":      fmt_number(r["PE_IV"]),
                "PE_Delta":   fmt_number(r["PE_Delta"], 3),
            })

        atm_label = f"  ATM ≈ {int(atm)}" if atm else ""
        header = (
            f"**{underlying.upper()} Option Chain — Expiry: {expiry_date}**  "
            f"Spot: {fmt_number(spot)}{atm_label}\n"
        )
        return header + records_to_table(fmt_rows, cols)
    except Exception as exc:
        logger.error("get_option_chain(%s, %s): %s", underlying, expiry, exc)
        return error_msg("get_option_chain", exc)


def get_atm_strike(underlying: str, expiry: str = "nearest") -> str:
    """
    Get the At-The-Money (ATM) strike for an underlying.

    Returns spot price, ATM strike, and the CE/PE premiums with IV at that strike.

    Args:
        underlying: Index symbol (e.g. "NIFTY", "BANKNIFTY").
        expiry:     Expiry date "YYYY-MM-DD" or "nearest".
    """
    try:
        throttle("option_chain", config.OPTION_CHAIN_RATE_LIMIT)
        expiry_date = _resolve_expiry(underlying.upper(), expiry)
        sec_id, segment = _resolve_underlying(underlying.upper())
        client = dhan_client.get_dhan()

        resp = client.option_chain(
            under_security_id=sec_id,
            under_exchange_segment=segment,
            expiry=expiry_date,
        )
        if resp.get("status") != "success":
            return (
                f"Dhan API rate limit hit for {underlying} option chain. "
                "Wait a few seconds and retry."
            )
        outer = resp.get("data", {})
        inner = outer.get("data", outer) if isinstance(outer, dict) else {}
        spot  = float(inner.get("last_price", 0)) if isinstance(inner, dict) else 0
        oc    = inner.get("oc", {}) if isinstance(inner, dict) else {}

        if not oc or not spot:
            return f"No data for {underlying} expiry {expiry_date}."

        all_rows = _parse_oc(oc)
        atm_row  = min(all_rows, key=lambda r: abs(r["_strike_float"] - spot))

        return (
            f"**{underlying.upper()} ATM — Expiry: {expiry_date}**\n"
            f"Spot:       {fmt_number(spot)}\n"
            f"ATM Strike: {atm_row['Strike']}\n"
            f"ATM CE  LTP: {fmt_number(atm_row['CE_LTP'])}  "
            f"IV: {fmt_number(atm_row['CE_IV'])}%  "
            f"Delta: {fmt_number(atm_row['CE_Delta'], 3)}\n"
            f"ATM PE  LTP: {fmt_number(atm_row['PE_LTP'])}  "
            f"IV: {fmt_number(atm_row['PE_IV'])}%  "
            f"Delta: {fmt_number(atm_row['PE_Delta'], 3)}"
        )
    except Exception as exc:
        logger.error("get_atm_strike(%s): %s", underlying, exc)
        return error_msg("get_atm_strike", exc)
