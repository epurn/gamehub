from __future__ import annotations

import gzip
import hashlib
import os
import stat
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal

from gamehub_common.models import (
    FirmwareSpec,
    LibraryIndex,
    SaveBindingSpec,
    SaveSpec,
    ServerIndexStatus,
    ServerSaveUploadStatus,
    ServerStatus,
    TitleEntry,
)

from .indexer import FIRMWARE_ROOT_NAME, ROMS_ROOT_NAME, IndexBundle, build_index
from .logging_utils import get_server_logger
from .save_index import SAVES_ROOT_NAME

logger = get_server_logger(__name__)
DEFAULT_INDEX_POLL_SECONDS = 1.0
DEFAULT_INDEX_STABLE_SECONDS = 2.0


def _timestamp_now_utc() -> datetime:
    return datetime.now(UTC)


def _sanitize_status_error(error: Exception, *, data_root: Path) -> str:
    detail = str(error).strip()
    if detail:
        text = f"{error.__class__.__name__}: {detail}"
    else:
        text = error.__class__.__name__
    for candidate in {str(data_root), str(data_root.resolve())}:
        if candidate:
            text = text.replace(candidate, "<data-root>")
    collapsed = " ".join(text.split())
    if len(collapsed) > 240:
        return collapsed[:237].rstrip() + "..."
    return collapsed


def _path_has_symlink_component(path: Path, *, allowed_root: Path) -> bool:
    try:
        relative_parts = path.relative_to(allowed_root).parts
    except ValueError:
        return True

    current = allowed_root
    if current.is_symlink():
        return True
    for part in relative_parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def validate_served_file_path(path: Path, *, allowed_root: Path) -> Path | None:
    try:
        if not allowed_root.exists() or not allowed_root.is_dir() or allowed_root.is_symlink():
            return None
        if _path_has_symlink_component(path, allowed_root=allowed_root):
            return None
        resolved_root = allowed_root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except OSError:
        return None

    if not resolved_path.is_relative_to(resolved_root):
        return None
    if not resolved_path.is_file():
        return None
    return resolved_path


def _path_signature_fields(path: Path, data_root: Path) -> tuple[str, str, int, int] | None:
    try:
        stat_result = path.lstat()
    except OSError:
        return None

    mode = stat_result.st_mode
    if stat.S_ISLNK(mode):
        kind = "symlink"
    elif stat.S_ISDIR(mode):
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


def _update_signature_tree(
    path: Path,
    *,
    data_root: Path,
    update: Callable[[str, str, int, int], None],
) -> None:
    fields = _path_signature_fields(path, data_root)
    if fields is None:
        return
    update(*fields)
    if fields[1] != "dir":
        return
    for child in _sorted_children(path):
        _update_signature_tree(child, data_root=data_root, update=update)


def _snapshot_data_signature(data_root: Path) -> str:
    digest = hashlib.blake2s(digest_size=16)

    def _update(relative: str, kind: str, size_bytes: int, mtime_ns: int) -> None:
        digest.update(f"{relative}|{kind}|{size_bytes}|{mtime_ns}\n".encode("utf-8"))

    for root_name in ("roms", FIRMWARE_ROOT_NAME, SAVES_ROOT_NAME):
        root = data_root / root_name
        if _path_signature_fields(root, data_root) is None:
            _update(root_name, "missing", 0, 0)
            continue
        _update_signature_tree(root, data_root=data_root, update=_update)

    return digest.hexdigest()


def _rom_entries_by_rel_path(index: LibraryIndex) -> dict[str, TitleEntry]:
    return {title.rom.rel_path: title for title in index.titles}


def _firmware_entries_by_rel_path(index: LibraryIndex) -> dict[str, tuple[str, FirmwareSpec]]:
    firmware_entries: dict[str, tuple[str, FirmwareSpec]] = {}
    for system in index.systems:
        for spec in system.firmware:
            rel_path = f"{FIRMWARE_ROOT_NAME}/{system.name}/{spec.filename}"
            firmware_entries[rel_path] = (system.name, spec)
    return firmware_entries


def _log_index_changes(previous_cache: IndexBundle | None, current_cache: IndexBundle, *, reason: str) -> None:
    if previous_cache is None:
        return

    previous_roms = _rom_entries_by_rel_path(previous_cache.index)
    current_roms = _rom_entries_by_rel_path(current_cache.index)
    previous_firmware = _firmware_entries_by_rel_path(previous_cache.index)
    current_firmware = _firmware_entries_by_rel_path(current_cache.index)
    previous_saves = {save.rel_path: save for save in previous_cache.index.saves}
    current_saves = {save.rel_path: save for save in current_cache.index.saves}

    added_rom_paths = sorted(set(current_roms) - set(previous_roms))
    updated_rom_paths = sorted(
        path
        for path in set(current_roms) & set(previous_roms)
        if current_roms[path].rom.sha256 != previous_roms[path].rom.sha256
    )
    removed_rom_paths = sorted(set(previous_roms) - set(current_roms))

    added_firmware_paths = sorted(set(current_firmware) - set(previous_firmware))
    updated_firmware_paths = sorted(
        path
        for path in set(current_firmware) & set(previous_firmware)
        if current_firmware[path][1].sha256 != previous_firmware[path][1].sha256
    )
    removed_firmware_paths = sorted(set(previous_firmware) - set(current_firmware))
    added_save_paths = sorted(set(current_saves) - set(previous_saves))
    updated_save_paths = sorted(
        path
        for path in set(current_saves) & set(previous_saves)
        if current_saves[path].sha256 != previous_saves[path].sha256
    )
    removed_save_paths = sorted(set(previous_saves) - set(current_saves))

    if not any(
        (
            added_rom_paths,
            updated_rom_paths,
            removed_rom_paths,
            added_firmware_paths,
            updated_firmware_paths,
            removed_firmware_paths,
            added_save_paths,
            updated_save_paths,
            removed_save_paths,
        )
    ):
        return

    logger.info(
        "index contents changed reason=%s roms_added=%d roms_updated=%d roms_removed=%d "
        "firmware_added=%d firmware_updated=%d firmware_removed=%d "
        "saves_added=%d saves_updated=%d saves_removed=%d",
        reason,
        len(added_rom_paths),
        len(updated_rom_paths),
        len(removed_rom_paths),
        len(added_firmware_paths),
        len(updated_firmware_paths),
        len(removed_firmware_paths),
        len(added_save_paths),
        len(updated_save_paths),
        len(removed_save_paths),
    )

    for rel_path in added_rom_paths:
        title = current_roms[rel_path]
        logger.info(
            "indexed new rom file reason=%s system=%s title=%s rel_path=%s",
            reason,
            title.system,
            title.title_name,
            rel_path,
        )
    for rel_path in updated_rom_paths:
        title = current_roms[rel_path]
        logger.info(
            "reindexed rom file reason=%s system=%s title=%s rel_path=%s",
            reason,
            title.system,
            title.title_name,
            rel_path,
        )
    for rel_path in removed_rom_paths:
        title = previous_roms[rel_path]
        logger.info(
            "removed rom file from index reason=%s system=%s title=%s rel_path=%s",
            reason,
            title.system,
            title.title_name,
            rel_path,
        )

    for rel_path in added_firmware_paths:
        system_name, spec = current_firmware[rel_path]
        logger.info(
            "indexed new firmware file reason=%s system=%s filename=%s rel_path=%s",
            reason,
            system_name,
            spec.filename,
            rel_path,
        )
    for rel_path in updated_firmware_paths:
        system_name, spec = current_firmware[rel_path]
        logger.info(
            "reindexed firmware file reason=%s system=%s filename=%s rel_path=%s",
            reason,
            system_name,
            spec.filename,
            rel_path,
        )
    for rel_path in removed_firmware_paths:
        system_name, spec = previous_firmware[rel_path]
        logger.info(
            "removed firmware file from index reason=%s system=%s filename=%s rel_path=%s",
            reason,
            system_name,
            spec.filename,
            rel_path,
        )

    for rel_path in added_save_paths:
        save = current_saves[rel_path]
        logger.info(
            "indexed new save file reason=%s system=%s title_id=%s kind=%s rel_path=%s",
            reason,
            save.system,
            save.title_id,
            save.kind,
            rel_path,
        )
    for rel_path in updated_save_paths:
        save = current_saves[rel_path]
        logger.info(
            "reindexed save file reason=%s system=%s title_id=%s kind=%s rel_path=%s",
            reason,
            save.system,
            save.title_id,
            save.kind,
            rel_path,
        )
    for rel_path in removed_save_paths:
        save = previous_saves[rel_path]
        logger.info(
            "removed save file from index reason=%s system=%s title_id=%s kind=%s rel_path=%s",
            reason,
            save.system,
            save.title_id,
            save.kind,
            rel_path,
        )


class IndexRepository:
    def __init__(
        self,
        data_root: Path,
        refresh_seconds: float = 0.0,
        poll_seconds: float = DEFAULT_INDEX_POLL_SECONDS,
        stable_seconds: float = DEFAULT_INDEX_STABLE_SECONDS,
    ) -> None:
        self._data_root = data_root
        self._cache: IndexBundle | None = None
        self._payload_json: bytes | None = None
        self._payload_gzip: bytes | None = None
        self._source_signature: str | None = None
        self._pending_source_signature: str | None = None
        self._pending_since: float | None = None
        self._pending_since_wall: datetime | None = None
        self._loaded_at: float | None = None
        self._refresh_seconds = max(0.0, float(refresh_seconds))
        self._poll_seconds = max(0.0, float(poll_seconds))
        self._stable_seconds = max(0.0, float(stable_seconds))
        self._last_refresh_reason: str | None = None
        self._last_successful_refresh_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._last_error: str | None = None
        self._lock = threading.Lock()
        self._poll_stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None

    def _should_refresh_for_ttl(self, observed_at: float) -> bool:
        if self._cache is None:
            return True
        if self._refresh_seconds <= 0:
            return False
        if self._loaded_at is None:
            return True
        age_seconds = observed_at - self._loaded_at
        return age_seconds >= self._refresh_seconds

    def _observe_source_signature(self, source_signature: str, observed_at: float) -> bool:
        if self._cache is None:
            return True
        if source_signature == self._source_signature:
            self._pending_source_signature = None
            self._pending_since = None
            self._pending_since_wall = None
            return False
        if self._pending_source_signature != source_signature:
            self._pending_source_signature = source_signature
            self._pending_since = observed_at
            self._pending_since_wall = _timestamp_now_utc()
            logger.info(
                "index refresh pending reason=source_change stable_seconds=%.3f data_root=%s",
                self._stable_seconds,
                self._data_root,
            )
            return self._stable_seconds <= 0
        if self._pending_since is None:
            self._pending_since = observed_at
            self._pending_since_wall = _timestamp_now_utc()
            return self._stable_seconds <= 0
        return (observed_at - self._pending_since) >= self._stable_seconds

    def _rebuild_locked(self, *, source_signature: str | None, reason: str, raise_on_error: bool) -> bool:
        previous_cache = self._cache
        started_at = time.monotonic()
        self._last_refresh_reason = reason
        logger.info("index refresh started reason=%s data_root=%s", reason, self._data_root)
        try:
            cache = build_index(self._data_root)
        except Exception as exc:
            elapsed_seconds = time.monotonic() - started_at
            self._last_failure_at = _timestamp_now_utc()
            self._last_error = _sanitize_status_error(exc, data_root=self._data_root)
            if raise_on_error or self._cache is None:
                logger.exception("index refresh failed reason=%s elapsed_seconds=%.3f", reason, elapsed_seconds)
                raise

            if source_signature is not None and source_signature != self._source_signature:
                self._pending_source_signature = source_signature
                self._pending_since = time.monotonic()
                self._pending_since_wall = _timestamp_now_utc()
            elif self._refresh_seconds > 0:
                self._loaded_at = time.monotonic()
            logger.exception(
                "index refresh failed keeping_cached_snapshot reason=%s elapsed_seconds=%.3f",
                reason,
                elapsed_seconds,
            )
            return False

        self._cache = cache
        self._payload_json = self._cache.index.model_dump_json().encode("utf-8")
        self._payload_gzip = gzip.compress(self._payload_json, compresslevel=5)
        if source_signature is None:
            source_signature = _snapshot_data_signature(self._data_root)
        self._source_signature = source_signature
        self._pending_source_signature = None
        self._pending_since = None
        self._pending_since_wall = None
        self._loaded_at = time.monotonic()
        self._last_successful_refresh_at = _timestamp_now_utc()
        self._last_error = None
        _log_index_changes(previous_cache, self._cache, reason=reason)
        elapsed_seconds = self._loaded_at - started_at
        logger.info(
            "index refresh completed reason=%s elapsed_seconds=%.3f systems=%d titles=%d",
            reason,
            elapsed_seconds,
            len(self._cache.index.systems),
            len(self._cache.index.titles),
        )
        return True

    def load(self, force_refresh: bool = False, *, check_sources: bool = True) -> IndexBundle:
        if force_refresh:
            with self._lock:
                self._rebuild_locked(source_signature=None, reason="forced", raise_on_error=True)
            if self._cache is None:
                raise RuntimeError("Index cache was expected but is missing")
            return self._cache

        source_signature: str | None = None
        observed_at = time.monotonic()
        if check_sources:
            source_signature = _snapshot_data_signature(self._data_root)

        with self._lock:
            if self._cache is None:
                self._rebuild_locked(source_signature=source_signature, reason="initial", raise_on_error=True)
            elif not check_sources:
                return self._cache
            else:
                refresh_for_source_change = False
                if source_signature is not None:
                    refresh_for_source_change = self._observe_source_signature(source_signature, observed_at)
                refresh_for_ttl = False
                if not refresh_for_source_change and self._pending_source_signature is None:
                    refresh_for_ttl = self._should_refresh_for_ttl(observed_at)
                if refresh_for_source_change:
                    self._rebuild_locked(
                        source_signature=source_signature, reason="source_change", raise_on_error=False
                    )
                elif refresh_for_ttl:
                    self._rebuild_locked(source_signature=source_signature, reason="ttl", raise_on_error=False)
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

    def resolve_save_path(self, save_id: str) -> Path | None:
        bundle = self.load(check_sources=False)
        path = bundle.save_paths.get(save_id)
        if path is None:
            return None
        return validate_served_file_path(path, allowed_root=self._data_root / SAVES_ROOT_NAME)

    def resolve_file_path(self, file_id: str) -> Path | None:
        bundle = self.load(check_sources=False)
        path = bundle.file_paths.get(file_id)
        if path is None:
            return None
        return validate_served_file_path(path, allowed_root=self._data_root / ROMS_ROOT_NAME)

    def resolve_asset_path(self, asset_id: str) -> Path | None:
        bundle = self.load(check_sources=False)
        path = bundle.asset_paths.get(asset_id)
        if path is None:
            return None
        return validate_served_file_path(path, allowed_root=self._data_root)

    def resolve_save_spec(self, save_id: str, *, force_refresh: bool = False) -> SaveSpec | None:
        bundle = self.load(force_refresh=force_refresh) if force_refresh else self.load(check_sources=False)
        for save in bundle.index.saves:
            if save.save_id == save_id:
                return save
        return None

    def save_bindings(self, *, force_refresh: bool = False) -> tuple[SaveBindingSpec, ...]:
        bundle = self.load(force_refresh=force_refresh) if force_refresh else self.load(check_sources=False)
        return bundle.save_bindings

    def resolve_save_binding(self, binding_id: str, *, force_refresh: bool = False) -> SaveBindingSpec | None:
        for binding in self.save_bindings(force_refresh=force_refresh):
            if binding.binding_id == binding_id:
                return binding
        return None

    def _poll_loop(self) -> None:
        logger.info(
            "index poller started interval_seconds=%.3f stable_seconds=%.3f data_root=%s",
            self._poll_seconds,
            self._stable_seconds,
            self._data_root,
        )
        while not self._poll_stop_event.wait(self._poll_seconds):
            try:
                self.load(force_refresh=False, check_sources=True)
            except Exception:
                logger.exception("index poll cycle failed data_root=%s", self._data_root)
        logger.info("index poller stopped data_root=%s", self._data_root)

    def start_polling(self) -> None:
        if self._poll_seconds <= 0:
            return
        with self._lock:
            if self._poll_thread is not None and self._poll_thread.is_alive():
                return
            self._poll_stop_event.clear()
            self._poll_thread = threading.Thread(target=self._poll_loop, name="gamehub-index-poller", daemon=True)
            self._poll_thread.start()

    def stop_polling(self) -> None:
        with self._lock:
            thread = self._poll_thread
            if thread is None:
                return
            self._poll_thread = None
            self._poll_stop_event.set()
        if thread is threading.current_thread():
            return
        thread.join(timeout=max(1.0, self._poll_seconds + 1.0))

    def server_status(
        self,
        *,
        server_version: str,
        max_upload_bytes: int,
        backup_keep_limit: int,
    ) -> ServerStatus:
        with self._lock:
            cache = self._cache
            index_status = ServerIndexStatus(
                systems=len(cache.index.systems) if cache is not None else 0,
                titles=len(cache.index.titles) if cache is not None else 0,
                saves=len(cache.index.saves) if cache is not None else 0,
                poll_seconds=self._poll_seconds,
                stable_seconds=self._stable_seconds,
                refresh_seconds=self._refresh_seconds,
                refresh_pending=self._pending_source_signature is not None,
                pending_since=self._pending_since_wall,
                last_refresh_reason=self._last_refresh_reason,
                last_successful_refresh_at=self._last_successful_refresh_at,
                last_failure_at=self._last_failure_at,
                last_error=self._last_error,
            )
            if cache is None:
                status: Literal["ok", "degraded", "starting"] = "starting"
            elif self._last_error is not None:
                status = "degraded"
            else:
                status = "ok"
            return ServerStatus(
                server_version=server_version,
                status=status,
                index=index_status,
                save_upload=ServerSaveUploadStatus(
                    max_upload_bytes=max_upload_bytes,
                    backup_keep_limit=backup_keep_limit,
                ),
            )


def read_non_negative_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return default
    if seconds < 0:
        return default
    return seconds


def read_index_refresh_seconds() -> float:
    return read_non_negative_float_env("GAMEHUB_INDEX_REFRESH_SECONDS", 0.0)


def read_index_poll_seconds() -> float:
    return read_non_negative_float_env("GAMEHUB_INDEX_POLL_SECONDS", DEFAULT_INDEX_POLL_SECONDS)


def read_index_stable_seconds() -> float:
    return read_non_negative_float_env("GAMEHUB_INDEX_STABLE_SECONDS", DEFAULT_INDEX_STABLE_SECONDS)
