"""Headless report runner: run the trading agents and write markdown report
files, with no interactive UI.

Usage:
    uv run python run_report.py NVDA 2024-05-10
    uv run python run_report.py NVDA 2024-05-10 --asset crypto

Reports are written to:
    <results_dir>/<ticker>/<date>/reports/
which defaults to ~/.tradingagents/logs/... (override with TRADINGAGENTS_RESULTS_DIR).
"""

import argparse
from datetime import date as date_type
from pathlib import Path

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Reuse the exact report-writer the CLI uses, so output is identical.
from cli.main import save_report_to_disk


def main():
    parser = argparse.ArgumentParser(description="Run trading agents and save the report.")
    parser.add_argument("ticker", help="Ticker symbol, e.g. NVDA")
    parser.add_argument("date", nargs="?", help="Analysis date, YYYY-MM-DD (default: today)")
    parser.add_argument("--asset", default="stock", choices=["stock", "crypto"],
                        help="Asset pipeline (default: stock)")
    args = parser.parse_args()

    # Default to today if no date provided
    if args.date is None:
        args.date = date_type.today().isoformat()

    config = DEFAULT_CONFIG.copy()  # picks up TRADINGAGENTS_* env-var overrides

    # debug=False keeps stdout quiet; no Rich UI is used at all.
    ta = TradingAgentsGraph(debug=False, config=config)
    final_state, decision = ta.propagate(args.ticker, args.date, asset_type=args.asset)

    save_path = Path(config["results_dir"]) / args.ticker / args.date / "reports"
    report_file = save_report_to_disk(final_state, args.ticker, save_path, report_date=args.date)

    print(f"Decision: {decision}")
    print(f"Report written to: {report_file}")
    print(f"Per-section files under: {save_path}")


if __name__ == "__main__":
    main()
