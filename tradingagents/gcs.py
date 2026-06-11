"""Google Cloud Storage upload utility for TradingAgents report output.

Uploads the two report files to the root of a GCS bucket using flat naming:
  gs://{bucket}/{TICKER}_{DATE}_report.md
  gs://{bucket}/{TICKER}_{DATE}_report_summary.json

Authentication uses ADC (Application Default Credentials), which is automatic
on Cloud Run with a service account that has the ``roles/storage.objectCreator``
binding on the target bucket.
"""

from __future__ import annotations

from pathlib import Path


def upload_report_to_gcs(
    save_path: Path,
    ticker: str,
    report_date: str,
    bucket_name: str,
) -> list[str]:
    """Upload the report and summary JSON to the root of a GCS bucket.

    Parameters
    ----------
    save_path:
        Local directory containing ``complete_report.md`` and
        ``complete_report_summary.json``.
    ticker:
        Ticker symbol used to name the GCS objects (e.g. ``AAPL``).
    report_date:
        Analysis date in ``YYYY-MM-DD`` format.
    bucket_name:
        GCS bucket name (without ``gs://`` scheme).

    Returns
    -------
    list[str]
        ``gs://`` URIs for the uploaded objects.
    """
    from google.cloud import storage  # type: ignore[import-untyped]

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    files = {
        save_path / "complete_report.md": f"{ticker}_{report_date}_report.md",
        save_path / "complete_report_summary.json": f"{ticker}_{report_date}_report_summary.json",
    }

    uris: list[str] = []
    for local_file, blob_name in files.items():
        if local_file.exists():
            bucket.blob(blob_name).upload_from_filename(str(local_file))
            uris.append(f"gs://{bucket_name}/{blob_name}")

    return uris
