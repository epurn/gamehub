from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class LibraryIndex(StrictBaseModel):
    index_version: Literal[1] = 1
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    systems: tuple[SystemSpec, ...] = ()
    titles: tuple[TitleEntry, ...] = ()
