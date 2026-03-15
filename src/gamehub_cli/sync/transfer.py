from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from ..common.fsops import DEFAULT_BACKUP_KEEP_LIMIT, backup_existing_file
from .downloads import DEFAULT_DOWNLOAD_CHUNK_BYTES, download_with_atomic_write, httpx

logger = logging.getLogger(__name__)


class SaveUploadConflictError(RuntimeError):
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        detail = payload.get("reason", "save-conflict")
        super().__init__(str(detail))


def stream_to_destination_atomic(
    *,
    server_url: str,
    url: str,
    destination: Path,
    expected_sha256: str,
    timeout_seconds: float,
    http_client: Any | None = None,
    backup_keep_limit: int = DEFAULT_BACKUP_KEEP_LIMIT,
) -> None:
    backup_result = backup_existing_file(destination, keep_limit=backup_keep_limit)
    if backup_result.created_path is not None:
        logger.info("save download backup created destination=%s backup=%s", destination, backup_result.created_path)
    for pruned_path in backup_result.pruned_paths:
        logger.info("save download backup pruned destination=%s pruned_backup=%s", destination, pruned_path)
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


def _encode_multipart_body(
    *,
    fields: dict[str, str],
    filename: str,
    payload: bytes,
    boundary: str,
) -> bytes:
    body = bytearray()
    boundary_bytes = boundary.encode("utf-8")
    for key, value in fields.items():
        body.extend(b"--" + boundary_bytes + b"\r\n")
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(b"--" + boundary_bytes + b"\r\n")
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
    )
    body.extend(payload)
    body.extend(b"\r\n")
    body.extend(b"--" + boundary_bytes + b"--\r\n")
    return bytes(body)


def upload_file_to_server(
    *,
    server_url: str,
    url: str,
    source: Path,
    binding_id: str,
    canonical_suffix: str,
    timeout_seconds: float,
    expected_remote_sha256: str | None = None,
    http_client: Any | None = None,
    chunk_size_bytes: int = DEFAULT_DOWNLOAD_CHUNK_BYTES,
) -> dict[str, object]:
    full_url = urljoin(server_url.rstrip("/") + "/", url.lstrip("/"))
    fields = {
        "binding_id": binding_id,
        "canonical_suffix": canonical_suffix,
    }
    if expected_remote_sha256 is not None:
        fields["expected_remote_sha256"] = expected_remote_sha256
    if httpx is not None:
        client = http_client if http_client is not None else httpx
        with source.open("rb") as handle:
            response = client.put(
                full_url,
                data=fields,
                files={"file": (source.name, handle, "application/octet-stream")},
                timeout=timeout_seconds,
            )
        if response.status_code == 409:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("detail")
                if isinstance(detail, dict):
                    raise SaveUploadConflictError(detail)
            response.raise_for_status()
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Save upload response must be a JSON object")
        return payload

    boundary = f"gamehub-{source.stat().st_mtime_ns}"
    request = Request(
        full_url,
        data=_encode_multipart_body(
            fields=fields, filename=source.name, payload=source.read_bytes(), boundary=boundary
        ),
        method="PUT",
    )
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if int(exc.code) == 409:
            payload = json.loads(exc.read().decode("utf-8"))
            if isinstance(payload, dict):
                detail = payload.get("detail")
                if isinstance(detail, dict):
                    raise SaveUploadConflictError(detail)
        raise
    if not isinstance(payload, dict):
        raise ValueError("Save upload response must be a JSON object")
    return payload
