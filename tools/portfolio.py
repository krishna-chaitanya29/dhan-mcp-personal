"""
Portfolio tools (READ-ONLY): holdings, positions, fund limits, order book, trade book.
No order placement, modification, or cancellation — ever.
"""

from __future__ import annotations

import logging

import dhan_client
from utils.formatters import records_to_table, dict_to_table, fmt_number, error_msg
from utils.rate_limiter import throttle
import config

logger = logging.getLogger(__name__)


def _extract_list(resp: dict) -> list[dict]:
    """Pull a list out of various Dhan response shapes."""
    if isinstance(resp, list):
        return resp
    data = resp.get("data", resp)
    if isinstance(data, list):
        return data
    return []


def get_holdings() -> str:
    """
    Get long-term equity holdings in your Dhan demat account.

    Returns instrument name, ISIN, quantity, average cost, current LTP,
    unrealised P&L, and day change for each holding.
    """
    try:
        throttle("portfolio", config.DEFAULT_RATE_LIMIT)
        resp = dhan_client.safe_call("get_holdings")
        items = _extract_list(resp)
        if not items:
            return "No holdings found."
        rows = []
        for h in items:
            rows.append({
                "Symbol":      h.get("tradingSymbol", ""),
                "ISIN":        h.get("isin", ""),
                "Qty":         fmt_number(h.get("totalQty", 0), 0),
                "Avg Cost":    fmt_number(h.get("avgCostPrice", 0)),
                "LTP":         fmt_number(h.get("lastTradedPrice", 0)),
                "Mkt Value":   fmt_number(h.get("totalMktValue", 0)),
                "Unrealised":  fmt_number(h.get("unrealizedProfit", 0)),
                "Day Chg%":    fmt_number(h.get("dayChange", 0)),
            })
        total_value = sum(float(h.get("totalMktValue", 0) or 0) for h in items)
        total_pnl   = sum(float(h.get("unrealizedProfit", 0) or 0) for h in items)
        summary = (
            f"**Holdings — {len(rows)} positions**  "
            f"Total Value: ₹{fmt_number(total_value)}  "
            f"Total Unrealised P&L: ₹{fmt_number(total_pnl)}\n"
        )
        return summary + records_to_table(rows)
    except Exception as exc:
        logger.error("get_holdings: %s", exc)
        return error_msg("get_holdings", exc)


def get_positions() -> str:
    """
    Get today's open intraday and delivery positions.

    Shows symbol, quantity, average price, LTP, realised and unrealised P&L.
    Covers both intraday (MIS) and carry-forward (CNC/NRML) positions.
    """
    try:
        throttle("portfolio", config.DEFAULT_RATE_LIMIT)
        resp = dhan_client.safe_call("get_positions")
        items = _extract_list(resp)
        if not items:
            return "No open positions today."
        rows = []
        for p in items:
            rows.append({
                "Symbol":     p.get("tradingSymbol", ""),
                "Product":    p.get("productType", ""),
                "Buy Qty":    fmt_number(p.get("buyQty", 0), 0),
                "Sell Qty":   fmt_number(p.get("sellQty", 0), 0),
                "Net Qty":    fmt_number(p.get("netQty", 0), 0),
                "Avg Price":  fmt_number(p.get("costPrice", p.get("avgCostPrice", 0))),
                "LTP":        fmt_number(p.get("lastTradedPrice", 0)),
                "Realised":   fmt_number(p.get("realizedProfit", 0)),
                "Unrealised": fmt_number(p.get("unrealizedProfit", 0)),
            })
        total_real   = sum(float(p.get("realizedProfit", 0) or 0) for p in items)
        total_unreal = sum(float(p.get("unrealizedProfit", 0) or 0) for p in items)
        summary = (
            f"**Positions — {len(rows)} open**  "
            f"Realised: ₹{fmt_number(total_real)}  "
            f"Unrealised: ₹{fmt_number(total_unreal)}\n"
        )
        return summary + records_to_table(rows)
    except Exception as exc:
        logger.error("get_positions: %s", exc)
        return error_msg("get_positions", exc)


def get_fund_limits() -> str:
    """
    Get available margin, used margin, and cash balance from your Dhan account.

    Shows: opening balance, available balance, used margin (intraday + delivery),
    SPAN margin, exposure margin, and total collateral.
    """
    try:
        throttle("portfolio", config.DEFAULT_RATE_LIMIT)
        resp = dhan_client.safe_call("get_fund_limits")
        data = resp.get("data", resp) if isinstance(resp, dict) else resp
        if not data:
            return "Fund limit data unavailable."
        fields = {
            "Available Balance":    data.get("availabelBalance", data.get("availableBalance", "N/A")),
            "Opening Balance":      data.get("openingBalance", "N/A"),
            "Total Collateral":     data.get("collateralAmount", "N/A"),
            "Used Margin (Intra)":  data.get("utilizedAmount", {}).get("tradingMargin", "N/A")
                                    if isinstance(data.get("utilizedAmount"), dict) else data.get("utilizedMargin", "N/A"),
            "SPAN Margin":          data.get("utilizedAmount", {}).get("spanMargin", "N/A")
                                    if isinstance(data.get("utilizedAmount"), dict) else "N/A",
            "Exposure Margin":      data.get("utilizedAmount", {}).get("exposureMargin", "N/A")
                                    if isinstance(data.get("utilizedAmount"), dict) else "N/A",
            "Withdrawal Amount":    data.get("withdrawableBalance", "N/A"),
        }
        return dict_to_table(
            {k: f"₹{fmt_number(v)}" if v not in ("N/A", None) else "N/A"
             for k, v in fields.items()},
            title="Fund Limits",
        )
    except Exception as exc:
        logger.error("get_fund_limits: %s", exc)
        return error_msg("get_fund_limits", exc)


def get_order_book() -> str:
    """
    View today's order book — status only, no order actions available.

    Shows all orders placed today with their status (PENDING, TRADED,
    CANCELLED, REJECTED) along with symbol, quantity, price, and order type.
    This server is READ-ONLY: place/modify/cancel operations are not supported.
    """
    try:
        throttle("portfolio", config.DEFAULT_RATE_LIMIT)
        resp = dhan_client.safe_call("get_order_list")
        items = _extract_list(resp)
        if not items:
            return "No orders today."
        rows = []
        for o in items:
            rows.append({
                "Order ID":  o.get("orderId", ""),
                "Symbol":    o.get("tradingSymbol", ""),
                "Type":      o.get("orderType", ""),
                "Side":      o.get("transactionType", ""),
                "Qty":       fmt_number(o.get("quantity", 0), 0),
                "Price":     fmt_number(o.get("price", 0)),
                "Status":    o.get("orderStatus", ""),
                "Time":      o.get("createTime", ""),
            })
        return f"**Order Book — {len(rows)} orders today**\n" + records_to_table(rows)
    except Exception as exc:
        logger.error("get_order_book: %s", exc)
        return error_msg("get_order_book", exc)


def get_trade_book() -> str:
    """
    View today's executed trades.

    Returns filled trades with symbol, quantity, trade price, trade time,
    and order ID. Read-only — no modification actions available.
    """
    try:
        throttle("portfolio", config.DEFAULT_RATE_LIMIT)
        resp = dhan_client.safe_call("get_trade_book")
        items = _extract_list(resp)
        if not items:
            return "No executed trades today."
        rows = []
        for t in items:
            rows.append({
                "Order ID":    t.get("orderId", ""),
                "Symbol":      t.get("tradingSymbol", ""),
                "Side":        t.get("transactionType", ""),
                "Qty":         fmt_number(t.get("tradedQuantity", t.get("quantity", 0)), 0),
                "Trade Price": fmt_number(t.get("tradedPrice", t.get("price", 0))),
                "Trade Time":  t.get("updateTime", t.get("createTime", "")),
            })
        return f"**Trade Book — {len(rows)} trades today**\n" + records_to_table(rows)
    except Exception as exc:
        logger.error("get_trade_book: %s", exc)
        return error_msg("get_trade_book", exc)
