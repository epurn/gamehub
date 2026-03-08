from __future__ import annotations

import asyncio
import errno
import os
import shutil
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, cast

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.datastructures import UploadFile

from gamehub_common.ids import make_save_id
from gamehub_common.models import SaveBindingSpec, SaveSpec

from .index_repository import IndexRepository
from .indexer import IndexBundle
from .logging_utils import get_server_logger
from .save_index import SAVES_ROOT_NAME, is_server_generated_save_backup_name

logger = get_server_logger(__name__)
DEFAULT_MAX_SAVE_UPLOAD_BYTES = 128 * 1024 * 1024
SAVE_UPLOAD_CHUNK_BYTES = 1024 * 1024
_SAVE_UPLOAD_LOCKS_GUARD = threading.Lock()
_SAVE_UPLOAD_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


def read_max_save_upload_bytes() -> int:
    raw = os.environ.get("GAMEHUB_MAX_SAVE_UPLOAD_BYTES", str(DEFAULT_MAX_SAVE_UPLOAD_BYTES)).strip()
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_SAVE_UPLOAD_BYTES
    if limit <= 0:
        return DEFAULT_MAX_SAVE_UPLOAD_BYTES
    return limit


def get_save(*, index_repo: IndexRepository, save_id: str) -> FileResponse:
    path = index_repo.resolve_save_path(save_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown save_id: {save_id}")
    return FileResponse(path)


def get_save_bindings(*, index_repo: IndexRepository) -> dict[str, object]:
    bindings = index_repo.save_bindings()
    return {"bindings": [binding.model_dump(mode="json") for binding in bindings]}


class _MultipartReader:
    def __init__(self, stream: AsyncIterator[bytes]) -> None:
        self._stream = stream
        self.buffer = bytearray()
        self.done = False

    async def fill(self) -> bool:
        if self.done:
            return False
        while True:
            try:
                chunk = await anext(self._stream)
            except StopAsyncIteration:
                self.done = True
                return False
            if not chunk:
                continue
            self.buffer.extend(chunk)
            return True

    async def read_line(self, *, max_bytes: int = 64 * 1024) -> bytes:
        while True:
            marker = self.buffer.find(b"\r\n")
            if marker != -1:
                line = bytes(self.buffer[:marker])
                del self.buffer[: marker + 2]
                return line
            if len(self.buffer) > max_bytes:
                raise HTTPException(status_code=400, detail="Malformed multipart payload")
            if not await self.fill():
                raise HTTPException(status_code=400, detail="Malformed multipart payload")


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


@asynccontextmanager
async def _save_upload_lock(save_id: str) -> AsyncIterator[None]:
    lock_key = (id(asyncio.get_running_loop()), save_id)
    with _SAVE_UPLOAD_LOCKS_GUARD:
        lock = _SAVE_UPLOAD_LOCKS.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            _SAVE_UPLOAD_LOCKS[lock_key] = lock
    async with lock:
        yield


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


async def _read_part_headers(reader: _MultipartReader) -> dict[str, str]:
    headers: dict[str, str] = {}
    while True:
        line = await reader.read_line(max_bytes=8 * 1024)
        if not line:
            return headers
        try:
            decoded = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Malformed multipart payload") from exc
        if ":" not in decoded:
            raise HTTPException(status_code=400, detail="Malformed multipart payload")
        key, value = decoded.split(":", 1)
        headers[key.strip().casefold()] = value.strip()


async def _stream_part_payload(
    reader: _MultipartReader,
    boundary: bytes,
    on_chunk: Callable[[bytes], None],
) -> bool:
    boundary_marker = b"\r\n--" + boundary
    scan_keep = len(boundary_marker) + 4

    while True:
        marker = reader.buffer.find(boundary_marker)
        if marker != -1:
            marker_end = marker + len(boundary_marker)
            while len(reader.buffer) < marker_end + 2 and await reader.fill():
                pass
            if len(reader.buffer) < marker_end + 2:
                raise HTTPException(status_code=400, detail="Malformed multipart payload")
            suffix = bytes(reader.buffer[marker_end : marker_end + 2])
            if suffix in {b"\r\n", b"--"}:
                if marker:
                    on_chunk(bytes(reader.buffer[:marker]))
                del reader.buffer[: marker_end + 2]
                if suffix == b"--":
                    if len(reader.buffer) < 2 and not reader.done:
                        await reader.fill()
                    if reader.buffer.startswith(b"\r\n"):
                        del reader.buffer[:2]
                    return True
                return False

            on_chunk(bytes(reader.buffer[: marker + 1]))
            del reader.buffer[: marker + 1]
            continue

        if reader.done:
            raise HTTPException(status_code=400, detail="Malformed multipart payload")
        if len(reader.buffer) > scan_keep:
            emit = len(reader.buffer) - scan_keep
            on_chunk(bytes(reader.buffer[:emit]))
            del reader.buffer[:emit]
        await reader.fill()


async def _parse_multipart_save_request(
    request: Request, *, max_upload_bytes: int
) -> tuple[dict[str, str], UploadFile]:
    content_type = request.headers.get("content-type", "")
    if not content_type.casefold().startswith("multipart/form-data"):
        raise HTTPException(status_code=400, detail="Save upload requires multipart/form-data")

    boundary = _parse_multipart_boundary(content_type).encode("utf-8")
    reader = _MultipartReader(request.stream())
    opening = await reader.read_line()
    if opening != (b"--" + boundary):
        raise HTTPException(status_code=400, detail="Malformed multipart payload")

    fields: dict[str, str] = {}
    file_upload: UploadFile | None = None
    try:
        while True:
            headers = await _read_part_headers(reader)
            disposition = headers.get("content-disposition")
            if not disposition:
                raise HTTPException(status_code=400, detail="Malformed multipart payload")
            params = _parse_disposition_params(disposition)
            name = params.get("name")
            if not name:
                raise HTTPException(status_code=400, detail="Malformed multipart payload")

            filename = params.get("filename")
            if filename is not None:
                if file_upload is not None:
                    raise HTTPException(status_code=400, detail="Save upload must include exactly one file payload")
                spool = SpooledTemporaryFile(max_size=SAVE_UPLOAD_CHUNK_BYTES, mode="w+b")
                bytes_received = 0

                def _write_chunk(chunk: bytes) -> None:
                    nonlocal bytes_received
                    bytes_received += len(chunk)
                    if bytes_received > max_upload_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Save upload exceeds maximum allowed size ({max_upload_bytes} bytes)",
                        )
                    spool.write(chunk)

                try:
                    is_final = await _stream_part_payload(reader, boundary, _write_chunk)
                    spool.seek(0)
                    file_upload = UploadFile(file=cast(BinaryIO, spool), filename=filename)
                except Exception:
                    spool.close()
                    raise
            else:
                field_bytes = bytearray()

                def _append_chunk(chunk: bytes) -> None:
                    field_bytes.extend(chunk)

                is_final = await _stream_part_payload(reader, boundary, _append_chunk)
                try:
                    fields[name] = field_bytes.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise HTTPException(status_code=400, detail="Malformed multipart payload") from exc

            if is_final:
                break
    except Exception:
        if file_upload is not None:
            await file_upload.close()
        raise

    if file_upload is None:
        raise HTTPException(status_code=400, detail="Save upload missing file payload")
    return fields, file_upload


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
    if is_server_generated_save_backup_name(PurePosixPath(normalized).name):
        raise HTTPException(status_code=400, detail="canonical_suffix cannot target a GAMEHUB backup file")
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


def _binding_existing_root_prefix(index_repo: IndexRepository, binding: SaveBindingSpec) -> tuple[str, ...] | None:
    bundle = index_repo.load(check_sources=False)
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


def _validate_binding_suffix(
    index_repo: IndexRepository,
    binding: SaveBindingSpec,
    canonical_suffix: str,
    *,
    target_exists: bool,
) -> None:
    if binding.strategy == "exact_files":
        if not target_exists and canonical_suffix not in set(binding.candidate_filenames):
            raise HTTPException(status_code=400, detail="canonical_suffix is not allowed for this binding")
        return

    root_prefix = _learned_root_prefix(binding, canonical_suffix)
    existing_prefix = _binding_existing_root_prefix(index_repo, binding)
    if existing_prefix is not None and tuple(root_prefix) != tuple(existing_prefix):
        raise HTTPException(status_code=409, detail={"reason": "binding-root-mismatch"})


def _save_spec_from_bundle(bundle: IndexBundle, save_id: str) -> SaveSpec | None:
    for save in bundle.index.saves:
        if save.save_id == save_id:
            return save
    return None


async def _write_save_upload(
    path: Path,
    upload: UploadFile,
    *,
    save_id: str,
    create: bool,
    max_upload_bytes: int,
) -> int:
    part_path = path.with_suffix(f"{path.suffix}.part")
    bytes_written = 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not create:
            backup_path = _backup_existing_save(path)
            if backup_path is not None:
                logger.info("save upload backup created save_id=%s rel_path=%s backup=%s", save_id, path, backup_path)
        with part_path.open("wb") as handle:
            while True:
                chunk = await upload.read(SAVE_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Save upload exceeds maximum allowed size ({max_upload_bytes} bytes)",
                    )
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        part_path.replace(path)
    except HTTPException:
        with suppress(OSError):
            part_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        logger.exception("save upload failed save_id=%s rel_path=%s", save_id, path)
        with suppress(OSError):
            part_path.unlink(missing_ok=True)
        if isinstance(exc, OSError) and exc.errno == errno.EROFS:
            raise HTTPException(
                status_code=500,
                detail="Server data volume is read-only; save uploads require a writable GAMEHUB_DATA_DIR mount",
            ) from exc
        raise HTTPException(status_code=500, detail=f"Failed to store save upload: {exc}") from exc
    return bytes_written


async def put_save(
    save_id: str,
    request: Request,
    response: Response,
    *,
    data_root: Path,
    index_repo: IndexRepository,
    max_upload_bytes: int,
) -> dict[str, object]:
    fields, file_upload = await _parse_multipart_save_request(request, max_upload_bytes=max_upload_bytes)
    binding_id = fields.get("binding_id", "").strip()
    canonical_suffix = _normalize_canonical_suffix(fields.get("canonical_suffix", ""))
    expected_remote_sha256 = fields.get("expected_remote_sha256")
    if expected_remote_sha256 is not None:
        expected_remote_sha256 = expected_remote_sha256.strip() or None

    try:
        if not binding_id:
            raise HTTPException(status_code=400, detail="binding_id is required")

        async with _save_upload_lock(save_id):
            bundle = index_repo.load(force_refresh=True)
            binding = next((item for item in bundle.save_bindings if item.binding_id == binding_id), None)
            if binding is None:
                raise HTTPException(status_code=404, detail=f"Unknown binding_id: {binding_id}")

            rel_path = f"{binding.server_rel_dir}/{canonical_suffix}"
            if make_save_id(rel_path) != save_id:
                raise HTTPException(status_code=400, detail="save_id does not match binding_id + canonical_suffix")

            path = (data_root / Path(*PurePosixPath(rel_path).parts)).resolve()
            saves_root = (data_root / SAVES_ROOT_NAME).resolve()
            if not path.is_relative_to(saves_root):
                raise HTTPException(status_code=400, detail="Resolved save path escapes saves root")

            current = _save_spec_from_bundle(bundle, save_id)
            target_path_exists = path.exists() and path.is_file()
            if current is None and target_path_exists:
                raise _save_conflict_response(reason="target-exists-unindexed", current=None)
            if current is not None and not target_path_exists:
                raise _save_conflict_response(reason="indexed-save-missing-file", current=current)

            target_exists = current is not None
            _validate_binding_suffix(index_repo, binding, canonical_suffix, target_exists=target_exists)

            if not target_exists:
                if expected_remote_sha256 is not None:
                    raise HTTPException(status_code=400, detail="expected_remote_sha256 is only valid for existing saves")
                bytes_written = await _write_save_upload(
                    path,
                    file_upload,
                    save_id=save_id,
                    create=True,
                    max_upload_bytes=max_upload_bytes,
                )
                refreshed_bundle = index_repo.load(force_refresh=True)
                save = _save_spec_from_bundle(refreshed_bundle, save_id)
                if save is None:
                    raise HTTPException(status_code=500, detail=f"Uploaded save missing after refresh: {save_id}")
                logger.info("save create completed save_id=%s rel_path=%s bytes=%d", save_id, save.rel_path, bytes_written)
                response.status_code = 201
                return save.model_dump(mode="json")

            if expected_remote_sha256 is None:
                raise _save_conflict_response(reason="target-exists", current=current)
            if current is None:
                raise HTTPException(status_code=500, detail=f"Indexed save missing for existing upload: {save_id}")
            if current.sha256 != expected_remote_sha256:
                raise _save_conflict_response(reason="remote-sha-mismatch", current=current)

            bytes_written = await _write_save_upload(
                path,
                file_upload,
                save_id=save_id,
                create=False,
                max_upload_bytes=max_upload_bytes,
            )
            refreshed_bundle = index_repo.load(force_refresh=True)
            save = _save_spec_from_bundle(refreshed_bundle, save_id)
            if save is None:
                raise HTTPException(status_code=500, detail=f"Uploaded save missing after refresh: {save_id}")
            logger.info("save upload completed save_id=%s rel_path=%s bytes=%d", save_id, save.rel_path, bytes_written)
            return save.model_dump(mode="json")
    finally:
        await file_upload.close()
