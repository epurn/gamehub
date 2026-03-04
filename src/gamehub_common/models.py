from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

HEX_SHA256 = r"^[a-f0-9]{64}$"


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FirmwareSpec(StrictBaseModel):
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=HEX_SHA256)
    required: bool = True


class SystemSpec(StrictBaseModel):
    name: str = Field(min_length=1)
    rom_extensions: tuple[str, ...] = Field(min_length=1)
    default_emulator: str = Field(min_length=1)
    launch_template: str = Field(min_length=1)
    firmware: tuple[FirmwareSpec, ...] = ()

    @field_validator("rom_extensions")
    @classmethod
    def normalize_extensions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in value))
        if len(normalized) != len(set(normalized)):
            raise ValueError("rom_extensions cannot contain duplicates")
        return normalized


class AssetSpec(StrictBaseModel):
    asset_id: str = Field(min_length=1)
    kind: Literal["grid", "hero", "logo", "icon"]
    rel_path: str = Field(min_length=1)
    sha256: str = Field(pattern=HEX_SHA256)
    size_bytes: int = Field(ge=0)


class RomSpec(StrictBaseModel):
    file_id: str = Field(min_length=1)
    rel_path: str = Field(min_length=1)
    sha256: str = Field(pattern=HEX_SHA256)
    size_bytes: int = Field(ge=0)
    extension: str = Field(min_length=2)

    @field_validator("extension")
    @classmethod
    def normalize_extension(cls, value: str) -> str:
        return value.lower() if value.startswith(".") else f".{value.lower()}"


class TitleEntry(StrictBaseModel):
    title_id: str = Field(min_length=1)
    system: str = Field(min_length=1)
    title_name: str = Field(min_length=1)
    title_rel_dir: str = Field(min_length=1)
    emulator: str = Field(min_length=1)
    launch_template: str = Field(min_length=1)
    rom: RomSpec
    assets: tuple[AssetSpec, ...] = ()


class SaveSpec(StrictBaseModel):
    save_id: str = Field(min_length=1)
    title_id: str = Field(min_length=1)
    system: str = Field(min_length=1)
    kind: Literal["battery", "memory_card", "per_game"]
    rel_path: str = Field(min_length=1)
    sha256: str = Field(pattern=HEX_SHA256)
    size_bytes: int = Field(ge=0)
    updated_at: datetime
    portable: bool


class SaveBindingSpec(StrictBaseModel):
    binding_id: str = Field(min_length=1)
    title_id: str = Field(min_length=1)
    system: str = Field(min_length=1)
    kind: Literal["battery", "memory_card", "per_game"]
    server_rel_dir: str = Field(min_length=1)
    local_root: Literal[
        "retroarch_saves", "retroarch_saves_psx", "pcsx2_memcards", "dolphin_gc", "dolphin_wii", "azahar_sdmc"
    ]
    strategy: Literal["exact_files", "learned_tree"]
    candidate_filenames: tuple[str, ...] = ()
    learn_rule: Literal["dolphin_gc_gci_tree", "dolphin_wii_title_tree", "azahar_title_data_tree"] | None = None
    portable: bool

    @field_validator("candidate_filenames")
    @classmethod
    def validate_candidate_filenames(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value if item.strip())
        if len(normalized) != len(value):
            raise ValueError("candidate_filenames cannot contain empty values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("candidate_filenames cannot contain duplicates")
        return normalized

    @field_validator("server_rel_dir")
    @classmethod
    def validate_server_rel_dir(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if not normalized:
            raise ValueError("server_rel_dir must be a relative path")
        if "\\" in normalized or normalized.startswith("/"):
            raise ValueError("server_rel_dir must be a normalized POSIX relative path")
        if any(part in {"", ".", ".."} for part in normalized.split("/")):
            raise ValueError("server_rel_dir must not contain traversal segments")
        return normalized

    @field_validator("learn_rule")
    @classmethod
    def validate_strategy_fields(
        cls,
        value: Literal["dolphin_gc_gci_tree", "dolphin_wii_title_tree", "azahar_title_data_tree"] | None,
        info: ValidationInfo,
    ) -> Literal["dolphin_gc_gci_tree", "dolphin_wii_title_tree", "azahar_title_data_tree"] | None:
        strategy = info.data.get("strategy")
        candidates = info.data.get("candidate_filenames", ())
        if strategy == "exact_files":
            if value is not None:
                raise ValueError("learn_rule must be null for exact_files bindings")
            if not candidates:
                raise ValueError("exact_files bindings require candidate_filenames")
        if strategy == "learned_tree":
            if value is None:
                raise ValueError("learned_tree bindings require learn_rule")
            if candidates:
                raise ValueError("learned_tree bindings cannot declare candidate_filenames")
        return value


class SaveBindingCatalog(StrictBaseModel):
    bindings: tuple[SaveBindingSpec, ...] = ()


class LibraryIndex(StrictBaseModel):
    index_version: Literal[1] = 1
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    systems: tuple[SystemSpec, ...] = ()
    titles: tuple[TitleEntry, ...] = ()
    saves: tuple[SaveSpec, ...] = ()
