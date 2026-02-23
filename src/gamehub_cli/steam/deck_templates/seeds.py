from __future__ import annotations

from pathlib import Path

_DECK_TEMPLATE_SEED_WII_FILENAME = "wii_0.vdf"
_DECK_TEMPLATE_SEED_N3DS_FILENAME = "3ds_0.vdf"
_DECK_TEMPLATE_WII_FILENAME = "gamehub_wii.vdf"
_DECK_TEMPLATE_N3DS_FILENAME = "gamehub_3ds.vdf"

DECK_TEMPLATE_SYSTEM_ORDER = ("Wii", "N3DS")
_DECK_TEMPLATE_SEED_ROOT = Path(__file__).resolve().parents[1] / "template_seeds" / "steamdeck"
DECK_TEMPLATE_SEED_BY_SYSTEM = {
    "Wii": _DECK_TEMPLATE_SEED_ROOT / "wii_gc" / _DECK_TEMPLATE_SEED_WII_FILENAME,
    "N3DS": _DECK_TEMPLATE_SEED_ROOT / "n3ds" / _DECK_TEMPLATE_SEED_N3DS_FILENAME,
}
DECK_TEMPLATE_FILENAMES_BY_SYSTEM = {
    "Wii": (_DECK_TEMPLATE_WII_FILENAME,),
    "N3DS": (_DECK_TEMPLATE_N3DS_FILENAME,),
}
DECK_TEMPLATE_DISABLED_SYSTEMS = {"GC"}


def seed_path_for_system(system_name: str) -> Path | None:
    return DECK_TEMPLATE_SEED_BY_SYSTEM.get(system_name)


def template_filenames_for_system(system_name: str) -> tuple[str, ...]:
    return DECK_TEMPLATE_FILENAMES_BY_SYSTEM.get(system_name, ())


def template_selection_name_for_system(system_name: str) -> str:
    filenames = template_filenames_for_system(system_name)
    if not filenames:
        raise RuntimeError(f"Steam Deck template sync failed: no template filename for system '{system_name}'")
    first_name = filenames[0]
    if first_name.casefold().endswith(".vdf"):
        return first_name[:-4]
    return first_name


def load_seed_payloads(required_systems: list[str]) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for system_name in required_systems:
        seed_path = seed_path_for_system(system_name)
        if seed_path is None:
            raise RuntimeError(f"Steam Deck template sync failed: no seed mapping for system '{system_name}'")
        if not seed_path.exists():
            raise RuntimeError(
                f"Steam Deck template sync failed: missing template seed for {system_name} ({seed_path})"
            )
        try:
            payloads[system_name] = seed_path.read_bytes()
        except OSError as exc:
            raise RuntimeError(
                f"Steam Deck template sync failed: failed reading seed for {system_name} ({seed_path}): {exc}"
            ) from exc
    return payloads
