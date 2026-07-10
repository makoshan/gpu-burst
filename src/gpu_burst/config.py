from __future__ import annotations

import os
from pathlib import Path


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

