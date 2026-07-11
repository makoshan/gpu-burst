from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class VastSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datacenter_only: bool = True
    max_hourly_cost_usd: float = Field(default=0.80, gt=0)
    default_gpu: str = "RTX4090"


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vast: VastSettings = Field(default_factory=VastSettings)


class StorageSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cache_bucket: str = "gpu-burst-cache"
    jobs_bucket: str = "gpu-burst-jobs"
    endpoint: str = ""
    aws_profile: str = "gpu-burst-r2"


class SafetySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autodown_idle_minutes: int = Field(default=10, ge=1)
    watchdog_interval_minutes: int = Field(default=5, ge=1)
    max_unverified_age_minutes: int = Field(default=20, ge=1)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)


def data_home() -> Path:
    override = os.environ.get("GPU_BURST_HOME")
    if override:
        return Path(override).expanduser()
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "gpu-burst"
    return Path.home() / ".local" / "share" / "gpu-burst"


def vast_api_key_file() -> Path:
    override = os.environ.get("GPU_BURST_VAST_API_KEY_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "vastai" / "vast_api_key"


def user_config_file() -> Path:
    override = os.environ.get("GPU_BURST_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "gpu-burst" / "config.toml"


def aws_credentials_file() -> Path:
    override = os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".aws" / "credentials"


def load_settings() -> Settings:
    path = user_config_file()
    if not path.exists():
        return Settings()
    with path.open("rb") as handle:
        return Settings.model_validate(tomllib.load(handle))
