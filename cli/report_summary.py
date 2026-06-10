"""Build the summary sidecar JSON written alongside the consolidated report.

The summary exposes a run's key decision data (rating, trader action,
entry/stop prices, price target, summary, thesis, etc.) as machine-readable
metadata in a standalone ``<ticker>_<date>_summary.json`` file.

Values are parsed out of the deterministic markdown the decision agents already
render -- see ``render_trader_proposal`` and ``render_pm_decision`` in
:mod:`tradingagents.agents.schemas`.  Any value we cannot find is simply
omitted: the dict never invents data.  This keeps the change localised to the
report writer (no agent/state changes) and works uniformly whether an agent
used structured output or the free-text fallback.
"""

from __future__ import annotations

import re
from typing import Optional, Union

from tradingagents.agents.utils.rating import parse_rating


# Tolerates the optional ``**`` bold wrappers and BUY/SELL/HOLD in any case.
_FINAL_PROPOSAL_RE = re.compile(
    r"FINAL TRANSACTION PROPOSAL:\s*\*{0,2}(BUY|SELL|HOLD)\*{0,2}",
    re.IGNORECASE,
)


def _field(markdown: str, label: str) -> Optional[str]:
    """Return the single-line value after a ``**Label**:`` marker, or ``None``."""
    if not markdown:
        return None
    pattern = re.compile(
        r"^\s*\*{0,2}" + re.escape(label) + r"\*{0,2}\s*:\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(markdown)
    if not m:
        return None
    value = m.group(1).strip().strip("*").strip("`").strip()
    return value or None


def _block(markdown: str, label: str) -> Optional[str]:
    """Return the (possibly multi-line) value after a ``**Label**:`` marker."""
    if not markdown:
        return None
    pattern = re.compile(
        r"\*{0,2}" + re.escape(label) + r"\*{0,2}\s*:\s*(.*?)"
        r"(?=\n\s*\*{0,2}[A-Z][^\n*]*\*{0,2}\s*:|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(markdown)
    if not m:
        return None
    value = " ".join(m.group(1).split())
    return value or None


def _num(value: Optional[str]) -> Optional[Union[int, float]]:
    """Coerce a string to a plain number, stripping ``$`` and thousands separators."""
    if value is None:
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not m:
        return None
    number = float(m.group(0))
    return int(number) if number.is_integer() else number


def _final_proposal(markdown: str) -> Optional[str]:
    """Return BUY/SELL/HOLD from the trailing FINAL TRANSACTION PROPOSAL line."""
    if not markdown:
        return None
    m = _FINAL_PROPOSAL_RE.search(markdown)
    return m.group(1).upper() if m else None


_TRANCHE_ROW_RE = re.compile(r"^\|(.+)\|\s*$", re.MULTILINE)


def _parse_tranches(markdown: str) -> Optional[list[dict]]:
    """Extract tranche rows from the **Tranches**: markdown table, or None.

    Accepts both the four-column layout (``Price | Price High | Allocation |
    Note``) and the legacy three-column layout (``Price | Allocation | Note``).
    """
    if not markdown:
        return None
    m = re.search(
        r"\*{0,2}Tranches\*{0,2}\s*:\s*\n(.*?)(?=\n\s*(?:FINAL|\*{0,2}[A-Z])|\Z)",
        markdown,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    block = m.group(1)
    rows = []
    has_price_high_col: Optional[bool] = None
    for row in _TRANCHE_ROW_RE.finditer(block):
        cells = [c.strip() for c in row.group(1).split("|")]
        if not cells:
            continue
        first = cells[0].lower()
        if first in ("price", "---", "") or re.match(r"^[-\s]+$", cells[0]):
            if first == "price":
                has_price_high_col = len(cells) >= 4 and cells[1].lower() in (
                    "price high",
                    "pricehigh",
                    "price_high",
                )
            continue
        if has_price_high_col is None:
            has_price_high_col = len(cells) >= 4
        if has_price_high_col:
            price_str, price_high_str, weight, note = (
                cells[0],
                cells[1] if len(cells) > 1 else "",
                cells[2] if len(cells) > 2 else "",
                cells[3] if len(cells) > 3 else "",
            )
        else:
            price_str, price_high_str, weight, note = (
                cells[0],
                "",
                cells[1] if len(cells) > 1 else "",
                cells[2] if len(cells) > 2 else "",
            )
        price = _num(price_str)
        price_high = _num(price_high_str) if price_high_str else None
        entry: dict = {}
        if price is not None:
            entry["price"] = price
        if price_high is not None:
            entry["price_high"] = price_high
        if weight:
            entry["weight"] = weight
        if note:
            entry["note"] = note
        if entry:
            rows.append(entry)
    return rows or None


def build_summary(
    final_state: dict,
    ticker: str,
    report_date: Optional[str] = None,
    report_close: Optional[Union[int, float]] = None,
    generated_at: Optional[str] = None,
) -> dict:
    """Build the summary dict for the sidecar JSON file.

    Only keys with a value are included; missing data is omitted rather than
    invented.  ``report_close`` is the close price as of ``report_date`` when
    the caller supplies it (see ``get_latest_close``).  ``tranches`` is parsed
    from the trader markdown table when present; omitted otherwise.
    """
    trader_md = final_state.get("trader_investment_plan") or ""
    pm_md = final_state.get("final_trade_decision") or ""

    ticker_up = (ticker or "").upper()

    company = final_state.get("company_of_interest")
    if company and company.strip().upper() == ticker_up:
        company = None

    # parse_rating defaults to "Hold" on empty text, so only emit a rating when
    # the Portfolio Manager actually produced a decision.
    rating = parse_rating(pm_md) if pm_md else None

    action = _field(trader_md, "Action")
    entry_price = _num(_field(trader_md, "Entry Price"))
    stop_loss = _num(_field(trader_md, "Stop Loss"))
    stop_loss_basis_raw = _field(trader_md, "Stop Loss Basis")
    stop_loss_basis: Optional[str] = None
    if stop_loss_basis_raw:
        normalised = stop_loss_basis_raw.strip().lower()
        if normalised in ("entry", "current", "close"):
            stop_loss_basis = normalised
    avoid_above = _num(_field(trader_md, "Avoid Above"))
    position_sizing = _field(trader_md, "Position Sizing")

    price_target = _num(_field(pm_md, "Price Target"))
    time_horizon = _field(pm_md, "Time Horizon")
    executive_summary = _block(pm_md, "Executive Summary")
    thesis = _block(pm_md, "Investment Thesis")

    final_proposal = _final_proposal(trader_md)
    if not final_proposal and action:
        final_proposal = action.upper()

    tranches = _parse_tranches(trader_md)
    if tranches and final_proposal != "BUY":
        tranches = None

    data: dict = {}

    def set_if(key: str, value) -> None:
        if value not in (None, ""):
            data[key] = value

    set_if("ticker", ticker_up)
    set_if("company", company)
    set_if("report_date", report_date)
    set_if("generated_at", generated_at)
    set_if("report_close", report_close)
    set_if("rating", rating)
    set_if("action", action)
    set_if("entry_price", entry_price)
    set_if("stop_loss", stop_loss)
    set_if("stop_loss_basis", stop_loss_basis)
    set_if("avoid_above", avoid_above)
    set_if("position_sizing", position_sizing)
    set_if("tranches", tranches)
    set_if("price_target", price_target)
    set_if("time_horizon", time_horizon)
    set_if("summary", executive_summary)
    set_if("thesis", thesis)
    set_if("final_proposal", final_proposal)

    return data
