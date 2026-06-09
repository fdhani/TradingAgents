"""Tests for the YAML front-matter prepended to the consolidated report.

The front-matter is parsed out of the deterministic markdown the decision
agents render (``render_trader_proposal`` / ``render_pm_decision``), so these
tests build their ``final_state`` from real schema objects to stay faithful to
the shapes the report writer sees in production.
"""

import pytest

from cli.report_frontmatter import build_front_matter
from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    TraderAction,
    TraderProposal,
    render_pm_decision,
    render_trader_proposal,
)


def _front_matter_dict(block: str) -> dict:
    """Parse the emitted front-matter into a dict.

    A tiny purpose-built parser for the known emission format (quoted string
    scalars, bare numbers, and ``>-`` folded block scalars) so the tests stay
    free of a PyYAML dependency.  Also asserts basic structural validity:
    leading/closing ``---`` fences and 2-space-indented block continuations.
    """
    lines = block.split("\n")
    assert lines[0] == "---", "front-matter must open with a '---' fence"
    data: dict = {}
    i = 1
    saw_close = False
    while i < len(lines):
        line = lines[i]
        if line == "---":
            saw_close = True
            break
        if not line:
            i += 1
            continue
        assert not line.startswith(" "), f"unexpected indented line: {line!r}"
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == ">-":
            i += 1
            buf = []
            while i < len(lines) and lines[i].startswith("  "):
                buf.append(lines[i].strip())
                i += 1
            data[key] = " ".join(buf)
            continue
        if rest.startswith('"') and rest.endswith('"'):
            data[key] = rest[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        else:
            try:
                num = float(rest)
                data[key] = int(num) if num.is_integer() else num
            except ValueError:
                data[key] = rest
        i += 1
    assert saw_close, "front-matter must close with a '---' fence"
    return data


@pytest.mark.unit
class TestBuildFrontMatter:
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

        block = build_front_matter(final_state, "nvda", report_date="2024-05-10")
        data = _front_matter_dict(block)

        assert data["ticker"] == "NVDA"
        assert data["report_date"] == "2024-05-10"
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
        # generated_at present; report_close never emitted; tranches never emitted.
        assert "generated_at" in data
        assert "report_close" not in data
        assert "tranches" not in data

    def test_block_scalars_used_for_summary_and_thesis(self):
        pm_md = render_pm_decision(
            PortfolioDecision(
                rating=PortfolioRating.HOLD,
                executive_summary="Balanced setup with no clear edge.",
                investment_thesis="Bull and bear cases offset.",
            )
        )
        block = build_front_matter(
            {"final_trade_decision": pm_md, "company_of_interest": "AAPL"},
            "AAPL",
            report_date="2024-05-10",
        )
        # Folded block scalars (`>-`) are used so multi-sentence prose stays tidy.
        assert "summary: >-" in block
        assert "thesis: >-" in block

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
        data = _front_matter_dict(build_front_matter(final_state, "MSFT", report_date="2024-05-10"))

        assert data["action"] == "Hold"
        assert data["final_proposal"] == "HOLD"
        for absent in ("entry_price", "stop_loss", "position_sizing", "price_target", "time_horizon"):
            assert absent not in data

    def test_price_with_dollar_sign_and_range_collapses_to_primary_number(self):
        # A weaker model / free-text path might emit a styled or ranged price;
        # the parser strips '$' and commas and keeps the primary number.
        trader_md = (
            "**Action**: Buy\n\n"
            "**Reasoning**: ...\n\n"
            "**Entry Price**: $1,234.50\n\n"
            "**Stop Loss**: 100-120\n\n"
            "FINAL TRANSACTION PROPOSAL: **BUY**"
        )
        data = _front_matter_dict(
            build_front_matter({"trader_investment_plan": trader_md}, "TSLA", report_date="2024-05-10")
        )
        assert data["entry_price"] == 1234.5
        assert data["stop_loss"] == 100

    def test_free_text_fallback_rating_and_graceful_omission(self):
        # Provider without structured output: PM decision is free-text prose.
        # rating falls back to parse_rating; typed-only fields are omitted.
        final_state = {
            "trader_investment_plan": "We should sit this one out for now.",
            "final_trade_decision": "After weighing the debate, our rating is Sell.",
            "company_of_interest": "GME",
        }
        data = _front_matter_dict(build_front_matter(final_state, "GME", report_date="2024-05-10"))

        assert data["rating"] == "Sell"
        assert "action" not in data
        assert "entry_price" not in data
        assert "summary" not in data
        assert "thesis" not in data

    def test_company_omitted_when_equal_to_ticker(self):
        data = _front_matter_dict(
            build_front_matter(
                {"final_trade_decision": "Rating: Hold", "company_of_interest": "NVDA"},
                "nvda",
                report_date="2024-05-10",
            )
        )
        assert data["ticker"] == "NVDA"
        assert "company" not in data

    def test_report_date_falls_back_to_trade_date(self):
        data = _front_matter_dict(
            build_front_matter(
                {"final_trade_decision": "Rating: Hold", "trade_date": "2023-01-02"},
                "ABC",
            )
        )
        assert data["report_date"] == "2023-01-02"

    def test_block_structurally_parses_with_punctuation(self):
        # End-to-end sanity: the emitted block stays structurally well-formed
        # (fences + indentation) and parses cleanly even when the prose contains
        # punctuation that would break an unquoted YAML scalar.
        pm_md = render_pm_decision(
            PortfolioDecision(
                rating=PortfolioRating.OVERWEIGHT,
                executive_summary="Add gradually: 2% now, more on dips; watch $200.",
                investment_thesis="Margins, guidance, and demand all point higher.",
                price_target=200.0,
                time_horizon="6-12 months",
            )
        )
        block = build_front_matter(
            {"final_trade_decision": pm_md, "company_of_interest": "Acme Corp"},
            "ACME",
            report_date="2024-05-10",
        )
        data = _front_matter_dict(block)
        assert data["company"] == "Acme Corp"
        assert data["rating"] == "Overweight"
        assert data["price_target"] == 200
