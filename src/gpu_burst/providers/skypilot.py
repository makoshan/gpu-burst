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
    bootstrap_task_file: Path | None = None

    def launch_args(self) -> list[str]:
        return [
            "sky",
            "launch",
            "-c",
            self.cluster_name,
            str(self.bootstrap_task_file or self.task_file),
            "--idle-minutes-to-autostop",
            str(self.autodown_idle_minutes),
            "--down",
            "-y",
        ]

    def down_args(self) -> list[str]:
        return ["sky", "down", "-y", self.cluster_name]

    def exec_args(self) -> list[str]:
        return ["sky", "exec", self.cluster_name, str(self.task_file), "-y"]


def execute_sky_launch(
    plan: SkyLaunchPlan,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    on_launched: Callable[[], None] | None = None,
    on_teardown: Callable[[], None] | None = None,
) -> None:
    launch_issue: str | None = None
    launched_cb_issue: str | None = None
    exec_issue: str | None = None
    callback_issue: str | None = None
    down_issue: str | None = None
    try:
        try:
            launch = runner(plan.launch_args(), capture_output=True, text=True, check=False)
            if launch.returncode != 0:
                launch_issue = "sky launch failed"
        except OSError:
            launch_issue = "sky launch could not start"
        if on_launched is not None:
            try:
                on_launched()
            except Exception:
                launched_cb_issue = "post-launch observation failed"
        if plan.bootstrap_task_file is not None and launch_issue is None and launched_cb_issue is None:
            try:
                execution = runner(plan.exec_args(), capture_output=True, text=True, check=False)
                if execution.returncode != 0:
                    exec_issue = "sky exec failed"
            except OSError:
                exec_issue = "sky exec could not start"
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

    issues = [
        issue
        for issue in (launch_issue, launched_cb_issue, exec_issue, callback_issue, down_issue)
        if issue
    ]
    if issues:
        raise SkyExecutionError("; ".join(issues))
