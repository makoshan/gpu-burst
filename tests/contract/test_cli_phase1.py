import json

from typer.testing import CliRunner

from gpu_burst.cli import app
from gpu_burst.ledger import Ledger
from gpu_burst.providers.skypilot import SkyExecutionError
from tests.unit.test_manifests import valid_task_dict


runner = CliRunner()


def write_task(tmp_path):
    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps(valid_task_dict()), encoding="utf-8")
    return task_path


def test_cli_quote_outputs_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GPU_BURST_HOME", str(tmp_path / "home"))
    task_path = write_task(tmp_path)

    result = runner.invoke(app, ["quote", "song-cards", str(task_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["backend"] == "fake-cloud"
    assert payload["estimated_total_usd"] > 0


def test_cli_run_dry_run_creates_ledger_and_status(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    task_path = write_task(tmp_path)

    run_result = runner.invoke(app, ["run", "song-cards", "--dry-run", str(task_path)])

    assert run_result.exit_code == 0
    run_payload = json.loads(run_result.stdout)
    task_id = run_payload["task_id"]
    assert run_payload["task_state"] == "QUOTED"
    assert run_payload["dry_run_state"] == "SUCCEEDED"
    assert (home / "tasks" / task_id / "manifest.json").exists()

    status_result = runner.invoke(app, ["status", task_id])
    assert status_result.exit_code == 0
    status_payload = json.loads(status_result.stdout)
    assert status_payload["task_state"] == "QUOTED"

    logs_result = runner.invoke(app, ["logs", task_id])
    assert logs_result.exit_code == 0
    assert "DRY_RUN_COMPLETE" in logs_result.stdout


def test_cli_paid_run_requires_explicit_confirm(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GPU_BURST_HOME", str(tmp_path / "home"))
    task_path = write_task(tmp_path)

    result = runner.invoke(app, ["run", "song-cards", str(task_path)])

    assert result.exit_code == 2
    assert "Use --confirm-paid" in result.stdout


def test_cli_confirm_paid_rejects_placeholder_digests(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    raw = valid_task_dict()
    raw["runtime"]["image_digest"] = "sha256:example-image-digest"
    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps(raw), encoding="utf-8")

    result = runner.invoke(app, ["run", "song-cards", "--confirm-paid", str(task_path)])

    assert result.exit_code == 2
    assert "placeholder runtime digest" in result.stdout
    assert not (home / "tasks").exists()


def test_cli_confirm_paid_run_requires_live_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GPU_BURST_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GPU_BURST_LIVE", raising=False)
    task_path = write_task(tmp_path)

    result = runner.invoke(app, ["run", "song-cards", "--confirm-paid", str(task_path)])

    assert result.exit_code == 2
    assert "GPU_BURST_LIVE=1" in result.stdout


def test_cli_doctor_does_not_print_secret_values(tmp_path, monkeypatch) -> None:
    secret_path = tmp_path / "vast_api_key"
    secret_path.write_text("super-secret-value", encoding="utf-8")
    secret_path.chmod(0o600)
    monkeypatch.setenv("GPU_BURST_VAST_API_KEY_FILE", str(secret_path))

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code in {0, 2}
    assert "super-secret-value" not in result.stdout
    assert "vast_api_key" in result.stdout


def test_cli_hello_world_dry_run_writes_command_plan(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_CONFIG", str(tmp_path / "missing-config.toml"))

    result = runner.invoke(app, ["hello-world", "--dry-run"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["task_state"] == "QUOTED"
    assert payload["provider"]["name"] == "skypilot-vast"
    assert payload["launch_args"][:2] == ["sky", "launch"]
    assert "--down" in payload["launch_args"]
    assert payload["policy"] == {
        "autodown_idle_minutes": 10,
        "datacenter_only": True,
        "default_gpu": "RTX4090",
        "max_hourly_cost_usd": 0.8,
    }
    assert (home / "tasks" / payload["task_id"] / "manifest.json").exists()


def test_cli_hello_world_confirm_paid_requires_live_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GPU_BURST_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GPU_BURST_LIVE", raising=False)

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 2
    assert "GPU_BURST_LIVE=1" in result.stdout


def test_cli_hello_world_confirm_paid_executes_and_records_success(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)
    executed = []

    def execute(plan, *, on_teardown):
        executed.append(plan)
        on_teardown()

    monkeypatch.setattr("gpu_burst.cli.execute_sky_launch", execute)

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["task_state"] == "SUCCEEDED"
    assert payload["dry_run"] is False
    assert len(executed) == 1
    events = Ledger(home).read_events(payload["task_id"])
    assert [event["event"] for event in events][-2:] == ["TEARING_DOWN", "SUCCEEDED"]


def test_cli_hello_world_confirm_paid_records_sanitized_failure(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)

    def fail(_plan, *, on_teardown):
        on_teardown()
        raise SkyExecutionError("sky launch failed")

    monkeypatch.setattr("gpu_burst.cli.execute_sky_launch", fail)

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 1
    assert "sky launch failed" in result.stdout
    task_dirs = list((home / "tasks").iterdir())
    manifest = Ledger(home).read_manifest(task_dirs[0].name)
    assert manifest["task_state"] == "FAILED"
    assert manifest["error"] == "sky launch failed"


def test_cli_watchdog_dry_run_reports_stale_tasks(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    ledger = Ledger(home)
    ledger.create_task("task-old", {"task_id": "task-old", "workload": "hello-world"})
    ledger.write_manifest(
        "task-old",
        {
            "task_id": "task-old",
            "task_state": "PROVISIONING",
            "updated_at": "2026-07-10T00:00:00Z",
            "provider": {"name": "vast", "cluster_name": "gb-task-old"},
        },
    )

    result = runner.invoke(app, ["watchdog", "--dry-run", "--max-age-minutes", "1"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["stale_tasks"][0]["task_id"] == "task-old"


def test_cli_watchdog_reports_corrupt_manifests_without_aborting(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    manifest_path = home / "tasks" / "task-corrupt" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{not-json", encoding="utf-8")

    result = runner.invoke(app, ["watchdog", "--dry-run", "--max-age-minutes", "1"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["stale_tasks"] == []
    assert payload["scan_errors"][0]["task_id"] == "task-corrupt"
    assert payload["scan_errors"][0]["error"] == "invalid manifest JSON"
