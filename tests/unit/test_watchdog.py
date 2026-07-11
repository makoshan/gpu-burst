from datetime import UTC, datetime, timedelta

import pytest

from gpu_burst.ledger import Ledger
from gpu_burst.safety.watchdog import find_stale_tasks, scan_stale_tasks


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


def test_watchdog_reports_structurally_invalid_terminal_manifest(tmp_path) -> None:
    ledger = Ledger(tmp_path)
    ledger.create_task("invalid-terminal", {"task_id": "invalid-terminal", "workload": "hello-world"})
    ledger.write_manifest(
        "invalid-terminal",
        {"task_state": "SUCCEEDED", "updated_at": "2026-07-10T00:00:00Z"},
    )

    scan = scan_stale_tasks(ledger, max_age_minutes=20)

    assert scan.stale_tasks == []
    assert scan.scan_errors[0].error == "manifest task_id is missing or does not match its directory"


def test_watchdog_isolates_missing_task_id_and_bad_timestamp(tmp_path) -> None:
    ledger = Ledger(tmp_path)
    ledger.create_task("missing-id", {"workload": "hello-world"})
    ledger.write_manifest(
        "missing-id",
        {"task_state": "PROVISIONING", "updated_at": "2026-07-10T00:00:00Z"},
    )
    ledger.create_task("bad-time", {"task_id": "bad-time", "workload": "hello-world"})
    ledger.write_manifest(
        "bad-time",
        {"task_id": "bad-time", "task_state": "PROVISIONING", "updated_at": "yesterday"},
    )

    scan = scan_stale_tasks(ledger, max_age_minutes=20)

    assert scan.stale_tasks == []
    assert [error.task_id for error in scan.scan_errors] == ["bad-time", "missing-id"]
    assert {error.error for error in scan.scan_errors} == {
        "invalid updated_at timestamp",
        "manifest task_id is missing or does not match its directory",
    }


def test_watchdog_reports_missing_timestamp(tmp_path) -> None:
    ledger = Ledger(tmp_path)
    ledger.create_task("missing-time", {"task_id": "missing-time", "workload": "hello-world"})
    ledger.write_manifest(
        "missing-time",
        {"task_id": "missing-time", "task_state": "PROVISIONING"},
    )

    scan = scan_stale_tasks(ledger, max_age_minutes=20)

    assert scan.stale_tasks == []
    assert scan.scan_errors[0].error == "manifest timestamp is missing"


@pytest.mark.parametrize(
    ("manifest", "expected_error"),
    [
        (["not", "an", "object"], "manifest JSON must be an object"),
        (
            {"task_id": "malformed", "task_state": "PROVISIONING", "updated_at": "2026-07-10T00:00:00"},
            "updated_at timestamp must include timezone",
        ),
        (
            {
                "task_id": "malformed",
                "task_state": "PROVISIONING",
                "updated_at": "2026-07-10T00:00:00Z",
                "provider": "vast",
            },
            "provider must be an object",
        ),
    ],
)
def test_watchdog_isolates_structurally_invalid_manifests(tmp_path, manifest, expected_error) -> None:
    ledger = Ledger(tmp_path)
    ledger.create_task("malformed", {"task_id": "malformed", "workload": "hello-world"})
    ledger.write_manifest("malformed", manifest)

    scan = scan_stale_tasks(ledger, max_age_minutes=20)

    assert scan.stale_tasks == []
    assert scan.scan_errors[0].error == expected_error
