from __future__ import annotations

import shutil
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from gpu_burst import __version__
from gpu_burst.config import user_config_file, vast_api_key_file


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


def _file_presence_check(name: str, path: Path) -> DoctorCheck:
    if path.exists():
        return DoctorCheck(name=name, status="present", detail=str(path))
    return DoctorCheck(name=name, status="missing", detail=str(path))


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
        _file_presence_check("config.toml", user_config_file()),
        _file_presence_check("vast_api_key", vast_api_key_file()),
    ]
    paid_ready = all(check.status == "present" for check in checks)
    return DoctorReport(version=__version__, paid_runtime_ready=paid_ready, checks=checks)


def exit_code(report: DoctorReport) -> int:
    if report.paid_runtime_ready:
        return 0
    if any(check.status == "incompatible" for check in report.checks):
        return 4
    return 2

