from __future__ import annotations

import ssl
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

certifi: Any | None
try:
    import certifi
except ModuleNotFoundError:  # pragma: no cover
    certifi = None


def _request_url(request_or_url: Any) -> str:
    if isinstance(request_or_url, str):
        return request_or_url
    full_url = getattr(request_or_url, "full_url", None)
    if isinstance(full_url, str):
        return full_url
    get_full_url = getattr(request_or_url, "get_full_url", None)
    if callable(get_full_url):
        value = get_full_url()
        if isinstance(value, str):
            return value
    return ""


def _is_ssl_error(exc: Exception) -> bool:
    if isinstance(exc, ssl.SSLError):
        return True
    if isinstance(exc, URLError):
        return isinstance(getattr(exc, "reason", None), ssl.SSLError)
    return False


def _certifi_context() -> ssl.SSLContext | None:
    if certifi is None:
        return None
    try:
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def open_url(request_or_url: Any, *, timeout: float) -> Any:
    try:
        return urlopen(request_or_url, timeout=timeout)
    except Exception as exc:
        if not _request_url(request_or_url).startswith("https://") or not _is_ssl_error(exc):
            raise
        context = _certifi_context()
        if context is None:
            raise
        return urlopen(request_or_url, timeout=timeout, context=context)
