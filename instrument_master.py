"""
Instrument master loader: downloads Dhan's compact CSV, caches locally,
and provides O(1) symbol → security_id lookup.
"""

from __future__ import annotations

import io
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

import config

logger = logging.getLogger(__name__)

# In-memory state
_df: Optional[pd.DataFrame] = None
_symbol_map: dict[str, dict] = {}   # "NIFTY" → {security_id, segment, ...}
_ticker_map: dict[str, dict] = {}   # "NIFTY25000CE" → same
_is_read_only_fs: bool = False      # True if filesystem is read-only
_last_load_time: float = 0.0        # Track when we last loaded data


# ---------------------------------------------------------------------------
# Load / refresh
# ---------------------------------------------------------------------------

def _cache_is_fresh() -> bool:
    """Check if cached CSV file exists and is within TTL."""
    if not os.path.exists(config.INSTRUMENT_MASTER_CSV):
        return False
    if not os.path.exists(config.INSTRUMENT_MASTER_TIMESTAMP):
        return False
    try:
        with open(config.INSTRUMENT_MASTER_TIMESTAMP) as f:
            ts = float(f.read().strip())
        age_hours = (time.time() - ts) / 3600
        return age_hours < config.INSTRUMENT_CACHE_TTL_HOURS
    except Exception as e:
        logger.warning("Cache freshness check failed: %s", e)
        return False


def _try_write_cache(csv_path: str, timestamp_path: str, csv_content: bytes, ts: float) -> bool:
    """Attempt to write cache files. Return True if successful, False if read-only."""
    global _is_read_only_fs
    try:
        with open(csv_path, "wb") as f:
            f.write(csv_content)
        with open(timestamp_path, "w") as f:
            f.write(str(ts))
        logger.info("Cache written to %s", csv_path)
        return True
    except (PermissionError, OSError) as e:
        logger.warning(
            "Filesystem is read-only or cache write failed: %s | "
            "Will use in-memory cache for this session", e
        )
        _is_read_only_fs = True
        return False


def _download_csv() -> pd.DataFrame:
    """Download instrument master CSV. Cache if possible, otherwise use in-memory."""
    logger.info("Downloading instrument master from %s", config.INSTRUMENT_MASTER_URL)
    resp = requests.get(config.INSTRUMENT_MASTER_URL, timeout=30)
    resp.raise_for_status()
    
    # Try to cache to disk
    _try_write_cache(
        config.INSTRUMENT_MASTER_CSV,
        config.INSTRUMENT_MASTER_TIMESTAMP,
        resp.content,
        time.time()
    )
    
    # Always load from memory (whether cached or not)
    return pd.read_csv(io.StringIO(resp.text), low_memory=False)


def _load_from_cache() -> pd.DataFrame:
    logger.info("Loading instrument master from cache")
    return pd.read_csv(config.INSTRUMENT_MASTER_CSV, low_memory=False)


def _build_maps(df: pd.DataFrame) -> None:
    global _symbol_map, _ticker_map
    _symbol_map = {}
    _ticker_map = {}

    for _, row in df.iterrows():
        rec = row.to_dict()
        sym = str(rec.get("SEM_TRADING_SYMBOL", "") or "").strip()
        custom = str(rec.get("SEM_CUSTOM_SYMBOL", "") or "").strip()
        if sym:
            _symbol_map[sym.upper()] = rec
        if custom and custom != sym:
            _symbol_map[custom.upper()] = rec

    logger.info("Instrument master: %d symbols indexed", len(_symbol_map))


def load_instrument_master(force: bool = False) -> pd.DataFrame:
    """Load (or refresh) the instrument master CSV into memory."""
    global _df, _last_load_time
    
    # If already loaded and not forced, check cache freshness
    if _df is not None and not force:
        # In-memory cache is always valid in this session
        if _is_read_only_fs or time.time() - _last_load_time < 3600:
            return _df
    
    try:
        if force or not _cache_is_fresh():
            _df = _download_csv()
        else:
            _df = _load_from_cache()
    except Exception as e:
        logger.error("Failed to load instrument master: %s", e)
        if _df is None:
            raise RuntimeError(
                f"Cannot load instrument master: {e}. "
                "Ensure internet connection and Dhan servers are accessible."
            )
        # Fall back to existing in-memory data
        logger.warning("Using stale in-memory cache due to load failure")
    
    _build_maps(_df)
    _last_load_time = time.time()
    return _df


def refresh_instrument_master() -> str:
    """Force-download the latest instrument master CSV and rebuild lookup maps."""
    try:
        load_instrument_master(force=True)
        msg = (
            f"✅ Instrument master refreshed: {len(_symbol_map):,} symbols loaded "
            f"at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
        )
        if _is_read_only_fs:
            msg += (
                "\n⚠️  Filesystem is read-only. Cache is in-memory only "
                "(will reset on server restart)."
            )
        return msg
    except Exception as e:
        error_msg = (
            f"❌ Failed to refresh: {e}. "
            f"Current cache: {len(_symbol_map):,} symbols in memory."
        )
        logger.error("refresh_instrument_master: %s", error_msg)
        return error_msg


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def lookup_symbol(symbol: str) -> Optional[dict]:
    """Return instrument record for an exact symbol (case-insensitive)."""
    if not _symbol_map:
        load_instrument_master()
    return _symbol_map.get(symbol.upper())


def search_instruments(query: str, max_results: int = 20) -> list[dict]:
    """Full-text search across trading symbol and custom symbol fields."""
    if _df is None:
        load_instrument_master()
    q = query.upper()
    mask = (
        _df["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.contains(q, na=False)
        | _df["SEM_CUSTOM_SYMBOL"].astype(str).str.upper().str.contains(q, na=False)
        | _df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().str.contains(q, na=False)
    )
    results = _df[mask].head(max_results)
    return results.to_dict("records")


_SEGMENT_MAP: dict[tuple[str, str], str] = {
    # (CSV exchange, CSV segment code) → Dhan API exchange_segment string
    ("NSE", "I"): "IDX_I",
    ("NSE", "E"): "NSE_EQ",
    ("NSE", "D"): "NSE_FNO",
    ("NSE", "C"): "NSE_EQ",   # currency
    ("NSE", "M"): "NSE_FNO",
    ("BSE", "I"): "BSE_EQ",   # BSE index
    ("BSE", "E"): "BSE_EQ",
    ("BSE", "D"): "BSE_FNO",
    ("BSE", "C"): "BSE_EQ",
    ("MCX", "M"): "MCX_COMM",
}


def _api_segment(rec: dict) -> str:
    """Map instrument master columns to the Dhan API exchange_segment string."""
    exch = str(rec.get("SEM_EXM_EXCH_ID", "")).upper()
    seg  = str(rec.get("SEM_SEGMENT", "")).upper()
    return _SEGMENT_MAP.get((exch, seg), f"{exch}_EQ")


def resolve_to_security_id(symbol: str) -> tuple[str, str]:
    """
    Resolve a symbol string to (security_id, api_exchange_segment).

    The returned segment uses Dhan API naming (e.g. NSE_EQ, IDX_I, NSE_FNO).
    Raises ValueError if not found.
    """
    rec = lookup_symbol(symbol)
    if rec is None:
        raise ValueError(
            f"Symbol '{symbol}' not found in instrument master. "
            "Try search_instrument() to find the correct symbol."
        )
    return str(rec["SEM_SMST_SECURITY_ID"]), _api_segment(rec)


def get_option_instruments(
    underlying: str,
    expiry_date: str,
    option_type: Optional[str] = None,
) -> pd.DataFrame:
    """
    Return all option contracts for an underlying + expiry.

    Args:
        underlying: e.g. "NIFTY", "BANKNIFTY"
        expiry_date: "YYYY-MM-DD"
        option_type: "CE" or "PE" or None for both
    """
    if _df is None:
        load_instrument_master()

    mask = (
        (_df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().isin(["OPTIDX", "OPTSTK"]))
        & (_df["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.startswith(underlying.upper()))
        & (_df["SEM_EXPIRY_DATE"].astype(str) == expiry_date)
    )
    sub = _df[mask].copy()
    if option_type:
        sub = sub[sub["SEM_OPTION_TYPE"].astype(str).str.upper() == option_type.upper()]
    return sub


def get_expiry_dates(underlying: str) -> list[str]:
    """Return sorted list of upcoming expiry dates for an underlying."""
    if _df is None:
        load_instrument_master()

    today = datetime.today().strftime("%Y-%m-%d")
    mask = (
        (_df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().isin(["OPTIDX", "OPTSTK"]))
        & (_df["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.startswith(underlying.upper()))
        & (_df["SEM_EXPIRY_DATE"].astype(str) >= today)
    )
    dates = sorted(_df[mask]["SEM_EXPIRY_DATE"].dropna().unique().tolist())
    return dates
