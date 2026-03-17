from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin

from gamehub_common.models import LibraryIndex, SaveBindingCatalog, ServerStatus
from gamehub_common.version import __version__

from ..common.config import GamehubConfig
from ..common.http import open_url
from . import index as sync_index

DEFAULT_TIMEOUT_SECONDS = 30.0
VERBOSE_TIMEOUT_SECONDS = 60.0


class ServerStatusError(RuntimeError):
    """Raised when GAMEHUB server status cannot be verified."""


class ServerCompatibilityError(ServerStatusError):
    """Raised when the CLI and server versions do not match exactly."""


@dataclass(frozen=True)
class ServerDoctorReport:
    server_url: str
    client_version: str
    health: dict[str, object] | None
    status: ServerStatus | None
    index: LibraryIndex | None
    save_bindings: SaveBindingCatalog | None
    sample_file_id: str | None
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _normalized_server_url(server_url: str) -> str:
    normalized = server_url.strip()
    if not normalized:
        raise ServerStatusError("Server URL must not be empty")
    return normalized


def metadata_timeout_seconds(config: GamehubConfig, *, verbose: bool) -> float:
    if config.index_timeout_seconds is not None:
        return config.index_timeout_seconds
    return VERBOSE_TIMEOUT_SECONDS if verbose else DEFAULT_TIMEOUT_SECONDS


def fetch_server_status(
    *,
    server_url: str,
    timeout_seconds: float,
    attempts: int,
    retry_backoff_seconds: float,
    verbose: bool,
) -> ServerStatus:
    try:
        payload = sync_index.fetch_status_with_retries(
            server_url=_normalized_server_url(server_url),
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            verbose=verbose,
            http_client_module=sync_index.httpx,
            sleep_func=time.sleep,
            reporter=print,
        )
        return ServerStatus.model_validate(payload)
    except ServerStatusError:
        raise
    except Exception as exc:
        raise ServerStatusError(f"Server status check failed ({exc})") from exc


def ensure_server_version_match(server_status: ServerStatus, *, client_version: str = __version__) -> None:
    if server_status.server_version == client_version:
        return
    raise ServerCompatibilityError(
        "Server version mismatch: "
        f"client={client_version} server={server_status.server_version}. "
        "GAMEHUB client and server versions must match exactly."
    )


def require_server_compatibility(
    config: GamehubConfig,
    *,
    verbose: bool,
    server_url: str | None = None,
    timeout_seconds: float | None = None,
    attempts: int | None = None,
    retry_backoff_seconds: float | None = None,
) -> ServerStatus:
    resolved_server_url = server_url if server_url is not None else config.server_url
    resolved_timeout = (
        timeout_seconds if timeout_seconds is not None else metadata_timeout_seconds(config, verbose=verbose)
    )
    status = fetch_server_status(
        server_url=resolved_server_url,
        timeout_seconds=resolved_timeout,
        attempts=attempts if attempts is not None else config.index_fetch_attempts,
        retry_backoff_seconds=(
            retry_backoff_seconds if retry_backoff_seconds is not None else config.index_retry_backoff_seconds
        ),
        verbose=verbose,
    )
    ensure_server_version_match(status)
    return status


def fetch_sample_file_bytes(*, server_url: str, file_id: str, timeout_seconds: float) -> bytes:
    file_url = urljoin(server_url.rstrip("/") + "/", f"v1/files/{file_id}")
    try:
        with open_url(file_url, timeout=timeout_seconds) as response:
            payload = response.read()
            return payload if isinstance(payload, bytes) else bytes(payload)
    except HTTPError as exc:
        raise ServerStatusError(f"Sample file request failed with HTTP {exc.code}: {file_id}") from exc
    except URLError as exc:
        raise ServerStatusError(f"Sample file request failed for {file_id}: {exc.reason}") from exc
    except OSError as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        raise ServerStatusError(f"Sample file request failed for {file_id}: {reason}") from exc


def run_server_doctor(
    config: GamehubConfig,
    *,
    server_url: str | None = None,
    json_output: bool = False,
) -> int:
    resolved_server_url = _normalized_server_url(server_url if server_url is not None else config.server_url)
    timeout_seconds = metadata_timeout_seconds(config, verbose=False)
    errors: list[str] = []
    health_payload: dict[str, object] | None = None
    status_payload: ServerStatus | None = None
    index_payload: LibraryIndex | None = None
    bindings_payload: SaveBindingCatalog | None = None
    sample_file_id: str | None = None

    try:
        health_payload = sync_index.fetch_health_with_retries(
            server_url=resolved_server_url,
            timeout_seconds=timeout_seconds,
            attempts=config.index_fetch_attempts,
            retry_backoff_seconds=config.index_retry_backoff_seconds,
            verbose=False,
            http_client_module=sync_index.httpx,
            sleep_func=time.sleep,
            reporter=print,
        )
        if health_payload.get("status") != "ok":
            errors.append(f"Health check returned unexpected payload: {health_payload}")
    except Exception as exc:
        errors.append(f"Health check failed ({exc})")

    try:
        status_payload = fetch_server_status(
            server_url=resolved_server_url,
            timeout_seconds=timeout_seconds,
            attempts=config.index_fetch_attempts,
            retry_backoff_seconds=config.index_retry_backoff_seconds,
            verbose=False,
        )
        if status_payload.status != "ok":
            errors.append(f"Server reported status={status_payload.status}")
        try:
            ensure_server_version_match(status_payload)
        except ServerCompatibilityError as exc:
            errors.append(str(exc))
    except ServerStatusError as exc:
        errors.append(str(exc))

    try:
        raw_index = sync_index.fetch_index_with_retries(
            index_url=urljoin(resolved_server_url.rstrip("/") + "/", "v1/index"),
            timeout_seconds=timeout_seconds,
            attempts=config.index_fetch_attempts,
            retry_backoff_seconds=config.index_retry_backoff_seconds,
            verbose=False,
            http_client_module=sync_index.httpx,
            sleep_func=time.sleep,
            reporter=print,
        )
        index_payload = LibraryIndex.model_validate(raw_index)
    except Exception as exc:
        errors.append(f"Index check failed ({exc})")

    try:
        raw_bindings = sync_index.fetch_save_bindings_with_retries(
            bindings_url=urljoin(resolved_server_url.rstrip("/") + "/", "v1/save-bindings"),
            timeout_seconds=timeout_seconds,
            attempts=config.index_fetch_attempts,
            retry_backoff_seconds=config.index_retry_backoff_seconds,
            verbose=False,
            http_client_module=sync_index.httpx,
            sleep_func=time.sleep,
            reporter=print,
        )
        bindings_payload = SaveBindingCatalog.model_validate(raw_bindings)
    except Exception as exc:
        errors.append(f"Save binding check failed ({exc})")

    if index_payload is not None and index_payload.titles:
        sample_file_id = index_payload.titles[0].rom.file_id
        try:
            fetch_sample_file_bytes(
                server_url=resolved_server_url,
                file_id=sample_file_id,
                timeout_seconds=timeout_seconds,
            )
        except ServerStatusError as exc:
            errors.append(str(exc))

    report = ServerDoctorReport(
        server_url=resolved_server_url,
        client_version=__version__,
        health=health_payload,
        status=status_payload,
        index=index_payload,
        save_bindings=bindings_payload,
        sample_file_id=sample_file_id,
        errors=tuple(errors),
    )

    if json_output:
        payload = {
            "server_url": report.server_url,
            "client_version": report.client_version,
            "health": report.health,
            "status": report.status.model_dump(mode="json") if report.status is not None else None,
            "index": (
                {
                    "systems": len(report.index.systems),
                    "titles": len(report.index.titles),
                    "saves": len(report.index.saves),
                }
                if report.index is not None
                else None
            ),
            "save_bindings": (
                {"count": len(report.save_bindings.bindings)} if report.save_bindings is not None else None
            ),
            "sample_file": (
                {"checked": report.sample_file_id is not None, "file_id": report.sample_file_id}
                if report.sample_file_id is not None
                else {"checked": False, "reason": "no-titles"}
            ),
            "errors": list(report.errors),
            "ok": report.ok,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if report.ok else 1

    print(f"server-doctor\tserver={report.server_url}\tclient_version={report.client_version}")
    if report.health is not None:
        print(f"server-doctor\thealth\tstatus={report.health.get('status', '<missing>')}")
    if report.status is not None:
        print(
            "server-doctor\tstatus\t"
            f"server_version={report.status.server_version}\t"
            f"status={report.status.status}\t"
            f"titles={report.status.index.titles}\t"
            f"saves={report.status.index.saves}"
        )
    if report.index is not None:
        print(
            "server-doctor\tindex\t"
            f"systems={len(report.index.systems)}\t"
            f"titles={len(report.index.titles)}\t"
            f"saves={len(report.index.saves)}"
        )
    if report.save_bindings is not None:
        print(f"server-doctor\tsave-bindings\tcount={len(report.save_bindings.bindings)}")
    if report.sample_file_id is not None:
        print(f"server-doctor\tsample-file\tfile_id={report.sample_file_id}")
    else:
        print("server-doctor\tsample-file\tskipped=no-titles")
    for error in report.errors:
        print(f"server-doctor\terror\t{error}")
    print(f"server-doctor\tsummary\tok={str(report.ok).lower()}\terrors={len(report.errors)}")
    return 0 if report.ok else 1
