from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class SkyExecutionError(RuntimeError):
    """A sanitized SkyPilot lifecycle failure."""


@dataclass(frozen=True)
class SkyLaunchPlan:
    cluster_name: str
    task_file: Path
    autodown_idle_minutes: int

    def launch_args(self) -> list[str]:
        return [
            "sky",
            "launch",
            "-c",
            self.cluster_name,
            str(self.task_file),
            "--idle-minutes-to-autostop",
            str(self.autodown_idle_minutes),
            "--down",
            "-y",
        ]

    def down_args(self) -> list[str]:
        return ["sky", "down", "-y", self.cluster_name]


def execute_sky_launch(
    plan: SkyLaunchPlan,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    on_teardown: Callable[[], None] | None = None,
) -> None:
    launch_issue: str | None = None
    callback_issue: str | None = None
    down_issue: str | None = None
    try:
        try:
            launch = runner(plan.launch_args(), capture_output=True, text=True, check=False)
            if launch.returncode != 0:
                launch_issue = "sky launch failed"
        except OSError:
            launch_issue = "sky launch could not start"
    finally:
        if on_teardown is not None:
            try:
                on_teardown()
            except Exception:
                callback_issue = "teardown state update failed"
        try:
            down = runner(plan.down_args(), capture_output=True, text=True, check=False)
            if down.returncode != 0:
                down_issue = "sky down failed"
        except OSError:
            down_issue = "sky down could not start"

    issues = [issue for issue in (launch_issue, callback_issue, down_issue) if issue]
    if issues:
        raise SkyExecutionError("; ".join(issues))
