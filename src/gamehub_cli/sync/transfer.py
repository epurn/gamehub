from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from ..common.fsops import backup_existing_file
from .downloads import DEFAULT_DOWNLOAD_CHUNK_BYTES, download_with_atomic_write, httpx

logger = logging.getLogger(__name__)


def stream_to_destination_atomic(
    *,
    server_url: str,
    url: str,
    destination: Path,
    expected_sha256: str,
    timeout_seconds: float,
    http_client: Any | None = None,
) -> None:
    backup_path = backup_existing_file(destination)
    if backup_path is not None:
        logger.info("save download backup created destination=%s backup=%s", destination, backup_path)
    download_with_atomic_write(
        server_url,
        url,
        destination,
        expected_sha256,
        timeout_seconds,
        http_client=http_client,
    )


def _iter_file_chunks(path: Path, chunk_size_bytes: int) -> Any:
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size_bytes)
            if not chunk:
                break
            yield chunk


def upload_file_to_server(
    *,
    server_url: str,
    url: str,
    source: Path,
    timeout_seconds: float,
    http_client: Any | None = None,
    chunk_size_bytes: int = DEFAULT_DOWNLOAD_CHUNK_BYTES,
) -> dict[str, object]:
    full_url = urljoin(server_url.rstrip("/") + "/", url.lstrip("/"))
    chunk_size = max(1024, int(chunk_size_bytes))
    if httpx is not None:
        client = http_client if http_client is not None else httpx
        response = client.put(full_url, content=_iter_file_chunks(source, chunk_size), timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Save upload response must be a JSON object")
        return payload

    request = Request(full_url, data=source.read_bytes(), method="PUT")
    request.add_header("Content-Type", "application/octet-stream")
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Save upload response must be a JSON object")
    return payload
