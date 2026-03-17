from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import urlopen


class VerificationError(RuntimeError):
    pass


def _normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise VerificationError("Base URL must not be empty")
    return normalized + "/"


def _request_json(base_url: str, path: str, *, timeout: float) -> dict[str, Any]:
    response = _request_bytes(base_url, path, timeout=timeout)
    try:
        payload = json.loads(response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{path} did not return valid JSON") from exc
    if not isinstance(payload, dict):
        raise VerificationError(f"{path} did not return a JSON object")
    return payload


def _request_bytes(base_url: str, path: str, *, timeout: float) -> bytes:
    url = urljoin(base_url, path.lstrip("/"))
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise VerificationError(f"{path} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise VerificationError(f"{path} request failed: {exc.reason}") from exc
    except OSError as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        raise VerificationError(f"{path} request failed: {reason}") from exc


def wait_for_health(base_url: str, *, timeout: float, wait_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, wait_seconds)
    last_error: VerificationError | None = None

    while True:
        try:
            payload = _request_json(base_url, "/health", timeout=timeout)
            if payload.get("status") != "ok":
                raise VerificationError(f"/health returned unexpected payload: {payload}")
            return payload
        except VerificationError as exc:
            last_error = exc
            if time.monotonic() >= deadline:
                raise last_error
            time.sleep(0.5)


def verify_server(base_url: str, *, timeout: float, wait_seconds: float) -> None:
    normalized_base_url = _normalize_base_url(base_url)

    wait_for_health(normalized_base_url, timeout=timeout, wait_seconds=wait_seconds)
    print("PASS /health")

    status_payload = _request_json(normalized_base_url, "/v1/status", timeout=timeout)
    status_version = status_payload.get("status_version")
    if status_version is None:
        raise VerificationError("/v1/status did not return a status_version")
    if status_version != 1:
        raise VerificationError(f"/v1/status returned unexpected status_version={status_version!r}")
    server_version = status_payload.get("server_version")
    if not isinstance(server_version, str) or not server_version.strip():
        raise VerificationError("/v1/status did not return a server_version")
    status = status_payload.get("status")
    if not isinstance(status, str) or not status.strip():
        raise VerificationError("/v1/status did not return a status")
    if status != "ok":
        raise VerificationError(f"/v1/status reported status={status}")
    print(f"PASS /v1/status (status_version={status_version}, server_version={server_version}, status={status})")

    index_payload = _request_json(normalized_base_url, "/v1/index", timeout=timeout)
    index_version = index_payload.get("index_version")
    if index_version is None:
        raise VerificationError("/v1/index did not return an index_version")

    titles = index_payload.get("titles")
    if not isinstance(titles, list):
        raise VerificationError("/v1/index did not return a titles list")
    print(f"PASS /v1/index (index_version={index_version}, titles={len(titles)})")

    if titles:
        first_title = titles[0]
        if not isinstance(first_title, dict):
            raise VerificationError("/v1/index returned an invalid title entry")
        rom_payload = first_title.get("rom")
        if not isinstance(rom_payload, dict):
            raise VerificationError("/v1/index returned a title without rom metadata")
        file_id = rom_payload.get("file_id")
        if not isinstance(file_id, str) or not file_id.strip():
            raise VerificationError("/v1/index returned an empty rom.file_id")
        _request_bytes(normalized_base_url, f"/v1/files/{file_id}", timeout=timeout)
        print(f"PASS /v1/files/{file_id}")
    else:
        print("SKIP /v1/files/{file_id} (no titles in index)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a live GAMEHUB server deployment.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Server base URL to verify.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-request timeout in seconds. Default: 5.0.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=0.0,
        help="How long to wait for /health to become ready before failing. Default: 0.",
    )
    args = parser.parse_args(argv)

    try:
        print(f"Verifying GAMEHUB server at {args.base_url}")
        verify_server(args.base_url, timeout=args.timeout, wait_seconds=args.wait_seconds)
    except VerificationError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1

    print("GAMEHUB deployment verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
