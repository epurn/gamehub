from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from gamehub_common.version import __version__

from .index_repository import (
    IndexRepository,
    read_index_poll_seconds,
    read_index_refresh_seconds,
    read_index_stable_seconds,
)
from .indexer import FIRMWARE_ROOT_NAME
from .logging_utils import get_server_logger

logger = get_server_logger(__name__)

DATA_ROOT = Path(os.environ.get("GAMEHUB_DATA_DIR", "/data")).resolve()
INDEX_REPO = IndexRepository(
    DATA_ROOT,
    refresh_seconds=read_index_refresh_seconds(),
    poll_seconds=read_index_poll_seconds(),
    stable_seconds=read_index_stable_seconds(),
)


def _is_safe_segment(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    return "/" not in value and "\\" not in value


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


def start_index_poller() -> None:
    INDEX_REPO.start_polling()


def stop_index_poller() -> None:
    INDEX_REPO.stop_polling()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    warm_index_cache()
    start_index_poller()
    try:
        yield
    finally:
        stop_index_poller()


app = FastAPI(title="GAMEHUB Server", version=__version__, lifespan=_lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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


@app.get("/v1/saves/{save_id}")
def get_save(save_id: str) -> FileResponse:
    path = INDEX_REPO.resolve_save_path(save_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown save_id: {save_id}")
    return FileResponse(path)


@app.put("/v1/saves/{save_id}")
def put_save(save_id: str) -> Response:
    raise HTTPException(
        status_code=501,
        detail=(
            "Save upload is not implemented in this rollout. "
            "Planned semantics: upload to a temporary file, atomically replace target save, "
            "then refresh the in-memory index snapshot before returning."
        ),
    )


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
