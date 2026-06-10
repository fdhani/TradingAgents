"""Tests for the summary sidecar JSON written alongside the consolidated report.

The summary is parsed out of the deterministic markdown the decision agents
render (``render_trader_proposal`` / ``render_pm_decision``), so these tests
build their ``final_state`` from real schema objects to stay faithful to the
shapes the report writer sees in production.
"""

import pytest

from cli.report_summary import build_summary
from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    TraderAction,
    TraderProposal,
    render_pm_decision,
    render_trader_proposal,
)


@pytest.mark.unit
class TestBuildSummary:
    def test_full_case_all_fields_present(self):
        trader_md = render_trader_proposal(
            TraderProposal(
                action=TraderAction.BUY,
                reasoning="Strong technicals and fundamentals align.",
                entry_price=189.5,
                stop_loss=178.0,
                position_sizing="6% of portfolio",
            )
        )
        pm_md = render_pm_decision(
            PortfolioDecision(
                rating=PortfolioRating.BUY,
                executive_summary="Enter on a pullback; size to 6%; trail the stop.",
                investment_thesis="Accelerating data-center demand underpins the move.",
                price_target=240.0,
                time_horizon="3-6 months",
            )
        )
        final_state = {
            "trader_investment_plan": trader_md,
            "final_trade_decision": pm_md,
            "company_of_interest": "NVDA",
            "trade_date": "2024-05-10",
        }

        data = build_summary(final_state, "nvda", report_date="2024-05-10", report_close=185.25)

        assert data["ticker"] == "NVDA"
        assert data["report_date"] == "2024-05-10"
        assert data["report_close"] == 185.25
        assert data["rating"] == "Buy"
        assert data["action"] == "Buy"
        assert data["entry_price"] == 189.5
        assert data["stop_loss"] == 178  # 178.0 collapses to a plain int
        assert data["position_sizing"] == "6% of portfolio"
        assert data["price_target"] == 240
        assert data["time_horizon"] == "3-6 months"
        assert "pullback" in data["summary"]
        assert "data-center demand" in data["thesis"]
        assert data["final_proposal"] == "BUY"
        assert "generated_at" in data
        assert "tranches" not in data

    def test_report_close_omitted_when_not_provided(self):
        data = build_summary(
            {"final_trade_decision": "Rating: Hold", "company_of_interest": "NVDA"},
            "NVDA",
            report_date="2024-05-10",
        )
        assert "report_close" not in data

    def test_report_close_emitted_as_number(self):
        data = build_summary(
            {"final_trade_decision": "Rating: Hold"},
            "NVDA",
            report_date="2024-05-10",
            report_close=910.0,
        )
        assert data["report_close"] == 910

    def test_minimal_hold_omits_optional_numeric_fields(self):
        trader_md = render_trader_proposal(
            TraderProposal(action=TraderAction.HOLD, reasoning="No edge.")
        )
        pm_md = render_pm_decision(
            PortfolioDecision(
                rating=PortfolioRating.HOLD,
                executive_summary="Stand pat.",
                investment_thesis="Evidence is balanced.",
            )
        )
        final_state = {
            "trader_investment_plan": trader_md,
            "final_trade_decision": pm_md,
            "company_of_interest": "MSFT",
        }
        data = build_summary(final_state, "MSFT", report_date="2024-05-10")

        assert data["action"] == "Hold"
        assert data["final_proposal"] == "HOLD"
        for absent in ("entry_price", "stop_loss", "position_sizing", "price_target", "time_horizon"):
            assert absent not in data

    def test_price_with_dollar_sign_and_range_collapses_to_primary_number(self):
        trader_md = (
            "**Action**: Buy\n\n"
            "**Reasoning**: ...\n\n"
            "**Entry Price**: $1,234.50\n\n"
            "**Stop Loss**: 100-120\n\n"
            "FINAL TRANSACTION PROPOSAL: **BUY**"
        )
        data = build_summary({"trader_investment_plan": trader_md}, "TSLA", report_date="2024-05-10")
        assert data["entry_price"] == 1234.5
        assert data["stop_loss"] == 100

    def test_free_text_fallback_rating_and_graceful_omission(self):
        final_state = {
            "trader_investment_plan": "We should sit this one out for now.",
            "final_trade_decision": "After weighing the debate, our rating is Sell.",
            "company_of_interest": "GME",
        }
        data = build_summary(final_state, "GME", report_date="2024-05-10")

        assert data["rating"] == "Sell"
        assert "action" not in data
        assert "entry_price" not in data
        assert "summary" not in data
        assert "thesis" not in data

    def test_company_omitted_when_equal_to_ticker(self):
        data = build_summary(
            {"final_trade_decision": "Rating: Hold", "company_of_interest": "NVDA"},
            "nvda",
            report_date="2024-05-10",
        )
        assert data["ticker"] == "NVDA"
        assert "company" not in data

    def test_report_date_falls_back_to_trade_date(self):
        data = build_summary(
            {"final_trade_decision": "Rating: Hold", "trade_date": "2023-01-02"},
            "ABC",
        )
        assert data["report_date"] == "2023-01-02"

    def test_structured_fields_parse_correctly(self):
        pm_md = render_pm_decision(
            PortfolioDecision(
                rating=PortfolioRating.OVERWEIGHT,
                executive_summary="Add gradually: 2% now, more on dips; watch $200.",
                investment_thesis="Margins, guidance, and demand all point higher.",
                price_target=200.0,
                time_horizon="6-12 months",
            )
        )
        data = build_summary(
            {"final_trade_decision": pm_md, "company_of_interest": "Acme Corp"},
            "ACME",
            report_date="2024-05-10",
        )
        assert data["company"] == "Acme Corp"
        assert data["rating"] == "Overweight"
        assert data["price_target"] == 200
