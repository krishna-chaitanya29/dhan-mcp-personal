"""Utilities to format pandas DataFrames and dicts into LLM-friendly text."""

from __future__ import annotations

from typing import Any


def fmt_number(val: Any, decimals: int = 2) -> str:
    try:
        return f"{float(val):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(val)


def fmt_int(val: Any) -> str:
    try:
        return f"{int(float(val)):,}"
    except (TypeError, ValueError):
        return str(val)


def dict_to_table(data: dict, title: str = "") -> str:
    """Render a flat dict as a two-column markdown table."""
    lines = []
    if title:
        lines.append(f"### {title}")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    for k, v in data.items():
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def records_to_table(records: list[dict], columns: list[str] | None = None) -> str:
    """Render a list of dicts as a markdown table."""
    if not records:
        return "_No data_"
    cols = columns or list(records[0].keys())
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "|" + "|".join("-------" for _ in cols) + "|"
    rows = []
    for rec in records:
        row = "| " + " | ".join(str(rec.get(c, "")) for c in cols) + " |"
        rows.append(row)
    return "\n".join([header, sep] + rows)


def option_chain_to_table(chain_rows: list[dict]) -> str:
    """Format option chain rows into a compact markdown table."""
    cols = ["Strike", "CE_LTP", "CE_OI", "CE_OI_Chg", "CE_Vol", "CE_IV",
            "PE_LTP", "PE_OI", "PE_OI_Chg", "PE_Vol", "PE_IV"]
    return records_to_table(chain_rows, cols)


def candles_to_table(candles: list[dict], max_rows: int = 50) -> str:
    """Format OHLCV candles as a markdown table, capped at max_rows."""
    if not candles:
        return "_No candle data_"
    truncated = candles[-max_rows:]
    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    return records_to_table(truncated, [c for c in cols if c in truncated[0]])


def error_msg(context: str, exc: Exception) -> str:
    return f"**Error** [{context}]: {exc}"
