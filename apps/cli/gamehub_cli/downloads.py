from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import urlopen

try:
    import httpx  # type: ignore
except ModuleNotFoundError:
    httpx = None


def download_with_atomic_write(
    server_url: str,
    url: str,
    destination: Path,
    expected_sha256: str,
    timeout: float = 30.0,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_suffix(f"{destination.suffix}.part")
    digest = hashlib.sha256()
    full_url = urljoin(server_url.rstrip("/") + "/", url.lstrip("/"))

    with part_path.open("wb") as handle:
        if httpx is not None:
            with httpx.stream("GET", full_url, timeout=timeout) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(1024 * 128):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
        else:
            with urlopen(full_url, timeout=timeout) as response:  # noqa: S310
                while True:
                    chunk = response.read(1024 * 128)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
        handle.flush()
        os.fsync(handle.fileno())

    actual = digest.hexdigest()
    if actual != expected_sha256:
        part_path.unlink(missing_ok=True)
        raise ValueError(f"Checksum mismatch for {url}: expected {expected_sha256}, got {actual}")

    part_path.replace(destination)
