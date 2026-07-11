from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from json import JSONDecodeError
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


@dataclass(frozen=True)
class ScanError:
    task_id: str
    error: str

    def as_dict(self) -> dict[str, str]:
        return {"task_id": self.task_id, "error": self.error}


@dataclass(frozen=True)
class WatchdogScan:
    stale_tasks: list[StaleTask]
    scan_errors: list[ScanError]


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def scan_stale_tasks(ledger: Ledger, *, max_age_minutes: int) -> WatchdogScan:
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=max_age_minutes)
    stale: list[StaleTask] = []
    errors: list[ScanError] = []
    tasks_root = ledger.root / "tasks"
    if not tasks_root.exists():
        return WatchdogScan(stale_tasks=[], scan_errors=[])

    for manifest_path in sorted(tasks_root.glob("*/manifest.json")):
        directory_task_id = manifest_path.parent.name
        try:
            manifest = ledger.read_manifest(directory_task_id)
        except (JSONDecodeError, UnicodeError):
            errors.append(ScanError(task_id=directory_task_id, error="invalid manifest JSON"))
            continue
        except OSError:
            errors.append(ScanError(task_id=directory_task_id, error="manifest is unreadable"))
            continue
        if not isinstance(manifest, dict):
            errors.append(ScanError(task_id=directory_task_id, error="manifest JSON must be an object"))
            continue
        task_state = str(manifest.get("task_state", "UNKNOWN"))
        updated_at = str(manifest.get("updated_at") or manifest.get("created_at") or "")
        if not updated_at:
            errors.append(ScanError(task_id=directory_task_id, error="manifest timestamp is missing"))
            continue
        try:
            updated = _parse_timestamp(updated_at)
        except ValueError:
            errors.append(ScanError(task_id=directory_task_id, error="invalid updated_at timestamp"))
            continue
        if updated.tzinfo is None or updated.utcoffset() is None:
            errors.append(ScanError(task_id=directory_task_id, error="updated_at timestamp must include timezone"))
            continue
        manifest_task_id = manifest.get("task_id")
        if not isinstance(manifest_task_id, str) or manifest_task_id != directory_task_id:
            errors.append(
                ScanError(
                    task_id=directory_task_id,
                    error="manifest task_id is missing or does not match its directory",
                )
            )
            continue
        provider = manifest.get("provider") or {}
        if not isinstance(provider, dict):
            errors.append(ScanError(task_id=directory_task_id, error="provider must be an object"))
            continue
        if task_state in TERMINAL_STATES:
            continue
        if updated > cutoff:
            continue
        age_minutes = int((now - updated).total_seconds() // 60)
        stale.append(
            StaleTask(
                task_id=manifest_task_id,
                task_state=task_state,
                updated_at=updated_at,
                age_minutes=age_minutes,
                provider=provider,
            )
        )
    return WatchdogScan(stale_tasks=stale, scan_errors=errors)


def find_stale_tasks(ledger: Ledger, *, max_age_minutes: int) -> list[StaleTask]:
    return scan_stale_tasks(ledger, max_age_minutes=max_age_minutes).stale_tasks
