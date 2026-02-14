from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path, PurePosixPath
import time
from typing import Callable
from urllib.parse import quote, urlparse

try:
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    httpx = None

from gamehub_common.models import TitleEntry

from .fsops import replace_file

SGDB_ART_KINDS = ("grid", "hero", "logo", "icon")


class SgdbError(RuntimeError):
    pass


@dataclass(frozen=True)
class SgdbLookupPlan:
    title_id: str
    title_name: str
    kinds: tuple[str, ...]


@dataclass(frozen=True)
class TitleArtworkBundle:
    title_id: str
    title_name: str
    files: dict[str, Path]


@dataclass
class ArtworkSyncResult:
    bundles: list[TitleArtworkBundle] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    lookups: int = 0
    downloaded: int = 0
    cached: int = 0


def redact_secret(secret: str | None) -> str:
    if not secret:
        return "<unset>"
    if len(secret) <= 6:
        return "***"
    return f"{secret[:3]}...{secret[-3:]}"


def build_stub_steam_app_id(title_id: str) -> str:
    return str(int(hashlib.sha256(title_id.encode("utf-8")).hexdigest()[:8], 16))


def build_lookup_plan(titles: tuple[TitleEntry, ...], kinds: tuple[str, ...]) -> list[SgdbLookupPlan]:
    return [SgdbLookupPlan(title_id=title.title_id, title_name=title.title_name, kinds=kinds) for title in titles]


def _cleanup_temp(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        return
    except PermissionError:
        pass
    if not path.exists():
        return
    try:
        with path.open("wb") as handle:
            handle.truncate(0)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass


def _extension_from_url(url: str) -> str:
    suffix = PurePosixPath(urlparse(url).path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".ico"}:
        return suffix
    return ".png"


class SgdbClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://www.steamgriddb.com/api/v2",
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        transport: object | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if httpx is None:
            raise SgdbError("httpx is required for SGDB artwork support")
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._sleep_fn = sleep_fn
        self._api_client = httpx.Client(
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )
        # Some SGDB CDN nodes reject authenticated requests. Keep a no-auth client for fallback.
        self._download_client = httpx.Client(
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._api_client.close()
        self._download_client.close()

    def __enter__(self) -> "SgdbClient":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def _request_json(self, path: str) -> dict:
        target_url = f"{self._base_url}/{path.lstrip('/')}"
        for attempt in range(self._max_retries + 1):
            response = self._api_client.get(target_url)
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt < self._max_retries:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait_seconds = float(retry_after)
                    else:
                        wait_seconds = self._backoff_seconds * (2**attempt)
                    self._sleep_fn(wait_seconds)
                    continue
                raise SgdbError(f"SGDB request failed with status {response.status_code} for {path}")

            try:
                response.raise_for_status()
            except Exception as exc:
                raise SgdbError(f"SGDB request failed for {path}: {exc}") from exc

            payload = response.json()
            if not isinstance(payload, dict):
                raise SgdbError(f"SGDB response was not a JSON object for {path}")
            return payload
        raise SgdbError(f"SGDB request exhausted retries for {path}")

    def find_game_id(self, title_name: str) -> int | None:
        payload = self._request_json(f"search/autocomplete/{quote(title_name)}")
        entries = payload.get("data", [])
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            game_id = entry.get("id")
            if isinstance(game_id, int):
                return game_id
        return None

    def resolve_asset_urls(self, game_id: int, kind: str) -> tuple[str, ...]:
        endpoint_by_kind = {
            "grid": "grids/game",
            "hero": "heroes/game",
            "logo": "logos/game",
            "icon": "icons/game",
        }
        endpoint = endpoint_by_kind[kind]
        payload = self._request_json(f"{endpoint}/{game_id}")
        entries = payload.get("data", [])
        if not isinstance(entries, list):
            return ()
        candidates: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for field in ("url", "thumb"):
                value = entry.get(field)
                if isinstance(value, str) and value:
                    if value not in seen:
                        seen.add(value)
                        candidates.append(value)
                    continue
                if isinstance(value, dict):
                    nested_url = value.get("url")
                    if isinstance(nested_url, str) and nested_url and nested_url not in seen:
                        seen.add(nested_url)
                        candidates.append(nested_url)
        return tuple(candidates)

    def _download_once(self, url: str, destination: Path, *, use_auth: bool) -> bool:
        client = self._api_client if use_auth else self._download_client
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size > 0:
            return False

        for attempt in range(self._max_retries + 1):
            part_path = destination.with_suffix(f"{destination.suffix}.part")
            expected_size: int | None = None
            bytes_written = 0
            try:
                with client.stream("GET", url, follow_redirects=True) as response:
                    if response.status_code in {429, 500, 502, 503, 504}:
                        raise SgdbError(f"Transient SGDB download failure {response.status_code} for {url}")
                    response.raise_for_status()
                    content_length = response.headers.get("Content-Length")
                    if content_length and content_length.isdigit():
                        expected_size = int(content_length)
                    with part_path.open("wb") as handle:
                        for chunk in response.iter_bytes(1024 * 128):
                            if not chunk:
                                continue
                            handle.write(chunk)
                            bytes_written += len(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())
                if expected_size is not None and bytes_written != expected_size:
                    raise SgdbError(
                        f"SGDB download length mismatch for {url}: expected {expected_size}, got {bytes_written}"
                    )
                replace_file(part_path, destination)
                return True
            except Exception as exc:
                _cleanup_temp(part_path)
                if attempt < self._max_retries and (
                    isinstance(exc, SgdbError)
                    or "429" in str(exc)
                    or "500" in str(exc)
                    or "502" in str(exc)
                    or "503" in str(exc)
                    or "504" in str(exc)
                ):
                    self._sleep_fn(self._backoff_seconds * (2**attempt))
                    continue
                raise SgdbError(f"Failed to download SGDB artwork from {url}: {exc}") from exc
        raise SgdbError(f"Exhausted SGDB download retries for {url}")

    def download_to_cache(self, url: str, destination: Path) -> bool:
        try:
            return self._download_once(url, destination, use_auth=True)
        except SgdbError as exc:
            if "401" not in str(exc):
                raise
            return self._download_once(url, destination, use_auth=False)


class SgdbArtworkPipeline:
    def __init__(self, client: SgdbClient, cache_dir: Path, kinds: tuple[str, ...]) -> None:
        self._client = client
        self._cache_dir = cache_dir
        self._kinds = kinds

    def _cache_path(self, title_id: str, kind: str, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        extension = _extension_from_url(url)
        return self._cache_dir / title_id / f"{kind}-{digest}{extension}"

    def sync(self, titles: tuple[TitleEntry, ...]) -> ArtworkSyncResult:
        result = ArtworkSyncResult()
        for title in titles:
            result.lookups += 1
            bundle = TitleArtworkBundle(title_id=title.title_id, title_name=title.title_name, files={})
            try:
                game_id = self._client.find_game_id(title.title_name)
            except SgdbError as exc:
                result.warnings.append(
                    f"SGDB lookup failed for '{title.title_name}': {exc}. "
                    "Check API key, quota, or connectivity."
                )
                continue
            if game_id is None:
                result.warnings.append(f"No SGDB game match for '{title.title_name}'.")
                continue

            for kind in self._kinds:
                try:
                    urls = self._client.resolve_asset_urls(game_id, kind)
                except SgdbError as exc:
                    result.warnings.append(f"SGDB {kind} lookup failed for '{title.title_name}': {exc}.")
                    continue
                if not urls:
                    continue
                download_error: SgdbError | None = None
                for url in urls:
                    cache_path = self._cache_path(title.title_id, kind, url)
                    if cache_path.exists() and cache_path.stat().st_size > 0:
                        result.cached += 1
                        bundle.files[kind] = cache_path
                        download_error = None
                        break
                    try:
                        was_downloaded = self._client.download_to_cache(url, cache_path)
                    except SgdbError as exc:
                        download_error = exc
                        continue
                    if was_downloaded:
                        result.downloaded += 1
                    else:
                        result.cached += 1
                    bundle.files[kind] = cache_path
                    download_error = None
                    break
                if download_error is not None:
                    result.warnings.append(f"SGDB {kind} download failed for '{title.title_name}': {download_error}.")
            if bundle.files:
                result.bundles.append(bundle)
        return result
