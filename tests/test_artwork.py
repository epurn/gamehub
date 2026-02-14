from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

import httpx

from gamehub_cli.artwork import SgdbArtworkPipeline, SgdbClient, redact_secret
from gamehub_cli.config import GamehubConfig
from gamehub_cli.sync import _build_artwork_assignments
from gamehub_common.models import LibraryIndex, RomSpec, SystemSpec, TitleEntry


@contextmanager
def _workspace_tempdir(prefix: str):
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp_local"
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = root / f"{prefix}{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _index_with_titles(*titles: TitleEntry) -> LibraryIndex:
    system = SystemSpec(
        name="NES",
        rom_extensions=(".nes",),
        default_emulator="retroarch",
        launch_template='"{emulator}" "{rom}"',
        firmware=(),
    )
    return LibraryIndex(index_version=1, systems=(system,), titles=titles)


def _title(title_id: str, title_name: str, file_id: str) -> TitleEntry:
    return TitleEntry(
        title_id=title_id,
        system="NES",
        title_name=title_name,
        title_rel_dir=f"NES/{title_name}",
        emulator="retroarch",
        launch_template='"{emulator}" "{rom}"',
        rom=RomSpec(
            file_id=file_id,
            rel_path=f"roms/NES/{title_name}.nes",
            sha256="a" * 64,
            size_bytes=123,
            extension=".nes",
        ),
        assets=(),
    )


def test_redact_secret_masks_sgdb_api_key() -> None:
    assert redact_secret(None) == "<unset>"
    assert redact_secret("abc") == "***"
    assert redact_secret("abcdefghi") == "abc...ghi"


def test_sgdb_client_retries_transient_then_parses_game_id() -> None:
    request_count = {"search": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search/autocomplete/Super Mario Bros"):
            request_count["search"] += 1
            if request_count["search"] == 1:
                return httpx.Response(status_code=429, headers={"Retry-After": "0"}, json={"success": False})
            return httpx.Response(status_code=200, json={"success": True, "data": [{"id": 42}]})
        return httpx.Response(status_code=404, json={"success": False})

    client = SgdbClient(
        "test-key",
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _seconds: None,
    )
    try:
        assert client.find_game_id("Super Mario Bros") == 42
    finally:
        client.close()

    assert request_count["search"] == 2


def test_sgdb_client_download_to_cache_skips_existing_file() -> None:
    request_count = {"download": 0}
    payload = b"grid-image"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cdn/grid.png":
            request_count["download"] += 1
            return httpx.Response(
                status_code=200,
                content=payload,
                headers={"Content-Length": str(len(payload))},
            )
        return httpx.Response(status_code=404, json={"success": False})

    with _workspace_tempdir("gamehub-artwork-") as temp_root:
        destination = temp_root / "cache" / "grid.png"
        client = SgdbClient("test-key", transport=httpx.MockTransport(handler))
        try:
            assert client.download_to_cache("https://cdn.example/cdn/grid.png", destination) is True
            assert destination.read_bytes() == payload
            assert client.download_to_cache("https://cdn.example/cdn/grid.png", destination) is False
        finally:
            client.close()

    assert request_count["download"] == 1


def test_sgdb_client_download_falls_back_to_no_auth_on_401() -> None:
    payload = b"fallback-image"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cdn/protected.png":
            if request.headers.get("Authorization"):
                return httpx.Response(status_code=401)
            return httpx.Response(
                status_code=200,
                content=payload,
                headers={"Content-Length": str(len(payload))},
            )
        return httpx.Response(status_code=404, json={"success": False})

    with _workspace_tempdir("gamehub-artwork-") as temp_root:
        destination = temp_root / "cache" / "protected.png"
        client = SgdbClient("test-key", transport=httpx.MockTransport(handler))
        try:
            assert client.download_to_cache("https://cdn.example/cdn/protected.png", destination) is True
            assert destination.read_bytes() == payload
        finally:
            client.close()


def test_sgdb_pipeline_continues_on_lookup_failure() -> None:
    payload = b"grid-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/search/autocomplete/Good Game"):
            return httpx.Response(status_code=200, json={"success": True, "data": [{"id": 111}]})
        if path.endswith("/search/autocomplete/Bad Game"):
            return httpx.Response(status_code=500, json={"success": False})
        if path.endswith("/grids/game/111"):
            return httpx.Response(
                status_code=200,
                json={"success": True, "data": [{"url": "https://cdn.example/assets/good-grid.png"}]},
            )
        if path == "/assets/good-grid.png":
            return httpx.Response(status_code=200, content=payload, headers={"Content-Length": str(len(payload))})
        return httpx.Response(status_code=404, json={"success": False})

    good = _title("title_good", "Good Game", "file_good")
    bad = _title("title_bad", "Bad Game", "file_bad")
    with _workspace_tempdir("gamehub-artwork-") as temp_root:
        client = SgdbClient(
            "test-key",
            transport=httpx.MockTransport(handler),
            sleep_fn=lambda _seconds: None,
            max_retries=1,
        )
        try:
            pipeline = SgdbArtworkPipeline(client, cache_dir=temp_root / "cache", kinds=("grid",))
            result = pipeline.sync((good, bad))
        finally:
            client.close()

        assert len(result.bundles) == 1
        assert result.bundles[0].title_id == "title_good"
        assert result.downloaded == 1
        assert any("Bad Game" in warning for warning in result.warnings)


def test_sgdb_pipeline_tries_next_candidate_url_after_download_401() -> None:
    payload = b"good-grid"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/search/autocomplete/Retry Game"):
            return httpx.Response(status_code=200, json={"success": True, "data": [{"id": 987}]})
        if path.endswith("/grids/game/987"):
            return httpx.Response(
                status_code=200,
                json={
                    "success": True,
                    "data": [
                        {"url": "https://cdn.example/assets/unauthorized-grid.png"},
                        {"url": "https://cdn.example/assets/usable-grid.png"},
                    ],
                },
            )
        if path == "/assets/unauthorized-grid.png":
            return httpx.Response(status_code=401)
        if path == "/assets/usable-grid.png":
            return httpx.Response(status_code=200, content=payload, headers={"Content-Length": str(len(payload))})
        return httpx.Response(status_code=404, json={"success": False})

    title = _title("title_retry", "Retry Game", "file_retry")
    with _workspace_tempdir("gamehub-artwork-") as temp_root:
        client = SgdbClient("test-key", transport=httpx.MockTransport(handler))
        try:
            pipeline = SgdbArtworkPipeline(client, cache_dir=temp_root / "cache", kinds=("grid",))
            result = pipeline.sync((title,))
        finally:
            client.close()

        assert len(result.bundles) == 1
        assert result.downloaded == 1
        assert not result.warnings


def test_sgdb_client_prefers_steam_compatible_artwork_formats() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/grids/game/99"):
            return httpx.Response(
                status_code=200,
                json={
                    "success": True,
                    "data": [
                        {"url": "https://cdn.example/assets/grid.webp"},
                        {"url": "https://cdn.example/assets/grid.png"},
                        {"url": "https://cdn.example/assets/grid.jpg"},
                    ],
                },
            )
        return httpx.Response(status_code=404, json={"success": False})

    client = SgdbClient("test-key", transport=httpx.MockTransport(handler))
    try:
        urls = client.resolve_asset_urls(99, "grid")
    finally:
        client.close()

    assert urls[:3] == (
        "https://cdn.example/assets/grid.png",
        "https://cdn.example/assets/grid.jpg",
        "https://cdn.example/assets/grid.webp",
    )


def test_build_artwork_assignments_dry_run_reports_plan(capsys) -> None:
    index = _index_with_titles(_title("title_mario", "Super Mario Bros", "file_mario"))
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path("state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key="sgdb-secret-key",
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "icon"),
    )

    assignments = _build_artwork_assignments(
        config=config,
        index=index,
        dry_run=True,
        timeout_seconds=10.0,
        verbose=False,
    )

    assert assignments == {}
    output = capsys.readouterr().out
    assert "SGDB dry-run" in output
    assert "Super Mario Bros" in output
    assert "sgd...key" in output
