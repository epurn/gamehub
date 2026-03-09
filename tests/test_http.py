from __future__ import annotations

import ssl
from urllib.error import URLError

from gamehub_cli.common.http import open_url


class _FakeResponse:
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb

    def read(self) -> bytes:
        return b"ok"


def test_open_url_retries_https_ssl_errors_with_certifi_context(monkeypatch) -> None:
    calls: list[object | None] = []
    fallback_context = object()

    def fake_urlopen(request_or_url, timeout: float, context=None):
        del request_or_url, timeout
        calls.append(context)
        if context is None:
            raise URLError(ssl.SSLCertVerificationError("certificate verify failed"))
        if context is fallback_context:
            return _FakeResponse()
        raise AssertionError("unexpected SSL context")

    monkeypatch.setattr("gamehub_cli.common.http.urlopen", fake_urlopen)
    monkeypatch.setattr("gamehub_cli.common.http._certifi_context", lambda: fallback_context)

    with open_url("https://example.invalid/test", timeout=5.0) as response:
        assert response.read() == b"ok"

    assert calls == [None, fallback_context]


def test_open_url_does_not_retry_non_https_ssl_errors(monkeypatch) -> None:
    calls: list[object | None] = []

    def fake_urlopen(request_or_url, timeout: float, context=None):
        del request_or_url, timeout, context
        calls.append(None)
        raise URLError(ssl.SSLCertVerificationError("certificate verify failed"))

    monkeypatch.setattr("gamehub_cli.common.http.urlopen", fake_urlopen)
    monkeypatch.setattr("gamehub_cli.common.http._certifi_context", lambda: object())

    try:
        open_url("http://example.invalid/test", timeout=5.0)
    except URLError as exc:
        assert isinstance(exc.reason, ssl.SSLError)
    else:  # pragma: no cover
        raise AssertionError("expected URLError")

    assert calls == [None]
