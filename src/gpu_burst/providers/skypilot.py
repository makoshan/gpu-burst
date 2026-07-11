from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
            "--down",
            str(self.autodown_idle_minutes),
            "-y",
        ]

    def down_args(self) -> list[str]:
        return ["sky", "down", "-y", self.cluster_name]

