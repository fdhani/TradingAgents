"""Build the YAML front-matter block prepended to the consolidated report.

The front-matter exposes a run's key decision data (rating, trader action,
entry/stop prices, price target, summary, thesis, etc.) as machine-readable
metadata at the top of ``complete_report.md``.

Values are parsed out of the deterministic markdown the decision agents already
render -- see ``render_trader_proposal`` and ``render_pm_decision`` in
:mod:`tradingagents.agents.schemas`.  Any value we cannot find is simply
omitted: the block never invents data.  This keeps the change localised to the
report writer (no agent/state changes) and works uniformly whether an agent
used structured output or the free-text fallback.
"""

from __future__ import annotations

import datetime
import re
from typing import Optional, Union

from tradingagents.agents.utils.rating import parse_rating


# Tolerates the optional ``**`` bold wrappers and BUY/SELL/HOLD in any case.
_FINAL_PROPOSAL_RE = re.compile(
    r"FINAL TRANSACTION PROPOSAL:\s*\*{0,2}(BUY|SELL|HOLD)\*{0,2}",
    re.IGNORECASE,
)


def _field(markdown: str, label: str) -> Optional[str]:
    """Return the single-line value after a ``**Label**:`` marker, or ``None``.

    Tolerates the optional markdown bold wrappers around the label.
    """
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
    """Return the (possibly multi-line) value after a ``**Label**:`` marker.

    Captures everything up to the next ``**Something**:`` line marker or the end
    of the text, then collapses internal whitespace to a single line so it sits
    cleanly in a folded YAML block scalar.
    """
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
    """Coerce a string to a plain number.

    Strips ``$`` and thousands separators, and takes the primary (first) number
    of a range such as ``"100-120"``.  Returns ``None`` when no number is found.
    """
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


def _yaml_str(value: str) -> str:
    """Emit a double-quoted YAML scalar, escaping backslashes and quotes."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_block(value: str) -> str:
    """Emit a folded, strip-chomped block scalar (``>-``) with 2-space indent."""
    return ">-\n  " + " ".join(value.split())


def build_front_matter(
    final_state: dict,
    ticker: str,
    report_date: Optional[str] = None,
) -> str:
    """Build the ``---\\n...\\n---\\n\\n`` YAML front-matter block for a report.

    Only keys with a value are emitted; missing data is omitted rather than
    invented.  ``report_close`` and ``tranches`` are intentionally not produced
    (no close-price plumbing and no structured staged-entry data exist today);
    ``position_sizing`` is used in place of ``tranches``.
    """
    trader_md = final_state.get("trader_investment_plan") or ""
    pm_md = final_state.get("final_trade_decision") or ""

    ticker_up = (ticker or "").upper()

    # company: omit when it is just the ticker (no friendly name is available).
    company = final_state.get("company_of_interest")
    if company and company.strip().upper() == ticker_up:
        company = None

    if not report_date:
        report_date = final_state.get("trade_date") or None

    # parse_rating defaults to "Hold" on empty text, so only emit a rating when
    # the Portfolio Manager actually produced a decision.
    rating = parse_rating(pm_md) if pm_md else None

    action = _field(trader_md, "Action")
    entry_price = _num(_field(trader_md, "Entry Price"))
    stop_loss = _num(_field(trader_md, "Stop Loss"))
    position_sizing = _field(trader_md, "Position Sizing")

    price_target = _num(_field(pm_md, "Price Target"))
    time_horizon = _field(pm_md, "Time Horizon")
    summary = _block(pm_md, "Executive Summary")
    thesis = _block(pm_md, "Investment Thesis")

    final_proposal = _final_proposal(trader_md)
    if not final_proposal and action:
        final_proposal = action.upper()

    lines = ["---"]

    def add_str(key: str, value) -> None:
        if value not in (None, ""):
            lines.append(f"{key}: {_yaml_str(str(value))}")

    def add_num(key: str, value) -> None:
        if value is not None:
            lines.append(f"{key}: {value}")

    def add_block(key: str, value) -> None:
        if value:
            lines.append(f"{key}: {_yaml_block(value)}")

    add_str("ticker", ticker_up)
    add_str("company", company)
    add_str("report_date", report_date)
    add_str("generated_at", datetime.datetime.now().isoformat(timespec="seconds"))
    # report_close intentionally omitted: not available in agent state.
    add_str("rating", rating)
    add_str("action", action)
    add_num("entry_price", entry_price)
    add_num("stop_loss", stop_loss)
    add_str("position_sizing", position_sizing)
    add_num("price_target", price_target)
    add_str("time_horizon", time_horizon)
    add_block("summary", summary)
    add_block("thesis", thesis)
    add_str("final_proposal", final_proposal)
    lines.append("---")

    return "\n".join(lines) + "\n\n"
