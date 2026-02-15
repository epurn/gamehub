from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

try:
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    httpx = None


def _is_retryable_index_status(status_code: int) -> bool:
    return status_code in {408, 429} or 500 <= status_code <= 599


def _is_retryable_index_fetch_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return _is_retryable_index_status(int(exc.code))
    if isinstance(exc, URLError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if httpx is None:
        return False
    timeout_exception = getattr(httpx, "TimeoutException", None)
    transport_error = getattr(httpx, "TransportError", None)
    http_status_error = getattr(httpx, "HTTPStatusError", None)
    if timeout_exception is not None and isinstance(exc, timeout_exception):
        return True
    if transport_error is not None and isinstance(exc, transport_error):
        return True
    if http_status_error is not None and isinstance(exc, http_status_error):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return _is_retryable_index_status(status_code)
    return False


def fetch_index_with_retries(
    *,
    index_url: str,
    timeout_seconds: float,
    attempts: int,
    retry_backoff_seconds: float,
    verbose: bool,
) -> dict:
    total_attempts = max(1, int(attempts))
    last_error: Exception | None = None
    for attempt in range(1, total_attempts + 1):
        try:
            if verbose and total_attempts > 1:
                print(f"Fetching index attempt {attempt}/{total_attempts}")
            if httpx is not None:
                response = httpx.get(index_url, timeout=timeout_seconds)
                response.raise_for_status()
                return response.json()
            with urlopen(index_url, timeout=timeout_seconds) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt >= total_attempts or not _is_retryable_index_fetch_error(exc):
                raise
            delay = retry_backoff_seconds * (2 ** (attempt - 1))
            print(
                f"Warning: index fetch attempt {attempt}/{total_attempts} failed ({exc.__class__.__name__}). "
                f"Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Index fetch failed without an error")
