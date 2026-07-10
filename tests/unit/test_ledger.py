import json

from gpu_burst.ledger import Ledger
from gpu_burst.lifecycle import TaskState


def test_ledger_writes_events_and_manifest_snapshot(tmp_path) -> None:
    ledger = Ledger(tmp_path)
    task_id = "song-cards-20260711-010203-a1b2c3"

    ledger.create_task(task_id, {"task_id": task_id, "workload": "song-cards"})
    ledger.append_event(task_id, "CREATED", {"phase": "local"})
    ledger.write_manifest(task_id, {"task_id": task_id, "task_state": TaskState.CREATED})

    events = ledger.read_events(task_id)
    manifest = ledger.read_manifest(task_id)

    assert events[0]["event"] == "CREATED"
    assert manifest["task_state"] == "CREATED"
    assert json.loads((tmp_path / "tasks" / task_id / "task.json").read_text())["workload"] == "song-cards"

