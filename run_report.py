"""Headless report runner: run the trading agents and write markdown report
files, with no interactive UI.

Usage:
    uv run python run_report.py NVDA 2024-05-10
    uv run python run_report.py NVDA 2024-05-10 --asset crypto

On Cloud Run, pass ticker and date via --args at execution time:
    gcloud run jobs execute tradingagents --args="NVDA,2024-05-10"

Reports are written to:
    <results_dir>/<ticker>/<date>/reports/
which defaults to ~/.tradingagents/logs/... (override with TRADINGAGENTS_RESULTS_DIR).
"""

import argparse
import sys
import traceback
from datetime import date as date_type
from pathlib import Path

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Reuse the exact report-writer the CLI uses, so output is identical.
from cli.main import save_report_to_disk
from tradingagents.gcs import upload_directory_to_gcs


def _log(msg: str) -> None:
    """Print a timestamped progress line (captured by Cloud Logging via stdout)."""
    print(msg, flush=True)


def _validate_gcs(bucket_name: str) -> None:
    """Check that the GCS bucket exists and is accessible. Exits on failure."""
    from google.cloud import storage
    from google.cloud.exceptions import NotFound, Forbidden

    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        if not bucket.exists():
            _log(f"[run_report] ERROR: GCS bucket '{bucket_name}' does not exist.")
            sys.exit(1)
        _log(f"[run_report] GCS bucket '{bucket_name}' validated OK.")
    except Forbidden:
        _log(f"[run_report] ERROR: Permission denied accessing GCS bucket '{bucket_name}'. "
             "Ensure the service account has roles/storage.objectCreator.")
        sys.exit(1)
    except Exception as e:
        _log(f"[run_report] ERROR: Could not validate GCS bucket '{bucket_name}': {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run trading agents and save the report.")
    parser.add_argument("ticker", help="Ticker symbol, e.g. NVDA")
    parser.add_argument("date", nargs="?", help="Analysis date, YYYY-MM-DD (default: today)")
    parser.add_argument("--asset", default="stock", choices=["stock", "crypto"],
                        help="Asset pipeline (default: stock)")
    args = parser.parse_args()

    if args.date is None:
        args.date = date_type.today().isoformat()

    _log(f"[run_report] ticker={args.ticker} date={args.date} asset={args.asset}")

    config = DEFAULT_CONFIG.copy()  # picks up TRADINGAGENTS_* env-var overrides

    _log("[run_report] Initializing TradingAgentsGraph...")
    ta = TradingAgentsGraph(debug=False, config=config)

    _log("[run_report] Running analysis pipeline...")
    final_state, decision = ta.propagate(args.ticker, args.date, asset_type=args.asset)

    _log("[run_report] Analysis complete. Saving report to disk...")
    save_path = Path(config["results_dir"]) / args.ticker / args.date / "reports"
    report_file = save_report_to_disk(final_state, args.ticker, save_path, report_date=args.date)

    print(f"Decision: {decision}")
    print(f"Report written to: {report_file}")
    print(f"Per-section files under: {save_path}")

    gcs_bucket = config.get("gcs_output_bucket")
    if not gcs_bucket:
        _log("[run_report] TRADINGAGENTS_GCS_BUCKET not set — skipping GCS upload.")
    else:
        _validate_gcs(gcs_bucket)
        _log(f"[run_report] Uploading reports to GCS bucket '{gcs_bucket}'...")
        gcs_prefix = f"{config.get('gcs_output_prefix', 'tradingagents')}/{args.ticker}/{args.date}/reports"
        uris = upload_directory_to_gcs(save_path, gcs_bucket, gcs_prefix)
        for uri in uris:
            print(f"Uploaded: {uri}")
        if uris:
            print(f"GCS output: gs://{gcs_bucket}/{gcs_prefix}/")

    _log("[run_report] Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
