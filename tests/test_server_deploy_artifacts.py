from __future__ import annotations

import runpy
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_binds_to_configured_host_interface_and_wires_upload_limit() -> None:
    text = (ROOT / "docker" / "compose.yaml").read_text(encoding="utf-8")

    assert "${GAMEHUB_SERVER_BIND_ADDRESS:-127.0.0.1}:${GAMEHUB_SERVER_PORT:-8000}:8000" in text
    assert "GAMEHUB_MAX_SAVE_UPLOAD_BYTES: ${GAMEHUB_MAX_SAVE_UPLOAD_BYTES:-}" in text


def test_env_template_exposes_bind_address_and_upload_limit() -> None:
    text = (ROOT / "docker" / ".env.template").read_text(encoding="utf-8")

    assert "GAMEHUB_SERVER_BIND_ADDRESS=127.0.0.1" in text
    assert "GAMEHUB_MAX_SAVE_UPLOAD_BYTES=" in text
    assert "Prefer a pinned release tag" in text


def test_build_server_deploy_bundle_includes_expected_files_and_pins_release_tag(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-bundle-") as temp_dir:
        module = runpy.run_path(str(ROOT / "scripts" / "build_server_deploy_bundle.py"))
        build_bundle = module["build_bundle"]
        bundle_path = build_bundle(ref_name="v9.9.9", output_dir=temp_dir)

        with zipfile.ZipFile(bundle_path) as archive:
            names = set(archive.namelist())
            env_text = archive.read("docker/.env.template").decode("utf-8")

        assert names == {
            "docker/compose.yaml",
            "docker/.env.template",
            "docs/deployment-server.md",
            "docs/runbook.md",
            "scripts/verify_server_deploy.py",
            "scripts/verify_server_deploy.ps1",
        }
        assert "GAMEHUB_IMAGE_TAG=v9.9.9" in env_text
        assert "GAMEHUB_SERVER_BIND_ADDRESS=127.0.0.1" in env_text


def test_release_client_workflow_uses_bundle_script() -> None:
    text = (ROOT / ".github" / "workflows" / "release-client.yml").read_text(encoding="utf-8")

    assert "python scripts/build_server_deploy_bundle.py --ref-name" in text


def test_audit_workflow_runs_server_container_smoke() -> None:
    text = (ROOT / ".github" / "workflows" / "audit-regression-gates.yml").read_text(encoding="utf-8")

    assert "server-container-smoke" in text
    assert "python3 scripts/verify_server_deploy.py --base-url http://127.0.0.1:18000 --wait-seconds 30" in text


def test_release_server_workflow_gates_publish_on_container_smoke() -> None:
    text = (ROOT / ".github" / "workflows" / "release-server.yml").read_text(encoding="utf-8")

    assert "smoke:" in text
    assert "needs: smoke" in text
    assert "python3 scripts/verify_server_deploy.py --base-url http://127.0.0.1:18000 --wait-seconds 30" in text


def test_deployment_docs_reference_portable_verifier_and_first_live_rules() -> None:
    deployment = (ROOT / "docs" / "deployment-server.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    release_process = (ROOT / "docs" / "release-process.md").read_text(encoding="utf-8")

    assert "scripts/verify_server_deploy.py" in deployment
    assert "GAMEHUB_SERVER_BIND_ADDRESS" in deployment
    assert "pinned release tag" in deployment
    assert "no symlinks" in runbook
    assert "scripts/verify_server_deploy.py" in release_process
