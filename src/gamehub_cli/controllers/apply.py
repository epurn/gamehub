from __future__ import annotations

from typing import Callable

from ..common.config import GamehubConfig
from .apply_azahar import apply_azahar_profile
from .apply_dolphin import apply_dolphin_profile
from .apply_pcsx2 import apply_pcsx2_profile
from .profiles import PROFILE_KBM, VALID_PROFILES, profile_name_for_controller_count


def apply_controller_profile(
    config: GamehubConfig,
    *,
    emulator_name: str,
    controller_count: int,
    verbose: bool = False,
    writer: Callable[[str], None] = print,
) -> str:
    profile_name = profile_name_for_controller_count(controller_count)
    return apply_named_controller_profile(
        config,
        emulator_name=emulator_name,
        profile_name=profile_name,
        verbose=verbose,
        writer=writer,
    )


def apply_named_controller_profile(
    config: GamehubConfig,
    *,
    emulator_name: str,
    profile_name: str,
    verbose: bool = False,
    writer: Callable[[str], None] = print,
) -> str:
    normalized_name = emulator_name.casefold()
    selected_profile = profile_name if profile_name in VALID_PROFILES else PROFILE_KBM

    if "pcsx2" in normalized_name:
        targets = apply_pcsx2_profile(config, selected_profile)
    elif "dolphin" in normalized_name:
        targets = apply_dolphin_profile(config, selected_profile)
    elif "azahar" in normalized_name:
        targets = apply_azahar_profile(config, selected_profile)
    else:
        raise ValueError(f"Unsupported controller profile emulator: {emulator_name}")

    if verbose:
        for target in targets:
            writer(
                f"controller-autoconfig\tapplied\temulator={normalized_name}\tprofile={selected_profile}\ttarget={target}"
            )
    return selected_profile
