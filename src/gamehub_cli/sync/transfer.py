from __future__ import annotations

from pathlib import Path
from typing import Any

from .downloads import download_with_atomic_write


def stream_to_destination_atomic(
    *,
    server_url: str,
    url: str,
    destination: Path,
    expected_sha256: str,
    timeout_seconds: float,
    http_client: Any | None = None,
) -> None:
    download_with_atomic_write(
        server_url,
        url,
        destination,
        expected_sha256,
        timeout_seconds,
        http_client=http_client,
    )
