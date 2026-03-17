from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_snapshot_module() -> dict[str, object]:
    return runpy.run_path(str(ROOT / "scripts" / "server_snapshot.py"))


def _write_env_file(path: Path, *, data_root: Path, image_tag: str = "v1.6.0") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"GAMEHUB_DATA_HOST_PATH={data_root}",
                f"GAMEHUB_IMAGE_TAG={image_tag}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_server_data(root: Path) -> None:
    (root / "roms" / "NES").mkdir(parents=True, exist_ok=True)
    (root / "firmware" / "PSX").mkdir(parents=True, exist_ok=True)
    (root / "saves" / "NES" / "Demo" / "battery").mkdir(parents=True, exist_ok=True)
    (root / "roms" / "NES" / "Demo.nes").write_bytes(b"rom")
    (root / "firmware" / "PSX" / "scph5501.bin").write_bytes(b"firmware")
    (root / "saves" / "NES" / "Demo" / "battery" / "save.sav").write_bytes(b"save")


def test_backup_dry_run_reports_manifest_and_inputs(workspace_tempdir, capsys) -> None:
    module = _load_snapshot_module()
    backup_snapshot = module["backup_snapshot"]

    with workspace_tempdir("gamehub-server-snapshot-") as temp_root:
        env_path = temp_root / "docker" / ".env"
        data_root = temp_root / "server-data"
        _seed_server_data(data_root)
        _write_env_file(env_path, data_root=data_root, image_tag="v2.0.0")

        snapshot_path = backup_snapshot(
            env_file=env_path,
            output_dir=temp_root / "snapshots",
            snapshot_name="snapshot-a",
            apply=False,
        )

        output = capsys.readouterr().out
        assert snapshot_path == temp_root / "snapshots" / "snapshot-a"
        assert "mode=dry-run" in output
        assert f"env_file={env_path.resolve(strict=False)}" in output
        assert f"data_root={data_root.resolve(strict=False)}" in output
        assert "image_tag=v2.0.0" in output
        assert "will-write=docker/.env" in output
        assert "will-write=image-tag.txt" in output
        assert "will-write=data/roms/NES/Demo.nes" in output
        assert "will-write=manifest.json" in output


def test_backup_apply_writes_snapshot_manifest_and_checksums(workspace_tempdir) -> None:
    module = _load_snapshot_module()
    backup_snapshot = module["backup_snapshot"]

    with workspace_tempdir("gamehub-server-snapshot-") as temp_root:
        env_path = temp_root / "docker" / ".env"
        data_root = temp_root / "server-data"
        _seed_server_data(data_root)
        _write_env_file(env_path, data_root=data_root, image_tag="v9.9.9")

        snapshot_path = backup_snapshot(
            env_file=env_path,
            output_dir=temp_root / "snapshots",
            snapshot_name="snapshot-b",
            apply=True,
        )

        manifest = json.loads((snapshot_path / "manifest.json").read_text(encoding="utf-8"))
        manifest_paths = {entry["path"] for entry in manifest["files"]}

        assert snapshot_path.exists()
        assert (snapshot_path / "docker" / ".env").read_text(encoding="utf-8") == env_path.read_text(encoding="utf-8")
        assert (snapshot_path / "image-tag.txt").read_text(encoding="utf-8") == "v9.9.9\n"
        assert manifest["image_tag"] == "v9.9.9"
        assert manifest["source"]["env_file"] == str(env_path.resolve(strict=False))
        assert manifest["source"]["data_root"] == str(data_root.resolve(strict=False))
        assert {
            "docker/.env",
            "image-tag.txt",
            "data/roms/NES/Demo.nes",
            "data/firmware/PSX/scph5501.bin",
            "data/saves/NES/Demo/battery/save.sav",
        }.issubset(manifest_paths)


def test_restore_dry_run_reports_replacements(workspace_tempdir, capsys) -> None:
    module = _load_snapshot_module()
    backup_snapshot = module["backup_snapshot"]
    restore_snapshot = module["restore_snapshot"]

    with workspace_tempdir("gamehub-server-snapshot-") as temp_root:
        source_env = temp_root / "source" / "docker" / ".env"
        source_data = temp_root / "source-data"
        _seed_server_data(source_data)
        _write_env_file(source_env, data_root=source_data, image_tag="v1.6.1")
        snapshot_path = backup_snapshot(
            env_file=source_env,
            output_dir=temp_root / "snapshots",
            snapshot_name="snapshot-c",
            apply=True,
        )

        target_env = temp_root / "restore" / "docker" / ".env"
        target_data = temp_root / "restore-data"
        _write_env_file(target_env, data_root=target_data, image_tag="old")
        _seed_server_data(target_data)

        restore_snapshot(
            snapshot_path=snapshot_path,
            env_file=target_env,
            data_root=target_data,
            apply=False,
        )

        output = capsys.readouterr().out
        assert "mode=dry-run" in output
        assert f"replace-file={target_env.resolve(strict=False)}" in output
        assert f"replace-dir={target_data.resolve(strict=False)}" in output
        assert target_env.read_text(encoding="utf-8").startswith("GAMEHUB_DATA_HOST_PATH=")


def test_restore_apply_uses_backup_and_atomic_replace(workspace_tempdir) -> None:
    module = _load_snapshot_module()
    backup_snapshot = module["backup_snapshot"]
    restore_snapshot = module["restore_snapshot"]

    with workspace_tempdir("gamehub-server-snapshot-") as temp_root:
        source_env = temp_root / "source" / "docker" / ".env"
        source_data = temp_root / "source-data"
        _seed_server_data(source_data)
        _write_env_file(source_env, data_root=source_data, image_tag="v1.7.0")
        snapshot_path = backup_snapshot(
            env_file=source_env,
            output_dir=temp_root / "snapshots",
            snapshot_name="snapshot-d",
            apply=True,
        )

        target_env = temp_root / "restore" / "docker" / ".env"
        target_data = temp_root / "restore-data"
        target_data.mkdir(parents=True, exist_ok=True)
        (target_data / "legacy.txt").write_text("legacy-data", encoding="utf-8")
        _write_env_file(target_env, data_root=target_data, image_tag="old-tag")

        restore_snapshot(
            snapshot_path=snapshot_path,
            env_file=target_env,
            data_root=target_data,
            apply=True,
        )

        env_backups = list(target_env.parent.glob(".env.*.bak"))
        data_backups = [path for path in target_data.parent.glob("restore-data.*.bak") if path.is_dir()]

        assert target_env.read_text(encoding="utf-8") == source_env.read_text(encoding="utf-8")
        assert (target_data / "roms" / "NES" / "Demo.nes").read_bytes() == b"rom"
        assert not (target_data / "legacy.txt").exists()
        assert len(env_backups) == 1
        assert "old-tag" in env_backups[0].read_text(encoding="utf-8")
        assert len(data_backups) == 1
        assert (data_backups[0] / "legacy.txt").read_text(encoding="utf-8") == "legacy-data"
