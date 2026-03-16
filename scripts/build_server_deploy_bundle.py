from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SOURCES = (
    Path("docker/compose.yaml"),
    Path("docs/deployment-server.md"),
    Path("docs/dev-to-prod-server-migration.md"),
    Path("docs/runbook.md"),
    Path("scripts/verify_server_deploy.py"),
    Path("scripts/verify_server_deploy.ps1"),
)
ENV_TEMPLATE_PATH = Path("docker/.env.template")


def render_env_template(*, image_tag: str) -> str:
    text = (REPO_ROOT / ENV_TEMPLATE_PATH).read_text(encoding="utf-8")
    lines = []
    replaced = False
    for line in text.splitlines():
        if line.startswith("GAMEHUB_IMAGE_TAG="):
            lines.append(f"GAMEHUB_IMAGE_TAG={image_tag}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        raise RuntimeError("docker/.env.template is missing GAMEHUB_IMAGE_TAG")
    return "\n".join(lines) + "\n"


def build_bundle(*, ref_name: str, output_dir: Path) -> Path:
    if not ref_name.strip():
        raise ValueError("ref_name must not be empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"gamehub-server-deploy-{ref_name}.zip"
    env_template = render_env_template(image_tag=ref_name)

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in BUNDLE_SOURCES:
            archive.write(REPO_ROOT / source, arcname=source.as_posix())
        archive.writestr(ENV_TEMPLATE_PATH.as_posix(), env_template)

    return bundle_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the GAMEHUB server deploy bundle zip.")
    parser.add_argument("--ref-name", required=True, help="Release ref/tag name to pin in the bundle.")
    parser.add_argument("--output-dir", default="dist", help="Directory where the bundle zip should be written.")
    args = parser.parse_args(argv)

    bundle_path = build_bundle(ref_name=args.ref_name, output_dir=(REPO_ROOT / args.output_dir))
    print(bundle_path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
