from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".3ds", ".cci", ".cxi"}
EXPECTED_MAGIC_BY_EXTENSION = {
    ".3ds": b"NCSD",
    ".cci": b"NCSD",
    ".cxi": b"NCCH",
}
HEADER_MAGIC_OFFSET = 0x100
HEADER_MAGIC_SIZE = 4


@dataclass(frozen=True)
class AuditRow:
    path: str
    extension: str
    size_bytes: int
    sha256: str
    status: str
    detail: str
    manual_action: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _read_magic(path: Path) -> bytes:
    with path.open("rb") as handle:
        handle.seek(HEADER_MAGIC_OFFSET)
        return handle.read(HEADER_MAGIC_SIZE)


def _audit_file(path: Path, rom_root: Path) -> AuditRow:
    extension = path.suffix.lower()
    size_bytes = path.stat().st_size
    sha256 = _sha256_file(path)
    rel_path = path.relative_to(rom_root).as_posix()

    if extension not in SUPPORTED_EXTENSIONS:
        return AuditRow(
            path=rel_path,
            extension=extension,
            size_bytes=size_bytes,
            sha256=sha256,
            status="unsupported_extension",
            detail="GAMEHUB N3DS only indexes .3ds/.cci/.cxi",
            manual_action="Re-export/rebuild ROM as decrypted .3ds/.cci/.cxi outside GAMEHUB.",
        )

    if size_bytes < HEADER_MAGIC_OFFSET + HEADER_MAGIC_SIZE:
        return AuditRow(
            path=rel_path,
            extension=extension,
            size_bytes=size_bytes,
            sha256=sha256,
            status="invalid_file_size",
            detail="File is too small to contain expected 3DS header.",
            manual_action="Re-copy or re-dump the ROM.",
        )

    expected_magic = EXPECTED_MAGIC_BY_EXTENSION[extension]
    observed_magic = _read_magic(path)
    if observed_magic != expected_magic:
        observed = observed_magic.decode("ascii", errors="replace")
        expected = expected_magic.decode("ascii")
        return AuditRow(
            path=rel_path,
            extension=extension,
            size_bytes=size_bytes,
            sha256=sha256,
            status="header_mismatch",
            detail=f"Expected {expected} at 0x100, found {observed!r}.",
            manual_action="Re-export/rebuild ROM in a format Azahar can load.",
        )

    return AuditRow(
        path=rel_path,
        extension=extension,
        size_bytes=size_bytes,
        sha256=sha256,
        status="looks_supported",
        detail="Container header matches expected format.",
        manual_action="No action.",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit N3DS ROM files for GAMEHUB/Azahar compatibility. "
            "This script does not decrypt files."
        )
    )
    parser.add_argument(
        "--rom-root",
        required=True,
        type=Path,
        help="Path to N3DS ROM directory (for example: D:/GamehubOutput/roms/N3DS)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of table text.",
    )
    return parser.parse_args()


def _print_table(rows: list[AuditRow]) -> None:
    print("path\tstatus\tdetail\tmanual_action")
    for row in rows:
        print(f"{row.path}\t{row.status}\t{row.detail}\t{row.manual_action}")


def main() -> int:
    args = _parse_args()
    rom_root: Path = args.rom_root.expanduser().resolve()
    if not rom_root.exists():
        raise SystemExit(f"ROM root does not exist: {rom_root}")
    if not rom_root.is_dir():
        raise SystemExit(f"ROM root is not a directory: {rom_root}")

    rows = [_audit_file(path, rom_root) for path in sorted(rom_root.iterdir(), key=lambda item: item.name.lower()) if path.is_file()]
    if args.json:
        print(json.dumps([row.__dict__ for row in rows], indent=2))
    else:
        _print_table(rows)

    supported = sum(1 for row in rows if row.status == "looks_supported")
    print(f"\nSummary: total={len(rows)} supported={supported} needs_review={len(rows) - supported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())