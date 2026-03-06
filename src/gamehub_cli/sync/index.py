from __future__ import annotations

import json
import time
from types import ModuleType
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import urlopen

_httpx: ModuleType | None
try:
    import httpx as _httpx_module

    _httpx = _httpx_module
except ModuleNotFoundError:  # pragma: no cover
    _httpx = None

httpx: ModuleType | None = _httpx


def _is_retryable_index_status(status_code: int) -> bool:
    return status_code in {408, 429} or 500 <= status_code <= 599


def _is_retryable_index_fetch_error(exc: Exception, httpx_module: ModuleType | None = None) -> bool:
    if isinstance(exc, HTTPError):
        return _is_retryable_index_status(int(exc.code))
    if isinstance(exc, URLError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    client = httpx_module if httpx_module is not None else httpx
    if client is None:
        return False
    timeout_exception = getattr(client, "TimeoutException", None)
    transport_error = getattr(client, "TransportError", None)
    http_status_error = getattr(client, "HTTPStatusError", None)
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


def _fetch_json_with_retries(
    *,
    url: str,
    timeout_seconds: float,
    attempts: int,
    retry_backoff_seconds: float,
    verbose: bool,
    request_label: str,
    http_client_module: ModuleType | None = None,
    sleep_func: Callable[[float], None] | None = None,
) -> dict:
    client = http_client_module if http_client_module is not None else httpx
    sleeper = sleep_func if sleep_func is not None else time.sleep
    total_attempts = max(1, int(attempts))
    last_error: Exception | None = None
    for attempt in range(1, total_attempts + 1):
        try:
            if verbose and total_attempts > 1:
                print(f"Fetching {request_label} attempt {attempt}/{total_attempts}")
            if client is not None:
                response = client.get(url, timeout=timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError(f"Server {request_label} response must be a JSON object")
                return payload
            with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError(f"Server {request_label} response must be a JSON object")
                return payload
        except Exception as exc:
            last_error = exc
            if attempt >= total_attempts or not _is_retryable_index_fetch_error(exc, httpx_module=client):
                raise
            delay = retry_backoff_seconds * (2 ** (attempt - 1))
            print(
                f"Warning: index fetch attempt {attempt}/{total_attempts} failed ({exc.__class__.__name__}). "
                f"Retrying in {delay:.1f}s..."
            )
            sleeper(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{request_label.capitalize()} fetch failed without an error")


def fetch_index_with_retries(
    *,
    index_url: str,
    timeout_seconds: float,
    attempts: int,
    retry_backoff_seconds: float,
    verbose: bool,
    http_client_module: ModuleType | None = None,
    sleep_func: Callable[[float], None] | None = None,
) -> dict:
    return _fetch_json_with_retries(
        url=index_url,
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        verbose=verbose,
        request_label="index",
        http_client_module=http_client_module,
        sleep_func=sleep_func,
    )


def fetch_save_bindings_with_retries(
    *,
    bindings_url: str,
    timeout_seconds: float,
    attempts: int,
    retry_backoff_seconds: float,
    verbose: bool,
    http_client_module: ModuleType | None = None,
    sleep_func: Callable[[float], None] | None = None,
) -> dict:
    return _fetch_json_with_retries(
        url=bindings_url,
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        verbose=verbose,
        request_label="save bindings",
        http_client_module=http_client_module,
        sleep_func=sleep_func,
    )


def probe_server_health(
    *,
    server_url: str,
    timeout_seconds: float,
    http_client_module: ModuleType | None = None,
) -> bool:
    health_url = urljoin(server_url.rstrip("/") + "/", "health")
    try:
        _fetch_json_with_retries(
            url=health_url,
            timeout_seconds=timeout_seconds,
            attempts=1,
            retry_backoff_seconds=0.0,
            verbose=False,
            request_label="health",
            http_client_module=http_client_module,
            sleep_func=None,
        )
    except Exception:
        return False
    return True
