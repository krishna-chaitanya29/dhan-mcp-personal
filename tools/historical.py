"""
Historical data tools: daily candles, intraday candles, expired option data.

SDK methods (dhanhq v2.1.0):
  historical_daily_data(security_id, exchange_segment, instrument_type,
                        from_date, to_date, expiry_code=0)
  intraday_minute_data(security_id, exchange_segment, instrument_type,
                       from_date, to_date, interval=1)

Both return r['data'] = {'open':[], 'high':[], 'low':[], 'close':[],
                          'volume':[], 'timestamp':[]}
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import dhan_client
import instrument_master as im
from utils.formatters import candles_to_table, error_msg, fmt_number
from utils.rate_limiter import throttle
import config

logger = logging.getLogger(__name__)

# Accepted timeframe strings → intraday interval int (DAY handled separately)
_INTRADAY_INTERVALS: dict[str, int] = {
    "1": 1, "5": 5, "15": 15, "25": 25, "60": 60,
}
_VALID_TF = "1, 5, 15, 25, 60, DAY"

# Instrument type constants (what the SDK expects)
_SEGMENT_TO_ITYPE: dict[str, str] = {
    "NSE_EQ":  "EQUITY",
    "BSE_EQ":  "EQUITY",
    "NSE_FNO": "OPTIDX",   # default; caller can override for futures
    "BSE_FNO": "OPTIDX",
    "IDX_I":   "INDEX",
    "BSE_IDX": "INDEX",
    "MCX_COMM": "FUTCOM",
}


def _instrument_type_from_master(sym: str, segment: str) -> str:
    """Look up SEM_INSTRUMENT_NAME from instrument master for accurate type."""
    rec = im.lookup_symbol(sym)
    if rec:
        raw = str(rec.get("SEM_INSTRUMENT_NAME", "")).upper()
        if raw:
            return raw
    return _SEGMENT_TO_ITYPE.get(segment, "EQUITY")


def _parse_candles(data: dict) -> list[dict]:
    """Convert parallel lists from Dhan historical response into OHLCV dicts."""
    timestamps = data.get("timestamp", [])
    opens      = data.get("open", [])
    highs      = data.get("high", [])
    lows       = data.get("low", [])
    closes     = data.get("close", [])
    volumes    = data.get("volume", [])

    candles = []
    for i, ts in enumerate(timestamps):
        try:
            dt = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            dt = str(ts)
        candles.append({
            "timestamp": dt,
            "open":   fmt_number(opens[i]   if i < len(opens)   else ""),
            "high":   fmt_number(highs[i]   if i < len(highs)   else ""),
            "low":    fmt_number(lows[i]    if i < len(lows)    else ""),
            "close":  fmt_number(closes[i]  if i < len(closes)  else ""),
            "volume": fmt_number(volumes[i] if i < len(volumes) else "", 0),
        })
    return candles


def get_candles(
    symbol: str,
    timeframe: str,
    from_date: str,
    to_date: str,
) -> str:
    """
    Fetch historical OHLCV candles for any instrument.

    Args:
        symbol:    Trading symbol (e.g. "NIFTY", "RELIANCE").
        timeframe: "1", "5", "15", "25", "60" for intraday; "DAY" for daily.
        from_date: Start date "YYYY-MM-DD".
        to_date:   End date "YYYY-MM-DD".

    Note: Dhan intraday endpoint covers the last 5 trading days only.
    For older data use timeframe "DAY".
    """
    tf = timeframe.upper().strip()
    if tf not in _INTRADAY_INTERVALS and tf not in ("DAY", "D"):
        return f"Invalid timeframe '{timeframe}'. Valid: {_VALID_TF}"

    try:
        throttle("historical", config.DEFAULT_RATE_LIMIT)
        sec_id, segment = im.resolve_to_security_id(symbol)
        itype  = _instrument_type_from_master(symbol, segment)
        client = dhan_client.get_dhan()

        if tf in ("DAY", "D"):
            resp = client.historical_daily_data(
                security_id=sec_id,
                exchange_segment=segment,
                instrument_type=itype,
                from_date=from_date,
                to_date=to_date,
                expiry_code=0,
            )
        else:
            resp = client.intraday_minute_data(
                security_id=sec_id,
                exchange_segment=segment,
                instrument_type=itype,
                from_date=from_date,
                to_date=to_date,
                interval=_INTRADAY_INTERVALS[tf],
            )

        data = resp.get("data", {})
        if isinstance(data, dict) and "open" in data:
            candles = _parse_candles(data)
        else:
            candles = []

        if not candles:
            return f"No candle data returned for {symbol} ({from_date} → {to_date})."

        header = (
            f"**{symbol}** {timeframe} candles "
            f"({from_date} → {to_date}) — {len(candles)} bars\n"
        )
        return header + candles_to_table(candles)
    except Exception as exc:
        logger.error("get_candles(%s, %s): %s", symbol, timeframe, exc)
        return error_msg("get_candles", exc)


def get_recent_candles(symbol: str, timeframe: str, count: int = 50) -> str:
    """
    Fetch the most recent N candles for any instrument.

    Args:
        symbol:    Trading symbol (e.g. "NIFTY", "RELIANCE").
        timeframe: "1", "5", "15", "25", "60", or "DAY".
        count:     Number of recent candles to return (default 50).

    Automatically computes an appropriate from_date based on timeframe.
    Intraday data is limited to the last 5 trading days by Dhan's API.
    """
    today = datetime.today()
    tf = timeframe.upper().strip()

    if tf in ("DAY", "D"):
        lookback_days = count + 30  # buffer for weekends/holidays
    else:
        mins_per_bar  = _INTRADAY_INTERVALS.get(tf, 60)
        trading_mins  = 375
        days_needed   = max(1, (count * mins_per_bar) // trading_mins + 5)
        lookback_days = min(days_needed, 5)  # Dhan caps intraday at 5 days

    from_date = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    to_date   = today.strftime("%Y-%m-%d")
    return get_candles(symbol, timeframe, from_date, to_date)


def get_expired_option_data(
    underlying: str,
    expiry_date: str,
    strike: int,
    option_type: str,
    timeframe: str,
) -> str:
    """
    Fetch historical candle data for a specific (possibly expired) option contract.

    Args:
        underlying:  Index or stock (e.g. "NIFTY", "BANKNIFTY").
        expiry_date: Expiry date "YYYY-MM-DD".
        strike:      Strike price as integer (e.g. 25000).
        option_type: "CE" or "PE".
        timeframe:   "1", "5", "15", "25", "60", or "DAY".

    Useful for reviewing how a specific strike behaved on or before expiry day.
    """
    option_type = option_type.upper()
    if option_type not in ("CE", "PE"):
        return "option_type must be 'CE' or 'PE'."

    try:
        throttle("historical", config.DEFAULT_RATE_LIMIT)
        # Look up the exact contract in the instrument master
        contracts = im.get_option_instruments(underlying, expiry_date, option_type)
        if contracts.empty:
            # Try stripping the timestamp if present in the CSV
            expiry_prefix = expiry_date[:10]
            contracts = im.get_option_instruments(underlying, expiry_prefix, option_type)

        if contracts.empty:
            return (
                f"No contracts found for {underlying} {expiry_date} "
                f"{strike} {option_type}. "
                "Check expiry date format (YYYY-MM-DD) and run search_instrument() "
                "to verify the symbol exists."
            )

        contracts = contracts.copy()
        contracts["SEM_STRIKE_PRICE"] = contracts["SEM_STRIKE_PRICE"].astype(float)
        closest = contracts.iloc[
            (contracts["SEM_STRIKE_PRICE"] - strike).abs().argsort()[:1]
        ]
        row          = closest.iloc[0]
        sec_id       = str(row["SEM_SMST_SECURITY_ID"])
        segment      = str(row["SEM_EXM_EXCH_ID"])
        actual_strike = int(row["SEM_STRIKE_PRICE"])
        itype        = str(row.get("SEM_INSTRUMENT_NAME", "OPTIDX"))

        # For expired options use daily data; for recent ones use intraday
        tf = timeframe.upper().strip()
        client = dhan_client.get_dhan()

        if tf in ("DAY", "D"):
            resp = client.historical_daily_data(
                security_id=sec_id,
                exchange_segment=segment,
                instrument_type=itype,
                from_date=expiry_date[:10],
                to_date=expiry_date[:10],
                expiry_code=0,
            )
        else:
            resp = client.intraday_minute_data(
                security_id=sec_id,
                exchange_segment=segment,
                instrument_type=itype,
                from_date=expiry_date[:10],
                to_date=expiry_date[:10],
                interval=_INTRADAY_INTERVALS.get(tf, 5),
            )

        data = resp.get("data", {})
        candles = _parse_candles(data) if isinstance(data, dict) and "open" in data else []
        if not candles:
            return (
                f"No candle data for {underlying} {actual_strike} {option_type} "
                f"on {expiry_date}. The contract may be too old for intraday data."
            )

        label = f"{underlying} {actual_strike} {option_type} exp:{expiry_date}"
        header = f"**{label}** {timeframe} candles — {len(candles)} bars\n"
        return header + candles_to_table(candles)
    except Exception as exc:
        logger.error("get_expired_option_data: %s", exc)
        return error_msg("get_expired_option_data", exc)
