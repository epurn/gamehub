from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

SNAPSHOT_VERSION = 1
DEFAULT_ENV_FILE = Path("docker/.env")
DEFAULT_OUTPUT_DIR = Path("snapshots")
IMAGE_TAG_FILENAME = "image-tag.txt"
MANIFEST_FILENAME = "manifest.json"


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1].strip()
        values[key.strip()] = normalized
    return values


def _write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _copy_file_with_fsync(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())


def _iter_snapshot_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _snapshot_manifest(*, snapshot_root: Path, env_file: Path, data_root: Path, image_tag: str) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for file_path in _iter_snapshot_files(snapshot_root):
        if file_path.name == MANIFEST_FILENAME:
            continue
        relative = file_path.relative_to(snapshot_root).as_posix()
        files.append(
            {
                "path": relative,
                "sha256": _sha256_file(file_path),
                "size_bytes": file_path.stat().st_size,
            }
        )
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "image_tag": image_tag,
        "source": {
            "env_file": str(env_file),
            "data_root": str(data_root),
        },
        "files": files,
    }


def _snapshot_name(snapshot_name: str | None) -> str:
    normalized = (snapshot_name or "").strip()
    return normalized or f"gamehub-server-snapshot-{_timestamp()}"


def _unique_backup_path(path: Path) -> Path:
    stamp = _timestamp()
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    collision = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}.{collision}.bak")
        collision += 1
    return candidate


def _validate_snapshot(snapshot_path: Path) -> dict[str, object]:
    manifest_path = snapshot_path / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise ValueError(f"Snapshot manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"Snapshot manifest is invalid: {manifest_path}")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError(f"Snapshot manifest is missing file entries: {manifest_path}")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"Snapshot manifest entry is invalid: {entry!r}")
        relative = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError(f"Snapshot manifest entry is incomplete: {entry!r}")
        file_path = snapshot_path / relative
        if not file_path.exists():
            raise ValueError(f"Snapshot file listed in manifest is missing: {file_path}")
        actual = _sha256_file(file_path)
        if actual != expected:
            raise ValueError(f"Snapshot checksum mismatch for {file_path}: expected {expected} got {actual}")
    return manifest


def _resolve_data_root(*, env_file: Path, explicit_data_root: Path | None) -> Path:
    if explicit_data_root is not None:
        return explicit_data_root.expanduser().resolve(strict=False)
    values = _read_env_file(env_file)
    raw_data_root = values.get("GAMEHUB_DATA_HOST_PATH", "").strip()
    if not raw_data_root:
        raise ValueError(f"{env_file} is missing GAMEHUB_DATA_HOST_PATH")
    return Path(raw_data_root).expanduser().resolve(strict=False)


def _resolve_image_tag(env_file: Path) -> str:
    values = _read_env_file(env_file)
    image_tag = values.get("GAMEHUB_IMAGE_TAG", "").strip()
    return image_tag or "latest"


def _stage_snapshot_tree(*, env_file: Path, data_root: Path, image_tag: str, stage_root: Path) -> None:
    _copy_file_with_fsync(env_file, stage_root / "docker" / ".env")
    shutil.copytree(data_root, stage_root / "data", dirs_exist_ok=False)
    _write_text_file(stage_root / IMAGE_TAG_FILENAME, f"{image_tag}\n")
    manifest = _snapshot_manifest(snapshot_root=stage_root, env_file=env_file, data_root=data_root, image_tag=image_tag)
    _write_text_file(stage_root / MANIFEST_FILENAME, json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def backup_snapshot(
    *,
    env_file: Path,
    output_dir: Path,
    snapshot_name: str | None = None,
    data_root: Path | None = None,
    apply: bool,
    reporter: Callable[[str], None] = print,
) -> Path:
    resolved_env_file = env_file.expanduser().resolve(strict=False)
    if not resolved_env_file.exists():
        raise ValueError(f"Env file not found: {resolved_env_file}")
    resolved_data_root = _resolve_data_root(env_file=resolved_env_file, explicit_data_root=data_root)
    if not resolved_data_root.exists() or not resolved_data_root.is_dir():
        raise ValueError(f"Data root not found or not a directory: {resolved_data_root}")
    resolved_output_dir = output_dir.expanduser().resolve(strict=False)
    snapshot_path = resolved_output_dir / _snapshot_name(snapshot_name)
    image_tag = _resolve_image_tag(resolved_env_file)

    manifest_paths = [
        "docker/.env",
        IMAGE_TAG_FILENAME,
        *[
            (Path("data") / path.relative_to(resolved_data_root)).as_posix()
            for path in _iter_snapshot_files(resolved_data_root)
        ],
        MANIFEST_FILENAME,
    ]
    mode = "apply" if apply else "dry-run"
    reporter(f"server-snapshot\tbackup\tmode={mode}\tenv_file={resolved_env_file}\tdata_root={resolved_data_root}")
    reporter(f"server-snapshot\tbackup\timage_tag={image_tag}\tsnapshot={snapshot_path}")
    for relative in manifest_paths:
        reporter(f"server-snapshot\tbackup\twill-write={relative}")
    if not apply:
        return snapshot_path

    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    if snapshot_path.exists():
        raise ValueError(f"Snapshot path already exists: {snapshot_path}")
    stage_root = Path(tempfile.mkdtemp(prefix=f".{snapshot_path.name}.", dir=resolved_output_dir))
    try:
        _stage_snapshot_tree(
            env_file=resolved_env_file,
            data_root=resolved_data_root,
            image_tag=image_tag,
            stage_root=stage_root,
        )
        stage_root.replace(snapshot_path)
    except Exception:
        shutil.rmtree(stage_root, ignore_errors=True)
        raise
    reporter(f"server-snapshot\tbackup\tcreated={snapshot_path}")
    return snapshot_path


def _restore_target_data_root(
    *, snapshot_path: Path, manifest: dict[str, object], env_file: Path, explicit: Path | None
) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve(strict=False)
    if env_file.exists():
        values = _read_env_file(env_file)
        raw = values.get("GAMEHUB_DATA_HOST_PATH", "").strip()
        if raw:
            return Path(raw).expanduser().resolve(strict=False)
    source = manifest.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("data_root"), str):
        raise ValueError(f"Snapshot manifest is missing source data root: {snapshot_path / MANIFEST_FILENAME}")
    return Path(str(source["data_root"])).expanduser().resolve(strict=False)


def _backup_existing_file(path: Path, reporter: Callable[[str], None]) -> Path | None:
    if not path.exists():
        return None
    backup_path = _unique_backup_path(path)
    _copy_file_with_fsync(path, backup_path)
    reporter(f"server-snapshot\trestore\tbackup-created={backup_path}\toriginal={path}")
    return backup_path


def _backup_existing_directory(path: Path, reporter: Callable[[str], None]) -> Path | None:
    if not path.exists():
        return None
    backup_path = _unique_backup_path(path)
    path.replace(backup_path)
    reporter(f"server-snapshot\trestore\tbackup-created={backup_path}\toriginal={path}")
    return backup_path


def _stage_directory_copy(source: Path, destination_parent: Path, name: str) -> Path:
    destination_parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=destination_parent))
    shutil.rmtree(stage_root)
    shutil.copytree(source, stage_root)
    return stage_root


def restore_snapshot(
    *,
    snapshot_path: Path,
    env_file: Path,
    data_root: Path | None = None,
    apply: bool,
    reporter: Callable[[str], None] = print,
) -> None:
    resolved_snapshot_path = snapshot_path.expanduser().resolve(strict=False)
    if not resolved_snapshot_path.exists() or not resolved_snapshot_path.is_dir():
        raise ValueError(f"Snapshot path not found: {resolved_snapshot_path}")
    manifest = _validate_snapshot(resolved_snapshot_path)
    resolved_env_file = env_file.expanduser().resolve(strict=False)
    resolved_data_root = _restore_target_data_root(
        snapshot_path=resolved_snapshot_path,
        manifest=manifest,
        env_file=resolved_env_file,
        explicit=data_root,
    )
    mode = "apply" if apply else "dry-run"
    reporter(f"server-snapshot\trestore\tmode={mode}\tsnapshot={resolved_snapshot_path}")
    reporter(f"server-snapshot\trestore\treplace-file={resolved_env_file}")
    reporter(f"server-snapshot\trestore\treplace-dir={resolved_data_root}")
    if not apply:
        return

    snapshot_env_file = resolved_snapshot_path / "docker" / ".env"
    snapshot_data_root = resolved_snapshot_path / "data"
    if not snapshot_env_file.exists():
        raise ValueError(f"Snapshot is missing docker/.env: {snapshot_env_file}")
    if not snapshot_data_root.exists() or not snapshot_data_root.is_dir():
        raise ValueError(f"Snapshot is missing data root: {snapshot_data_root}")

    resolved_env_file.parent.mkdir(parents=True, exist_ok=True)
    temp_env_fd, temp_env_name = tempfile.mkstemp(prefix=f".{resolved_env_file.name}.", dir=resolved_env_file.parent)
    os.close(temp_env_fd)
    temp_env_path = Path(temp_env_name)
    try:
        _copy_file_with_fsync(snapshot_env_file, temp_env_path)
        _backup_existing_file(resolved_env_file, reporter)
        temp_env_path.replace(resolved_env_file)
        reporter(f"server-snapshot\trestore\trestored-file={resolved_env_file}")
    finally:
        temp_env_path.unlink(missing_ok=True)

    staged_data_root = _stage_directory_copy(snapshot_data_root, resolved_data_root.parent, resolved_data_root.name)
    backup_data_root = None
    try:
        if resolved_data_root.exists() and not resolved_data_root.is_dir():
            raise ValueError(f"Restore target exists but is not a directory: {resolved_data_root}")
        backup_data_root = _backup_existing_directory(resolved_data_root, reporter)
        staged_data_root.replace(resolved_data_root)
        reporter(f"server-snapshot\trestore\trestored-dir={resolved_data_root}")
    except Exception:
        if backup_data_root is not None and not resolved_data_root.exists():
            backup_data_root.replace(resolved_data_root)
        raise
    finally:
        if staged_data_root.exists():
            shutil.rmtree(staged_data_root, ignore_errors=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Back up or restore a GAMEHUB server deployment snapshot.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser(
        "backup", help="Create a backup snapshot of docker/.env and the server data root."
    )
    backup_parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="Path to docker/.env.")
    backup_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory that will contain snapshot directories.",
    )
    backup_parser.add_argument(
        "--snapshot-name", type=str, default=None, help="Optional explicit snapshot directory name."
    )
    backup_parser.add_argument("--data-root", type=Path, default=None, help="Override the server data root path.")
    backup_parser.add_argument("--apply", action="store_true", help="Write the snapshot directory. Default is dry-run.")

    restore_parser = subparsers.add_parser(
        "restore", help="Restore docker/.env and the server data root from a snapshot."
    )
    restore_parser.add_argument("snapshot", type=Path, help="Path to a snapshot directory created by this tool.")
    restore_parser.add_argument(
        "--env-file", type=Path, default=DEFAULT_ENV_FILE, help="Restore docker/.env to this path."
    )
    restore_parser.add_argument("--data-root", type=Path, default=None, help="Override the restore target data root.")
    restore_parser.add_argument("--apply", action="store_true", help="Perform the restore. Default is dry-run.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            backup_snapshot(
                env_file=args.env_file,
                output_dir=args.output_dir,
                snapshot_name=args.snapshot_name,
                data_root=args.data_root,
                apply=args.apply,
            )
            return 0
        restore_snapshot(
            snapshot_path=args.snapshot,
            env_file=args.env_file,
            data_root=args.data_root,
            apply=args.apply,
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"server-snapshot\terror\t{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
