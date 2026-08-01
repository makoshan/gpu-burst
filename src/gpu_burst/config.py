from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VastSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datacenter_only: bool = True
    max_hourly_cost_usd: float = Field(default=0.80, gt=0)
    default_gpu: str = "RTX4090"


class RunPodSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cloud_type: Literal["COMMUNITY", "SECURE"] = "COMMUNITY"
    max_hourly_cost_usd: float = Field(default=0.75, gt=0)
    default_gpu: str = "RTX4090"
    allowed_cuda_versions: list[str] = Field(default_factory=lambda: ["13.0"])


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: Literal["vast", "runpod"] = "vast"
    vast: VastSettings = Field(default_factory=VastSettings)
    runpod: RunPodSettings = Field(default_factory=RunPodSettings)


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


def runpod_config_file() -> Path:
    override = os.environ.get("GPU_BURST_RUNPOD_CONFIG_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".runpod" / "config.toml"


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
        settings = Settings()
    else:
        with path.open("rb") as handle:
            settings = Settings.model_validate(tomllib.load(handle))
    provider_override = os.environ.get("GPU_BURST_PROVIDER")
    if provider_override:
        payload = settings.model_dump()
        payload["provider"]["active"] = provider_override
        settings = Settings.model_validate(payload)
    return settings
