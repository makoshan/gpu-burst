from __future__ import annotations

import shutil
import sys
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from gpu_burst import __version__
from gpu_burst.config import Settings, user_config_file, vast_api_key_file


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


def build_report() -> DoctorReport:
    checks = [
        DoctorCheck(
            name="python",
            status="present" if sys.version_info[:2] == (3, 13) else "incompatible",
            detail=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        _tool_check("uv"),
        _tool_check("sky"),
        _tool_check("vastai"),
        _tool_check("s5cmd"),
        _tool_check("docker"),
        _config_check(user_config_file()),
        _vast_key_check(vast_api_key_file()),
    ]
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
