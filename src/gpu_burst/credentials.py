from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_runpod_config(api_key: str, path: Path) -> None:
    key = api_key.strip()
    if not key:
        raise ValueError("RunPod API key is empty")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    content = f"[default]\napi_key = {json.dumps(key)}\n"
    fd, temporary_name = tempfile.mkstemp(prefix=".config.toml.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        temporary_path.replace(path)
        path.chmod(0o600)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
