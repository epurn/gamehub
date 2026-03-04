from __future__ import annotations

import errno
import os
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from gamehub_common.ids import make_save_id
from gamehub_common.models import SaveBindingSpec, SaveSpec
from gamehub_common.version import __version__

from .index_repository import (
    IndexRepository,
    read_index_poll_seconds,
    read_index_refresh_seconds,
    read_index_stable_seconds,
)
from .indexer import FIRMWARE_ROOT_NAME, SAVES_ROOT_NAME
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


def _backup_existing_save(path: Path) -> Path | None:
    if not path.exists() or not path.is_file():
        return None

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}.{suffix}.bak")
        suffix += 1

    shutil.copy2(path, candidate)
    return candidate


def _save_conflict_response(*, reason: str, current: SaveSpec | None, status_code: int = 409) -> HTTPException:
    payload: dict[str, object] = {"reason": reason}
    if current is not None:
        payload["current"] = current.model_dump(mode="json")
    return HTTPException(status_code=status_code, detail=payload)


def _parse_multipart_boundary(content_type: str) -> str:
    for raw_part in content_type.split(";"):
        part = raw_part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip().casefold() != "boundary":
            continue
        boundary = value.strip().strip('"')
        if boundary:
            return boundary
    raise HTTPException(status_code=400, detail="Missing multipart boundary")


def _parse_disposition_params(value: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for raw_part in value.split(";"):
        part = raw_part.strip()
        if "=" not in part:
            continue
        key, param_value = part.split("=", 1)
        params[key.strip().casefold()] = param_value.strip().strip('"')
    return params


async def _parse_multipart_save_request(request: Request) -> tuple[dict[str, str], bytes]:
    content_type = request.headers.get("content-type", "")
    if not content_type.casefold().startswith("multipart/form-data"):
        raise HTTPException(status_code=400, detail="Save upload requires multipart/form-data")

    boundary = _parse_multipart_boundary(content_type)
    delimiter = f"--{boundary}".encode("utf-8")
    body = await request.body()
    fields: dict[str, str] = {}
    file_bytes: bytes | None = None

    for raw_chunk in body.split(delimiter):
        chunk = raw_chunk.lstrip(b"\r\n")
        if not chunk or chunk in {b"--", b"--\r\n"}:
            continue
        if chunk.endswith(b"--"):
            chunk = chunk[:-2]
        chunk = chunk.rstrip(b"\r\n")
        header_blob, separator, payload = chunk.partition(b"\r\n\r\n")
        if not separator:
            continue

        headers: dict[str, str] = {}
        for header_line in header_blob.decode("utf-8", errors="ignore").split("\r\n"):
            if ":" not in header_line:
                continue
            key, value = header_line.split(":", 1)
            headers[key.strip().casefold()] = value.strip()
        disposition = headers.get("content-disposition")
        if not disposition:
            continue
        params = _parse_disposition_params(disposition)
        name = params.get("name")
        if not name:
            continue
        if "filename" in params:
            file_bytes = payload
            continue
        fields[name] = payload.decode("utf-8", errors="strict")

    if file_bytes is None:
        raise HTTPException(status_code=400, detail="Save upload missing file payload")
    return fields, file_bytes


def _normalize_canonical_suffix(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise HTTPException(status_code=400, detail="canonical_suffix is required")
    if value.startswith("/") or "\\" in value:
        raise HTTPException(status_code=400, detail="canonical_suffix must be a normalized POSIX relative path")
    parts = PurePosixPath(value).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail="canonical_suffix contains invalid path segments")
    normalized = PurePosixPath(*parts).as_posix()
    if normalized != value:
        raise HTTPException(status_code=400, detail="canonical_suffix must be normalized")
    return normalized


def _is_hex_segment(value: str, length: int) -> bool:
    if len(value) != length:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def _learned_root_prefix(binding: SaveBindingSpec, canonical_suffix: str) -> tuple[str, ...]:
    parts = PurePosixPath(canonical_suffix).parts
    if binding.learn_rule == "dolphin_gc_gci_tree":
        if len(parts) < 3 or parts[0] not in {"USA", "EUR", "JAP"} or parts[1] not in {"Card A", "Card B"}:
            raise HTTPException(status_code=400, detail="canonical_suffix does not match dolphin_gc_gci_tree")
        return parts[:2]
    if binding.learn_rule == "dolphin_wii_title_tree":
        if (
            len(parts) < 4
            or parts[0] != "title"
            or not _is_hex_segment(parts[1], 8)
            or not _is_hex_segment(parts[2], 8)
        ):
            raise HTTPException(status_code=400, detail="canonical_suffix does not match dolphin_wii_title_tree")
        return parts[:3]
    if binding.learn_rule == "azahar_title_data_tree":
        if (
            len(parts) < 5
            or parts[0] != "title"
            or not _is_hex_segment(parts[1], 8)
            or not _is_hex_segment(parts[2], 8)
            or parts[3] != "data"
        ):
            raise HTTPException(status_code=400, detail="canonical_suffix does not match azahar_title_data_tree")
        return parts[:4]
    raise HTTPException(status_code=400, detail="Unsupported learned-tree rule")


def _binding_existing_root_prefix(binding: SaveBindingSpec) -> tuple[str, ...] | None:
    bundle = INDEX_REPO.load(check_sources=False)
    suffixes: list[str] = []
    prefix = f"{binding.server_rel_dir}/"
    for save in bundle.index.saves:
        if save.rel_path.startswith(prefix):
            suffixes.append(save.rel_path[len(prefix) :])
    if not suffixes:
        return None
    roots = {_learned_root_prefix(binding, suffix) for suffix in suffixes}
    if len(roots) != 1:
        raise HTTPException(status_code=500, detail="Inconsistent learned-tree root in indexed saves")
    return next(iter(roots))


def _validate_binding_suffix(binding: SaveBindingSpec, canonical_suffix: str, *, target_exists: bool) -> None:
    if binding.strategy == "exact_files":
        if not target_exists and canonical_suffix not in set(binding.candidate_filenames):
            raise HTTPException(status_code=400, detail="canonical_suffix is not allowed for this binding")
        return

    root_prefix = _learned_root_prefix(binding, canonical_suffix)
    existing_prefix = _binding_existing_root_prefix(binding)
    if existing_prefix is not None and tuple(root_prefix) != tuple(existing_prefix):
        raise HTTPException(status_code=409, detail={"reason": "binding-root-mismatch"})


def _write_save_bytes(path: Path, payload: bytes, *, save_id: str, create: bool) -> int:
    part_path = path.with_suffix(f"{path.suffix}.part")
    bytes_written = 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not create:
            backup_path = _backup_existing_save(path)
            if backup_path is not None:
                logger.info("save upload backup created save_id=%s rel_path=%s backup=%s", save_id, path, backup_path)
        with part_path.open("wb") as handle:
            handle.write(payload)
            bytes_written = len(payload)
            handle.flush()
            os.fsync(handle.fileno())
        part_path.replace(path)
    except Exception as exc:
        logger.exception("save upload failed save_id=%s rel_path=%s", save_id, path)
        try:
            part_path.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, OSError) and exc.errno == errno.EROFS:
            raise HTTPException(
                status_code=500,
                detail="Server data volume is read-only; save uploads require a writable GAMEHUB_DATA_DIR mount",
            ) from exc
        raise HTTPException(status_code=500, detail=f"Failed to store save upload: {exc}") from exc
    return bytes_written


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


@app.get("/v1/save-bindings")
def get_save_bindings() -> dict[str, object]:
    bindings = INDEX_REPO.save_bindings()
    return {"bindings": [binding.model_dump(mode="json") for binding in bindings]}


@app.put("/v1/saves/{save_id}")
async def put_save(save_id: str, request: Request, response: Response) -> dict[str, object]:
    fields, file_bytes = await _parse_multipart_save_request(request)
    binding_id = fields.get("binding_id", "").strip()
    canonical_suffix = _normalize_canonical_suffix(fields.get("canonical_suffix", ""))
    expected_remote_sha256 = fields.get("expected_remote_sha256")
    if expected_remote_sha256 is not None:
        expected_remote_sha256 = expected_remote_sha256.strip() or None

    if not binding_id:
        raise HTTPException(status_code=400, detail="binding_id is required")

    binding = INDEX_REPO.resolve_save_binding(binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail=f"Unknown binding_id: {binding_id}")

    rel_path = f"{binding.server_rel_dir}/{canonical_suffix}"
    if make_save_id(rel_path) != save_id:
        raise HTTPException(status_code=400, detail="save_id does not match binding_id + canonical_suffix")

    path = (DATA_ROOT / Path(*PurePosixPath(rel_path).parts)).resolve()
    saves_root = (DATA_ROOT / SAVES_ROOT_NAME).resolve()
    if not path.is_relative_to(saves_root):
        raise HTTPException(status_code=400, detail="Resolved save path escapes saves root")

    current = INDEX_REPO.resolve_save_spec(save_id)
    target_exists = current is not None and path.exists()
    _validate_binding_suffix(binding, canonical_suffix, target_exists=target_exists)

    if not target_exists:
        if expected_remote_sha256 is not None:
            raise HTTPException(status_code=400, detail="expected_remote_sha256 is only valid for existing saves")
        bytes_written = _write_save_bytes(path, file_bytes, save_id=save_id, create=True)
        save = INDEX_REPO.resolve_save_spec(save_id, force_refresh=True)
        if save is None:
            raise HTTPException(status_code=500, detail=f"Uploaded save missing after refresh: {save_id}")
        logger.info("save create completed save_id=%s rel_path=%s bytes=%d", save_id, save.rel_path, bytes_written)
        response.status_code = 201
        return save.model_dump(mode="json")

    if expected_remote_sha256 is None:
        raise HTTPException(status_code=400, detail="expected_remote_sha256 is required for existing saves")
    if current is None:
        raise HTTPException(status_code=500, detail=f"Indexed save missing for existing upload: {save_id}")
    if current.sha256 != expected_remote_sha256:
        raise _save_conflict_response(reason="remote-sha-mismatch", current=current)

    bytes_written = _write_save_bytes(path, file_bytes, save_id=save_id, create=False)
    save = INDEX_REPO.resolve_save_spec(save_id, force_refresh=True)
    if save is None:
        raise HTTPException(status_code=500, detail=f"Uploaded save missing after refresh: {save_id}")
    logger.info("save upload completed save_id=%s rel_path=%s bytes=%d", save_id, save.rel_path, bytes_written)
    return save.model_dump(mode="json")


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
