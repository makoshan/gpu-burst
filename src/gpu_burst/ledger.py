from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Ledger:
    def __init__(self, root: Path):
        self.root = Path(root)

    def task_dir(self, task_id: str) -> Path:
        return self.root / "tasks" / task_id

    def create_task(self, task_id: str, task: dict[str, Any]) -> None:
        task_dir = self.task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write_json(task_dir / "task.json", task)

    def write_quote(self, task_id: str, quote: dict[str, Any]) -> None:
        self._atomic_write_json(self.task_dir(task_id) / "quote.json", quote)

    def write_manifest(self, task_id: str, manifest: dict[str, Any]) -> None:
        self._atomic_write_json(self.task_dir(task_id) / "manifest.json", manifest)

    def read_manifest(self, task_id: str) -> dict[str, Any]:
        return json.loads((self.task_dir(task_id) / "manifest.json").read_text(encoding="utf-8"))

    def append_event(self, task_id: str, event: str, payload: dict[str, Any] | None = None) -> None:
        task_dir = self.task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        event_payload = {
            "timestamp": utc_now(),
            "task_id": task_id,
            "event": event,
            **(payload or {}),
        }
        path = task_dir / "events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event_payload, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def read_events(self, task_id: str) -> list[dict[str, Any]]:
        path = self.task_dir(task_id) / "events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)

