"""Build the machine-readable summary JSON from a completed run's final_state.

Structured data comes directly from the Pydantic objects stored in state
(``trader_proposal``, ``pm_decision``) — no markdown re-parsing needed.
When structured output was unavailable (free-text fallback), those keys are
``None`` and the corresponding fields are omitted from the summary.
"""

from __future__ import annotations

import datetime
from typing import Any, Optional, Union


def build_summary(
    final_state: dict,
    ticker: str,
    report_date: Optional[str] = None,
    report_close: Optional[Union[int, float]] = None,
) -> dict:
    """Return a dict suitable for ``json.dump`` as the run summary.

    Only keys with a value are included; missing data is omitted rather than
    invented.
    """
    ticker_up = (ticker or "").upper()

    company = final_state.get("company_of_interest")
    if company and company.strip().upper() == ticker_up:
        company = None

    trade_date = report_date or final_state.get("trade_date") or None

    trader_proposal: Any = final_state.get("trader_proposal")
    pm_decision: Any = final_state.get("pm_decision")

    out: dict = {}

    out["ticker"] = ticker_up
    if company:
        out["company"] = company
    if trade_date:
        out["report_date"] = trade_date
    out["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    if report_close is not None:
        out["report_close"] = report_close

    if pm_decision is not None:
        out["rating"] = pm_decision.rating.value
        if pm_decision.price_target is not None:
            out["price_target"] = pm_decision.price_target
        if pm_decision.time_horizon:
            out["time_horizon"] = pm_decision.time_horizon
        if pm_decision.executive_summary:
            out["summary"] = pm_decision.executive_summary
        if pm_decision.investment_thesis:
            out["thesis"] = pm_decision.investment_thesis

    if trader_proposal is not None:
        out["action"] = trader_proposal.action.value
        if trader_proposal.entry_price is not None:
            out["entry_price"] = trader_proposal.entry_price
        if trader_proposal.stop_loss is not None:
            out["stop_loss"] = trader_proposal.stop_loss
        if trader_proposal.position_sizing:
            out["position_sizing"] = trader_proposal.position_sizing
        if trader_proposal.tranches:
            out["tranches"] = [
                {k: v for k, v in t.model_dump().items() if v is not None}
                for t in trader_proposal.tranches
            ]
        out["final_proposal"] = trader_proposal.action.value.upper()

    return out
