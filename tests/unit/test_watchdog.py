from datetime import UTC, datetime, timedelta

from gpu_burst.ledger import Ledger
from gpu_burst.safety.watchdog import find_stale_tasks


def test_watchdog_reports_stale_non_terminal_tasks(tmp_path) -> None:
    ledger = Ledger(tmp_path)
    task_id = "hello-world-20260711-010203-a1b2c3"
    old_timestamp = (datetime.now(UTC) - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    ledger.create_task(task_id, {"task_id": task_id, "workload": "hello-world"})
    ledger.write_manifest(
        task_id,
        {
            "task_id": task_id,
            "task_state": "PROVISIONING",
            "updated_at": old_timestamp,
            "provider": {"name": "vast", "cluster_name": "gb-hello-world-a1b2c3"},
        },
    )

    stale = find_stale_tasks(ledger, max_age_minutes=20)

    assert [task.task_id for task in stale] == [task_id]
    assert stale[0].task_state == "PROVISIONING"


def test_watchdog_ignores_terminal_tasks(tmp_path) -> None:
    ledger = Ledger(tmp_path)
    task_id = "hello-world-20260711-010203-a1b2c3"
    old_timestamp = (datetime.now(UTC) - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    ledger.create_task(task_id, {"task_id": task_id, "workload": "hello-world"})
    ledger.write_manifest(
        task_id,
        {
            "task_id": task_id,
            "task_state": "SUCCEEDED",
            "updated_at": old_timestamp,
            "provider": {"name": "fake-cloud"},
        },
    )

    assert find_stale_tasks(ledger, max_age_minutes=20) == []

