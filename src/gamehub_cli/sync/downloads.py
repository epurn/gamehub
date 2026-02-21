from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import urlopen

try:
    import httpx  # type: ignore
except ModuleNotFoundError:
    httpx = None

from ..common.fsops import replace_file

DEFAULT_DOWNLOAD_CHUNK_BYTES = 1024 * 1024


def _cleanup_part_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        return
    except PermissionError:
        pass
    if not path.exists():
        return
    with path.open("wb") as handle:
        handle.truncate(0)
        handle.flush()
        os.fsync(handle.fileno())


def download_with_atomic_write(
    server_url: str,
    url: str,
    destination: Path,
    expected_sha256: str,
    timeout: float = 30.0,
    *,
    http_client: Any | None = None,
    chunk_size_bytes: int = DEFAULT_DOWNLOAD_CHUNK_BYTES,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_suffix(f"{destination.suffix}.part")
    digest = hashlib.sha256()
    full_url = urljoin(server_url.rstrip("/") + "/", url.lstrip("/"))
    chunk_size = max(1024, int(chunk_size_bytes))

    with part_path.open("wb") as handle:
        if httpx is not None:
            stream_client = http_client if http_client is not None else httpx
            with stream_client.stream("GET", full_url, timeout=timeout) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(chunk_size):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
        else:
            with urlopen(full_url, timeout=timeout) as response:  # noqa: S310
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
        handle.flush()
        os.fsync(handle.fileno())

    actual = digest.hexdigest()
    if actual != expected_sha256:
        _cleanup_part_file(part_path)
        raise ValueError(f"Checksum mismatch for {url}: expected {expected_sha256}, got {actual}")

    replace_file(part_path, destination)
