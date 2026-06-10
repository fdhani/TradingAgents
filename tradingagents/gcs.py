"""Google Cloud Storage upload utility for TradingAgents report output.

Uploads a local directory tree to a GCS bucket, preserving the subdirectory
structure relative to *local_path*. Authentication uses ADC (Application
Default Credentials), which is automatic on Cloud Run with a service account
that has the ``roles/storage.objectCreator`` binding on the target bucket.
"""

from __future__ import annotations

from pathlib import Path


def upload_directory_to_gcs(
    local_path: Path,
    bucket_name: str,
    gcs_prefix: str,
) -> list[str]:
    """Recursively upload all files under *local_path* to GCS.

    Parameters
    ----------
    local_path:
        Local directory whose contents are uploaded. The directory itself is
        not represented in GCS — only its contents, preserving subdirectory
        structure relative to *local_path*.
    bucket_name:
        GCS bucket name (without ``gs://`` scheme).
    gcs_prefix:
        Object name prefix inside the bucket. Resulting object names are
        ``{gcs_prefix}/{relative_file_path}``.

    Returns
    -------
    list[str]
        ``gs://`` URIs for every uploaded object, in filesystem traversal
        order. Returns an empty list when *local_path* contains no files.
    """
    # Lazy import so startup cost is zero when GCS upload is disabled.
    from google.cloud import storage  # type: ignore[import-untyped]

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    prefix = gcs_prefix.rstrip("/")
    uris: list[str] = []

    for file_path in sorted(local_path.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(local_path)
        blob_name = f"{prefix}/{relative}"
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(file_path))
        uri = f"gs://{bucket_name}/{blob_name}"
        uris.append(uri)

    return uris
