"""
Derived analytics: PCR, max pain, OI buildup, market summary.
All computed from option chain data (option_chain SDK call).

Row format from _fetch_chain_data():
  {'Strike', '_strike_float', 'CE_LTP', 'CE_OI', 'CE_PrevOI', 'CE_Vol',
   'CE_IV', 'CE_Delta', 'PE_LTP', 'PE_OI', 'PE_PrevOI', 'PE_Vol', 'PE_IV', ...}
"""

from __future__ import annotations

import logging

import dhan_client
from utils.formatters import fmt_number, records_to_table, error_msg
from utils.rate_limiter import throttle
import config

logger = logging.getLogger(__name__)


def _fetch_chain_data(underlying: str, expiry: str) -> tuple[list[dict], float, str]:
    """
    Fetch parsed option chain rows, spot price, and resolved expiry date.
    Returns (rows, spot, expiry_date) where rows come from _parse_oc().
    """
    from tools.option_chain import _resolve_expiry, _resolve_underlying, _parse_oc
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
        raise RuntimeError(
            f"Dhan API error for option_chain: {resp.get('remarks', resp)}"
        )
    outer = resp.get("data", {})
    inner = outer.get("data", outer) if isinstance(outer, dict) else {}
    if not isinstance(inner, dict):
        raise RuntimeError(f"Unexpected option_chain response shape: {type(inner)}")
    spot  = float(inner.get("last_price", 0))
    rows  = _parse_oc(inner.get("oc", {}))
    return rows, spot, expiry_date


def compute_pcr(underlying: str, expiry: str = "nearest") -> str:
    """
    Compute Put-Call Ratio (PCR) for an underlying and expiry.

    Calculates OI-based and volume-based PCR across all strikes.
    PCR > 1.2 → bullish (heavy put writing).
    PCR < 0.7 → bearish (heavy call writing).

    Args:
        underlying: Index symbol (e.g. "NIFTY", "BANKNIFTY").
        expiry:     Expiry date "YYYY-MM-DD" or "nearest".
    """
    try:
        rows, spot, expiry_date = _fetch_chain_data(underlying, expiry)
        if not rows:
            return f"No data to compute PCR for {underlying} {expiry_date}."

        total_ce_oi  = sum(float(r["CE_OI"])  for r in rows)
        total_pe_oi  = sum(float(r["PE_OI"])  for r in rows)
        total_ce_vol = sum(float(r["CE_Vol"]) for r in rows)
        total_pe_vol = sum(float(r["PE_Vol"]) for r in rows)

        oi_pcr  = total_pe_oi  / total_ce_oi  if total_ce_oi  else 0
        vol_pcr = total_pe_vol / total_ce_vol if total_ce_vol else 0

        sentiment = (
            "Bullish (heavy put writing)"  if oi_pcr > 1.2
            else "Bearish (heavy call writing)" if oi_pcr < 0.7
            else "Neutral"
        )
        return (
            f"**PCR — {underlying.upper()} | Expiry: {expiry_date}**\n"
            f"OI-based PCR:     {fmt_number(oi_pcr, 3)}\n"
            f"Volume-based PCR: {fmt_number(vol_pcr, 3)}\n"
            f"Total CE OI:      {fmt_number(total_ce_oi, 0)}\n"
            f"Total PE OI:      {fmt_number(total_pe_oi, 0)}\n"
            f"Sentiment:        {sentiment}"
        )
    except Exception as exc:
        logger.error("compute_pcr(%s): %s", underlying, exc)
        return error_msg("compute_pcr", exc)


def compute_max_pain(underlying: str, expiry: str = "nearest") -> str:
    """
    Compute the Max Pain strike for an upcoming options expiry.

    Max Pain = the strike where total option buyer losses are maximised
    (i.e., option writer profit is maximised). Often acts as a price magnet
    near expiry.

    Args:
        underlying: Index symbol (e.g. "NIFTY", "BANKNIFTY").
        expiry:     Expiry date "YYYY-MM-DD" or "nearest".
    """
    try:
        rows, spot, expiry_date = _fetch_chain_data(underlying, expiry)
        if not rows:
            return f"No data to compute max pain for {underlying} {expiry_date}."

        strikes = [r["_strike_float"] for r in rows]

        def total_pain(candidate: float) -> float:
            total = 0.0
            for r in rows:
                s = r["_strike_float"]
                total += max(0.0, candidate - s) * float(r["CE_OI"])
                total += max(0.0, s - candidate) * float(r["PE_OI"])
            return total

        max_pain_s = min(strikes, key=total_pain)
        distance   = abs(max_pain_s - spot)
        direction  = "above" if max_pain_s > spot else "below"

        return (
            f"**Max Pain — {underlying.upper()} | Expiry: {expiry_date}**\n"
            f"Max Pain Strike: **{int(max_pain_s)}**\n"
            f"Current Spot:    {fmt_number(spot)}\n"
            f"Distance:        {fmt_number(distance)} pts ({direction} spot)"
        )
    except Exception as exc:
        logger.error("compute_max_pain(%s): %s", underlying, exc)
        return error_msg("compute_max_pain", exc)


def find_oi_buildup(
    underlying: str,
    expiry: str = "nearest",
    top_n: int = 5,
) -> str:
    """
    Find strikes with the highest OI and largest OI change for CE and PE.

    Top OI strikes → key support/resistance / pinning candidates.
    Top OI change strikes → fresh position building this session.

    Args:
        underlying: Index symbol (e.g. "NIFTY", "BANKNIFTY").
        expiry:     Expiry date "YYYY-MM-DD" or "nearest".
        top_n:      Number of top strikes per category (default 5).
    """
    try:
        rows, spot, expiry_date = _fetch_chain_data(underlying, expiry)
        if not rows:
            return f"No data for OI buildup on {underlying} {expiry_date}."

        # Compute OI change = current − previous
        for r in rows:
            r["CE_OI_Chg"] = float(r["CE_OI"]) - float(r["CE_PrevOI"])
            r["PE_OI_Chg"] = float(r["PE_OI"]) - float(r["PE_PrevOI"])

        def top_by(field: str, side: str, n: int) -> list[dict]:
            return sorted(rows, key=lambda r: float(r[field]), reverse=True)[:n]

        def fmt_side(lst: list[dict], oi_field: str, ltp_field: str, iv_field: str) -> list[dict]:
            return [{
                "Strike": r["Strike"],
                "OI":     fmt_number(r[oi_field], 0),
                "LTP":    fmt_number(r[ltp_field]),
                "IV%":    fmt_number(r[iv_field]),
            } for r in lst]

        out = [
            f"**OI Buildup — {underlying.upper()} | "
            f"Expiry: {expiry_date} | Spot: {fmt_number(spot)}**\n"
        ]
        out.append(f"### Top {top_n} CE strikes by OI (resistance levels)")
        out.append(records_to_table(fmt_side(top_by("CE_OI", "CE", top_n), "CE_OI", "CE_LTP", "CE_IV")))
        out.append(f"\n### Top {top_n} PE strikes by OI (support levels)")
        out.append(records_to_table(fmt_side(top_by("PE_OI", "PE", top_n), "PE_OI", "PE_LTP", "PE_IV")))
        out.append(f"\n### Top {top_n} CE strikes by OI change (fresh call writing)")
        out.append(records_to_table(fmt_side(top_by("CE_OI_Chg", "CE", top_n), "CE_OI_Chg", "CE_LTP", "CE_IV")))
        out.append(f"\n### Top {top_n} PE strikes by OI change (fresh put writing)")
        out.append(records_to_table(fmt_side(top_by("PE_OI_Chg", "PE", top_n), "PE_OI_Chg", "PE_LTP", "PE_IV")))
        return "\n".join(out)
    except Exception as exc:
        logger.error("find_oi_buildup(%s): %s", underlying, exc)
        return error_msg("find_oi_buildup", exc)


def get_market_summary(underlying: str = "NIFTY") -> str:
    """
    One-call market summary: spot, ATM, PCR, max pain, top OI strikes.

    Combines index spot, nearest expiry ATM, PCR, max pain, and top OI
    levels into a single formatted report. Designed for quick briefings.

    Args:
        underlying: Index to summarise (default "NIFTY"). Also works with
                    "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY".
    """
    try:
        from tools.option_chain import _nearest_expiry
        expiry_date = _nearest_expiry(underlying.upper())

        rows, spot, _ = _fetch_chain_data(underlying, expiry_date)
        if not rows or not spot:
            return f"Could not fetch data for {underlying}. Markets may be closed."

        # ATM
        atm_row = min(rows, key=lambda r: abs(r["_strike_float"] - spot))
        atm = atm_row["Strike"]

        # PCR
        total_ce_oi = sum(float(r["CE_OI"]) for r in rows)
        total_pe_oi = sum(float(r["PE_OI"]) for r in rows)
        oi_pcr = total_pe_oi / total_ce_oi if total_ce_oi else 0
        sentiment = (
            "Bullish" if oi_pcr > 1.2
            else "Bearish" if oi_pcr < 0.7
            else "Neutral"
        )

        # Max pain
        strikes = [r["_strike_float"] for r in rows]
        def total_pain(c: float) -> float:
            return sum(
                max(0.0, c - r["_strike_float"]) * float(r["CE_OI"]) +
                max(0.0, r["_strike_float"] - c) * float(r["PE_OI"])
                for r in rows
            )
        max_pain_s = int(min(strikes, key=total_pain))

        # Top 3 CE/PE OI strikes
        top_ce = sorted(rows, key=lambda r: float(r["CE_OI"]), reverse=True)[:3]
        top_pe = sorted(rows, key=lambda r: float(r["PE_OI"]), reverse=True)[:3]

        ce_label = ", ".join(
            f"{r['Strike']}({fmt_number(r['CE_OI'],0)} OI)" for r in top_ce
        )
        pe_label = ", ".join(
            f"{r['Strike']}({fmt_number(r['PE_OI'],0)} OI)" for r in top_pe
        )

        return (
            f"# {underlying.upper()} Market Summary — Expiry: {expiry_date}\n\n"
            f"**Spot:**       {fmt_number(spot)}\n"
            f"**ATM Strike:** {atm}\n"
            f"**PCR (OI):**   {fmt_number(oi_pcr, 3)} → {sentiment}\n"
            f"**Max Pain:**   {max_pain_s}\n\n"
            f"**Top CE OI (resistance):** {ce_label}\n"
            f"**Top PE OI (support):**    {pe_label}\n\n"
            f"**ATM CE:** LTP {fmt_number(atm_row['CE_LTP'])}  "
            f"IV {fmt_number(atm_row['CE_IV'])}%\n"
            f"**ATM PE:** LTP {fmt_number(atm_row['PE_LTP'])}  "
            f"IV {fmt_number(atm_row['PE_IV'])}%"
        )
    except Exception as exc:
        logger.error("get_market_summary(%s): %s", underlying, exc)
        return error_msg("get_market_summary", exc)
