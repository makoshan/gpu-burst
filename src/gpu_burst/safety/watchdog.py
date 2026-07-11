from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from gpu_burst.ledger import Ledger


TERMINAL_STATES = {"SUCCEEDED", "FAILED", "DEGRADED", "FAILED_TEARDOWN"}


@dataclass(frozen=True)
class StaleTask:
    task_id: str
    task_state: str
    updated_at: str
    age_minutes: int
    provider: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_state": self.task_state,
            "updated_at": self.updated_at,
            "age_minutes": self.age_minutes,
            "provider": self.provider,
        }


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def find_stale_tasks(ledger: Ledger, *, max_age_minutes: int) -> list[StaleTask]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=max_age_minutes)
    stale: list[StaleTask] = []
    tasks_root = ledger.root / "tasks"
    if not tasks_root.exists():
        return []

    for manifest_path in sorted(tasks_root.glob("*/manifest.json")):
        manifest = ledger.read_manifest(manifest_path.parent.name)
        task_state = str(manifest.get("task_state", "UNKNOWN"))
        if task_state in TERMINAL_STATES:
            continue
        updated_at = str(manifest.get("updated_at") or manifest.get("created_at") or "")
        if not updated_at:
            continue
        updated = _parse_timestamp(updated_at)
        if updated > cutoff:
            continue
        age_minutes = int((now - updated).total_seconds() // 60)
        stale.append(
            StaleTask(
                task_id=str(manifest["task_id"]),
                task_state=task_state,
                updated_at=updated_at,
                age_minutes=age_minutes,
                provider=dict(manifest.get("provider") or {}),
            )
        )
    return stale
