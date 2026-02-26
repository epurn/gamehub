from __future__ import annotations

import gzip
import hashlib
import logging
import os
import stat
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from .indexer import FIRMWARE_ROOT_NAME, IndexBundle, build_index

app = FastAPI(title="GAMEHUB Server", version="1.3.0")
logger = logging.getLogger(__name__)


def _path_signature_fields(path: Path, data_root: Path) -> tuple[str, str, int, int] | None:
    try:
        stat_result = path.stat()
    except OSError:
        return None

    mode = stat_result.st_mode
    if stat.S_ISDIR(mode):
        kind = "dir"
    elif stat.S_ISREG(mode):
        kind = "file"
    else:
        kind = "other"

    try:
        relative = path.relative_to(data_root).as_posix()
    except ValueError:
        relative = path.resolve().as_posix()
    return relative, kind, int(stat_result.st_size), int(stat_result.st_mtime_ns)


def _sorted_children(path: Path) -> list[Path]:
    try:
        children = list(path.iterdir())
    except OSError:
        return []
    return sorted(children, key=lambda item: item.name.casefold())


def _snapshot_data_signature(data_root: Path) -> str:
    digest = hashlib.blake2s(digest_size=16)

    def _update(relative: str, kind: str, size_bytes: int, mtime_ns: int) -> None:
        digest.update(f"{relative}|{kind}|{size_bytes}|{mtime_ns}\n".encode("utf-8"))

    for root_name in ("roms", FIRMWARE_ROOT_NAME):
        root = data_root / root_name
        root_fields = _path_signature_fields(root, data_root)
        if root_fields is None:
            _update(root_name, "missing", 0, 0)
            continue
        _update(*root_fields)
        if root_fields[1] != "dir":
            continue

        for system_entry in _sorted_children(root):
            system_fields = _path_signature_fields(system_entry, data_root)
            if system_fields is None:
                continue
            _update(*system_fields)
            if system_fields[1] != "dir":
                continue

            for child_entry in _sorted_children(system_entry):
                child_fields = _path_signature_fields(child_entry, data_root)
                if child_fields is None:
                    continue
                _update(*child_fields)

    return digest.hexdigest()


class IndexRepository:
    def __init__(self, data_root: Path, refresh_seconds: float = 0.0) -> None:
        self._data_root = data_root
        self._cache: IndexBundle | None = None
        self._payload_json: bytes | None = None
        self._payload_gzip: bytes | None = None
        self._source_signature: str | None = None
        self._loaded_at: float | None = None
        self._refresh_seconds = max(0.0, float(refresh_seconds))
        self._lock = threading.Lock()

    def _should_refresh(self, source_signature: str | None = None) -> bool:
        if self._cache is None:
            return True
        if source_signature is not None and source_signature != self._source_signature:
            return True
        if self._refresh_seconds <= 0:
            return False
        if self._loaded_at is None:
            return True
        age_seconds = time.monotonic() - self._loaded_at
        return age_seconds >= self._refresh_seconds

    def load(self, force_refresh: bool = False, *, check_sources: bool = True) -> IndexBundle:
        source_signature: str | None = None
        if not force_refresh and check_sources:
            source_signature = _snapshot_data_signature(self._data_root)
        if not force_refresh and not self._should_refresh(source_signature=source_signature):
            if self._cache is None:
                raise RuntimeError("Index cache was expected but is missing")
            return self._cache

        with self._lock:
            if not force_refresh and check_sources:
                source_signature = _snapshot_data_signature(self._data_root)
            if force_refresh or self._should_refresh(source_signature=source_signature):
                self._cache = build_index(self._data_root)
                self._payload_json = self._cache.index.model_dump_json().encode("utf-8")
                self._payload_gzip = gzip.compress(self._payload_json, compresslevel=5)
                if source_signature is None:
                    source_signature = _snapshot_data_signature(self._data_root)
                self._source_signature = source_signature
                self._loaded_at = time.monotonic()
        if self._cache is None:
            raise RuntimeError("Index cache was expected but is missing")
        return self._cache

    def load_payload(self, force_refresh: bool = False, *, prefer_gzip: bool = False) -> tuple[bytes, bool]:
        self.load(force_refresh=force_refresh)
        if prefer_gzip and self._payload_gzip is not None:
            return self._payload_gzip, True
        if self._payload_json is None:
            raise RuntimeError("Index payload cache was expected but is missing")
        return self._payload_json, False


def _read_index_refresh_seconds() -> float:
    raw = os.environ.get("GAMEHUB_INDEX_REFRESH_SECONDS", "0").strip()
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if seconds < 0:
        return 0.0
    return seconds


DATA_ROOT = Path(os.environ.get("GAMEHUB_DATA_DIR", "/data")).resolve()
INDEX_REPO = IndexRepository(DATA_ROOT, refresh_seconds=_read_index_refresh_seconds())


def _is_safe_segment(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    return "/" not in value and "\\" not in value


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def warm_index_cache() -> None:
    # Preload the index so first /v1/index request does not trigger full-library hashing.
    logger.info("index warmup started data_root=%s", DATA_ROOT)
    started_at = time.monotonic()
    try:
        bundle = INDEX_REPO.load(force_refresh=True)
    except Exception:
        elapsed_seconds = time.monotonic() - started_at
        logger.exception("index warmup failed elapsed_seconds=%.3f", elapsed_seconds)
        raise

    elapsed_seconds = time.monotonic() - started_at
    logger.info(
        "index warmup completed elapsed_seconds=%.3f systems=%d titles=%d",
        elapsed_seconds,
        len(bundle.index.systems),
        len(bundle.index.titles),
    )


@app.get("/v1/index")
def get_index(request: Request, refresh: bool = Query(default=False)) -> Response:
    accept_encoding = request.headers.get("accept-encoding", "")
    wants_gzip = "gzip" in accept_encoding.lower()
    payload, is_gzip = INDEX_REPO.load_payload(force_refresh=refresh, prefer_gzip=wants_gzip)
    headers: dict[str, str] = {}
    if is_gzip:
        headers["Content-Encoding"] = "gzip"
        headers["Vary"] = "Accept-Encoding"
    return Response(content=payload, media_type="application/json", headers=headers)


@app.get("/v1/files/{file_id}")
def get_file(file_id: str) -> FileResponse:
    bundle = INDEX_REPO.load(check_sources=False)
    path = bundle.file_paths.get(file_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown file_id: {file_id}")
    return FileResponse(path)


@app.get("/v1/assets/{asset_id}")
def get_asset(asset_id: str) -> FileResponse:
    bundle = INDEX_REPO.load(check_sources=False)
    path = bundle.asset_paths.get(asset_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown asset_id: {asset_id}")
    return FileResponse(path)


@app.get("/v1/firmware/{system}/{filename}")
def get_firmware(system: str, filename: str) -> FileResponse:
    if not _is_safe_segment(system) or not _is_safe_segment(filename):
        raise HTTPException(status_code=404, detail="Firmware file not found")

    firmware_root = (DATA_ROOT / FIRMWARE_ROOT_NAME).resolve()
    system_root = (firmware_root / system).resolve()
    if not system_root.is_relative_to(firmware_root):
        raise HTTPException(status_code=404, detail="Firmware file not found")

    path = (system_root / filename).resolve()
    if not path.is_relative_to(system_root):
        raise HTTPException(status_code=404, detail="Firmware file not found")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Firmware file not found: {system}/{filename}")
    return FileResponse(path)


def run() -> None:
    uvicorn.run("gamehub_server.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
