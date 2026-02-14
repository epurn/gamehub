from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .indexer import FIRMWARE_ROOT_NAME, IndexBundle, build_index

app = FastAPI(title="GAMEHUB Server", version="0.1.0")


class IndexRepository:
    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root
        self._cache: IndexBundle | None = None

    def load(self, force_refresh: bool = False) -> IndexBundle:
        if self._cache is None or force_refresh:
            self._cache = build_index(self._data_root)
        return self._cache


DATA_ROOT = Path(os.environ.get("GAMEHUB_DATA_DIR", "/data")).resolve()
INDEX_REPO = IndexRepository(DATA_ROOT)


def _is_safe_segment(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    return "/" not in value and "\\" not in value


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/index")
def get_index() -> dict:
    return INDEX_REPO.load(force_refresh=True).index.model_dump(mode="json")


@app.get("/v1/files/{file_id}")
def get_file(file_id: str) -> FileResponse:
    bundle = INDEX_REPO.load(force_refresh=True)
    path = bundle.file_paths.get(file_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown file_id: {file_id}")
    return FileResponse(path)


@app.get("/v1/assets/{asset_id}")
def get_asset(asset_id: str) -> FileResponse:
    bundle = INDEX_REPO.load(force_refresh=True)
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
