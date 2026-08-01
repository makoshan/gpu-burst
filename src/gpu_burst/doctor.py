from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from configparser import ConfigParser
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from gpu_burst import __version__
from gpu_burst.config import (
    Settings,
    aws_credentials_file,
    load_settings,
    runpod_config_file,
    user_config_file,
    vast_api_key_file,
)


class DoctorCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    detail: str


class DoctorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    paid_runtime_ready: bool
    checks: list[DoctorCheck]


def _tool_check(name: str) -> DoctorCheck:
    path = shutil.which(name)
    if path:
        return DoctorCheck(name=name, status="present", detail=path)
    return DoctorCheck(name=name, status="missing", detail="not found on PATH")


def _config_check(path: Path) -> DoctorCheck:
    if not path.exists():
        return DoctorCheck(name="config.toml", status="missing", detail=str(path))
    try:
        with path.open("rb") as handle:
            Settings.model_validate(tomllib.load(handle))
    except (OSError, tomllib.TOMLDecodeError, ValidationError):
        return DoctorCheck(name="config.toml", status="invalid", detail=f"{path}: invalid configuration")
    return DoctorCheck(name="config.toml", status="present", detail=str(path))


def _r2_storage_check(config_path: Path, credentials_path: Path) -> DoctorCheck:
    if not config_path.exists():
        return DoctorCheck(name="r2_storage", status="missing", detail=f"{config_path}: config.toml missing")
    try:
        with config_path.open("rb") as handle:
            settings = Settings.model_validate(tomllib.load(handle))
    except (OSError, tomllib.TOMLDecodeError, ValidationError):
        return DoctorCheck(name="r2_storage", status="invalid", detail=f"{config_path}: invalid configuration")

    storage = settings.storage
    if not storage.endpoint.strip():
        return DoctorCheck(name="r2_storage", status="invalid", detail="storage.endpoint is required")
    if not storage.cache_bucket.strip():
        return DoctorCheck(name="r2_storage", status="invalid", detail="storage.cache_bucket is required")
    if not storage.jobs_bucket.strip():
        return DoctorCheck(name="r2_storage", status="invalid", detail="storage.jobs_bucket is required")
    if not storage.aws_profile.strip():
        return DoctorCheck(name="r2_storage", status="invalid", detail="storage.aws_profile is required")
    if not credentials_path.exists():
        return DoctorCheck(name="r2_storage", status="missing", detail=f"{credentials_path}: AWS credentials missing")

    parser = ConfigParser()
    try:
        parser.read(credentials_path)
    except (OSError, UnicodeError):
        return DoctorCheck(name="r2_storage", status="invalid", detail=f"{credentials_path}: unreadable")

    if not parser.has_section(storage.aws_profile):
        return DoctorCheck(
            name="r2_storage",
            status="invalid",
            detail=f"{credentials_path}: missing AWS profile {storage.aws_profile}",
        )

    return DoctorCheck(
        name="r2_storage",
        status="present",
        detail=f"profile={storage.aws_profile} endpoint={storage.endpoint} buckets={storage.cache_bucket},{storage.jobs_bucket}",
    )


def _vast_key_check(path: Path) -> DoctorCheck:
    if not path.exists():
        return DoctorCheck(name="vast_api_key", status="missing", detail=str(path))
    try:
        has_value = bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        return DoctorCheck(name="vast_api_key", status="invalid", detail=f"{path}: unreadable")
    if not has_value:
        return DoctorCheck(name="vast_api_key", status="invalid", detail=f"{path}: empty")
    try:
        permissions = path.stat().st_mode & 0o777
    except OSError:
        return DoctorCheck(name="vast_api_key", status="invalid", detail=f"{path}: unreadable")
    if permissions & 0o077:
        return DoctorCheck(name="vast_api_key", status="invalid", detail=f"{path}: unsafe permissions")
    return DoctorCheck(name="vast_api_key", status="present", detail=str(path))


def _runpod_key_check(path: Path) -> DoctorCheck:
    if not path.exists():
        return DoctorCheck(name="runpod_api_key", status="missing", detail=str(path))
    try:
        permissions = path.stat().st_mode & 0o777
    except OSError:
        return DoctorCheck(name="runpod_api_key", status="invalid", detail=f"{path}: unreadable")
    if permissions & 0o077:
        return DoctorCheck(name="runpod_api_key", status="invalid", detail=f"{path}: unsafe permissions")
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
        has_value = bool(str(payload.get("default", {}).get("api_key", "")).strip())
    except (OSError, tomllib.TOMLDecodeError, TypeError, AttributeError):
        return DoctorCheck(name="runpod_api_key", status="invalid", detail=f"{path}: invalid configuration")
    if not has_value:
        return DoctorCheck(name="runpod_api_key", status="invalid", detail=f"{path}: empty")
    return DoctorCheck(name="runpod_api_key", status="present", detail=str(path))


def _sky_runpod_check() -> DoctorCheck:
    try:
        result = subprocess.run(
            ["sky", "check", "runpod"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return DoctorCheck(
            name="sky_runpod",
            status="missing",
            detail='install the matching "skypilot[runpod]" extra and run sky check runpod',
        )
    if result.returncode != 0:
        return DoctorCheck(
            name="sky_runpod",
            status="missing",
            detail='install the matching "skypilot[runpod]" extra and run sky check runpod',
        )
    return DoctorCheck(name="sky_runpod", status="present", detail="sky check runpod passed")


def build_report() -> DoctorReport:
    config_path = user_config_file()
    try:
        provider = load_settings().provider.active
    except (OSError, tomllib.TOMLDecodeError, ValidationError):
        provider = "vast"
    checks = [
        DoctorCheck(
            name="python",
            status="present" if sys.version_info[:2] == (3, 13) else "incompatible",
            detail=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        _tool_check("uv"),
        _tool_check("sky"),
        _tool_check("s5cmd"),
        _tool_check("docker"),
        DoctorCheck(name="active_provider", status="present", detail=provider),
        _config_check(config_path),
        _r2_storage_check(config_path, aws_credentials_file()),
    ]
    if provider == "runpod":
        checks.extend([_sky_runpod_check(), _runpod_key_check(runpod_config_file())])
    else:
        checks.extend([_tool_check("vastai"), _vast_key_check(vast_api_key_file())])
    paid_ready = all(check.status == "present" for check in checks)
    return DoctorReport(version=__version__, paid_runtime_ready=paid_ready, checks=checks)


def exit_code(report: DoctorReport) -> int:
    if report.paid_runtime_ready:
        return 0
    if any(check.status == "invalid" for check in report.checks):
        return 3
    if any(check.status == "incompatible" for check in report.checks):
        return 4
    return 2
