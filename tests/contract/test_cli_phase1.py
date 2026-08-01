import json
from subprocess import CompletedProcess

from typer.testing import CliRunner

from gpu_burst.cli import app
from gpu_burst.ayue_runpod import build_ayue_runpod_plan
from gpu_burst.ledger import Ledger
from gpu_burst.providers.skypilot import SkyExecutionError
from gpu_burst.providers.runpod_api import verify_terminated
from gpu_burst.providers.vast_api import VastApiError, verify_destroyed
from tests.unit.test_manifests import valid_task_dict
from tests.unit.test_ayue_runpod import _write_jobpack


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


def test_cli_hello_world_runpod_dry_run_writes_runpod_plan(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_PROVIDER", "runpod")
    monkeypatch.setenv("GPU_BURST_CONFIG", str(tmp_path / "missing-config.toml"))

    result = runner.invoke(app, ["hello-world", "--dry-run"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["provider"]["name"] == "skypilot-runpod"
    assert payload["policy"] == {
        "autodown_idle_minutes": 10,
        "allowed_cuda_versions": ["13.0"],
        "cloud_type": "COMMUNITY",
        "default_gpu": "RTX4090",
        "max_hourly_cost_usd": 0.75,
    }
    task_file = home / "tasks" / payload["task_id"] / "sky-task.yaml"
    task_yaml = task_file.read_text(encoding="utf-8")
    assert "cloud: runpod" in task_yaml
    assert "cloud: vast" not in task_yaml


def test_cli_configure_runpod_uses_env_without_printing_secret(tmp_path, monkeypatch) -> None:
    path = tmp_path / "runpod.toml"
    secret = "rpa_test_only"
    monkeypatch.setenv("RUNPOD_API_KEY", secret)
    monkeypatch.setenv("GPU_BURST_RUNPOD_CONFIG_FILE", str(path))

    result = runner.invoke(app, ["configure-runpod", "--from-env"])

    assert result.exit_code == 0
    assert secret not in result.stdout
    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600


def test_cli_ayue_runpod_plan_writes_yaml_but_does_not_launch(tmp_path, monkeypatch) -> None:
    jobpack = _write_jobpack(tmp_path / "jobpack")
    output = tmp_path / "ayue-runpod.yaml"
    image = "registry.example/ayue@sha256:" + "e" * 64
    monkeypatch.setattr(
        "gpu_burst.cli.execute_sky_launch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("planning must not launch")),
    )

    result = runner.invoke(
        app,
        [
            "ayue-720p-plan",
            "--jobpack",
            str(jobpack),
            "--image",
            image,
            "--output",
            str(output),
            "--allow-pending",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["deliverable_count"] == 19
    assert payload["execution_count"] == 29
    assert payload["paid_launch_allowed"] is False
    assert payload["sky_yaml"] == str(output)
    assert payload["bootstrap_yaml"] == str(output.with_suffix(".bootstrap.yaml"))
    assert "cloud: runpod" in output.read_text(encoding="utf-8")
    assert "fetch_weights" not in output.with_suffix(".bootstrap.yaml").read_text(encoding="utf-8")


def test_cli_ayue_runpod_launch_refuses_pending_package_before_cloud(tmp_path, monkeypatch) -> None:
    jobpack = _write_jobpack(tmp_path / "jobpack")
    image = "registry.example/ayue@sha256:" + "f" * 64
    monkeypatch.setenv("GPU_BURST_PROVIDER", "runpod")
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr(
        "gpu_burst.cli._require_live_ready",
        lambda: (_ for _ in ()).throw(AssertionError("doctor must run only after package gates")),
    )
    monkeypatch.setattr(
        "gpu_burst.cli.execute_sky_launch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pending package must not launch")),
    )

    result = runner.invoke(
        app,
        [
            "ayue-720p-launch",
            "--jobpack",
            str(jobpack),
            "--image",
            image,
            "--confirm-paid",
        ],
    )

    assert result.exit_code == 2
    assert "paid launch blocked" in result.stdout


def test_cli_ayue_runpod_checks_observed_rate_before_exec(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    config_path = tmp_path / "config.toml"
    config_path.write_text("[provider.runpod]\nmax_hourly_cost_usd = 0.50\n", encoding="utf-8")
    image = "registry.example/ayue@sha256:" + "1" * 64
    jobpack = _write_jobpack(tmp_path / "jobpack", approved=True)
    preview = build_ayue_runpod_plan(
        jobpack, image, allow_pending=True, max_hourly_cost_usd=0.50
    )
    approval_path = jobpack / "approval.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval.update(
        {
            "provider": "runpod",
            "image_ref": image,
            "launch_contract_sha256": preview.launch_contract_sha256,
        }
    )
    approval_path.write_text(json.dumps(approval), encoding="utf-8")
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_CONFIG", str(config_path))
    monkeypatch.setenv("GPU_BURST_PROVIDER", "runpod")
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)
    fake = _FakeRunPodClient()
    monkeypatch.setattr("gpu_burst.cli.RunPodClient", lambda: fake)
    calls: list[str] = []

    def execute(plan, *, on_launched=None, on_teardown=None):
        from gpu_burst.providers.skypilot import execute_sky_launch as real_execute

        fake.cluster_name = plan.cluster_name

        def runner(args, **kwargs):
            calls.append(args[1])
            if args[1] == "launch":
                fake.phase = "launched"
            elif args[1] == "down":
                fake.phase = "down"
            return CompletedProcess(args, 0, "", "")

        return real_execute(
            plan,
            runner=runner,
            on_launched=on_launched,
            on_teardown=on_teardown,
        )

    monkeypatch.setattr("gpu_burst.cli.execute_sky_launch", execute)

    result = runner.invoke(
        app,
        [
            "ayue-720p-launch",
            "--jobpack",
            str(jobpack),
            "--image",
            image,
            "--confirm-paid",
        ],
    )

    assert result.exit_code == 1
    assert calls == ["launch", "down"]
    task_id = next((home / "tasks").iterdir()).name
    events = Ledger(home).read_events(task_id)
    assert any(event["event"] == "RUNPOD_RATE_LIMIT_EXCEEDED" for event in events)


class _FakeRunPodPod:
    def __init__(self, pod_id: str, cost_per_hour: float = 0.69, name: str = ""):
        self.pod_id = pod_id
        self.cost_per_hour = cost_per_hour
        self.name = name
        self.desired_status = "RUNNING"

    def as_dict(self):
        return {
            "pod_id": self.pod_id,
            "name": self.name,
            "desired_status": self.desired_status,
            "gpu_name": "NVIDIA GeForce RTX 4090",
            "cost_per_hour": self.cost_per_hour,
            "image": "repo/ayue@sha256:" + "a" * 64,
        }


class _FakeRunPodClient:
    def __init__(self):
        self.phase = "pre"
        self.cluster_name = ""
        self.deleted: list[str] = []

    def list_pods(self):
        if self.phase in {"launched", "leaked"}:
            return [_FakeRunPodPod("pod-1", name=f"{self.cluster_name}-head")]
        return []

    def terminate_pod(self, pod_id):
        self.deleted.append(pod_id)
        self.phase = "down"


def test_cli_hello_world_runpod_confirm_paid_records_cleanup_and_estimated_billing(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_PROVIDER", "runpod")
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)
    fake = _FakeRunPodClient()
    monkeypatch.setattr("gpu_burst.cli.RunPodClient", lambda: fake)

    def execute(plan, *, on_launched=None, on_teardown=None):
        fake.cluster_name = plan.cluster_name
        fake.phase = "launched"
        if on_launched is not None:
            on_launched()
        fake.phase = "down"
        if on_teardown is not None:
            on_teardown()

    monkeypatch.setattr("gpu_burst.cli.execute_sky_launch", execute)

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["task_state"] == "SUCCEEDED"
    assert payload["terminate_verified"] is True
    assert payload["billing"]["provider"] == "runpod"
    assert payload["billing"]["billing_source"] == "estimated_from_observed_rate"
    assert payload["billing"]["pods"][0]["pod_id"] == "pod-1"
    events = [event["event"] for event in Ledger(home).read_events(payload["task_id"])]
    for expected in (
        "RUNPOD_SNAPSHOT",
        "POD_OBSERVED",
        "TEARING_DOWN",
        "TERMINATE_VERIFIED",
        "BILLING_RECORDED",
        "SUCCEEDED",
    ):
        assert expected in events


def test_cli_hello_world_runpod_aborts_when_account_has_existing_pod(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_PROVIDER", "runpod")
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)
    fake = _FakeRunPodClient()
    fake.phase = "launched"
    fake.cluster_name = "foreign"
    monkeypatch.setattr("gpu_burst.cli.RunPodClient", lambda: fake)
    monkeypatch.setattr(
        "gpu_burst.cli.execute_sky_launch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not launch")),
    )

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 2
    assert "--allow-concurrent" in result.stdout
    task_id = next((home / "tasks").iterdir()).name
    events = [event["event"] for event in Ledger(home).read_events(task_id)]
    assert "ABORTED_CONCURRENT" in events


def test_cli_hello_world_runpod_escalates_delete_for_leaked_pod(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_PROVIDER", "runpod")
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)
    fake = _FakeRunPodClient()
    monkeypatch.setattr("gpu_burst.cli.RunPodClient", lambda: fake)
    monkeypatch.setattr(
        "gpu_burst.cli.verify_terminated",
        lambda client, ids: verify_terminated(client, ids, attempts=3, sleeper=lambda _: None),
    )

    def execute(plan, *, on_launched=None, on_teardown=None):
        fake.cluster_name = plan.cluster_name
        fake.phase = "launched"
        if on_launched is not None:
            on_launched()
        fake.phase = "leaked"
        if on_teardown is not None:
            on_teardown()

    monkeypatch.setattr("gpu_burst.cli.execute_sky_launch", execute)

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["terminate_verified"] is True
    assert fake.deleted == ["pod-1"]


def test_cli_hello_world_plan_uses_configured_gpu_in_generated_sky_task(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[provider.vast]
default_gpu = "RTX3060"
max_hourly_cost_usd = 0.10
datacenter_only = false

[safety]
autodown_idle_minutes = 5
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_CONFIG", str(config_path))

    result = runner.invoke(app, ["hello-world", "--dry-run"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    task_file = home / "tasks" / payload["task_id"] / "sky-task.yaml"
    assert payload["launch_args"][4] == str(task_file)
    assert task_file.exists()
    task_yaml = task_file.read_text(encoding="utf-8")
    assert "accelerators: RTX3060:1" in task_yaml
    assert "RTX4090" not in task_yaml


def test_cli_hello_world_confirm_paid_requires_live_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GPU_BURST_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GPU_BURST_LIVE", raising=False)

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 2
    assert "GPU_BURST_LIVE=1" in result.stdout


class _FakeVastInstance:
    def __init__(self, instance_id: int, dph_total: float = 0.35, label: str = ""):
        self.instance_id = instance_id
        self.dph_total = dph_total
        self.label = label

    def as_dict(self):
        return {"instance_id": self.instance_id, "gpu_name": "RTX 4090",
                "dph_total": self.dph_total, "geolocation": "US",
                "actual_status": "running", "label": self.label}


class _FakeVastClient:
    """Instance 90001 appears after launch and disappears after teardown."""

    def __init__(self):
        self.phase = "pre"
        self.balances = [10.0, 9.9]
        self.label_prefix = ""

    def list_instances(self):
        if self.phase == "launched":
            return [_FakeVastInstance(90001, label=f"{self.label_prefix}-94-head")]
        return []

    def destroy_instance(self, instance_id):
        raise AssertionError("escalation should not trigger in the happy path")

    def current_balance(self):
        return self.balances.pop(0) if self.balances else 9.9


def test_cli_hello_world_confirm_paid_executes_and_records_success(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)
    fake_vast = _FakeVastClient()
    monkeypatch.setattr("gpu_burst.cli.VastClient", lambda: fake_vast)
    executed = []

    def execute(plan, *, on_launched=None, on_teardown=None):
        executed.append(plan)
        fake_vast.label_prefix = plan.cluster_name
        fake_vast.phase = "launched"
        if on_launched is not None:
            on_launched()
        fake_vast.phase = "down"
        if on_teardown is not None:
            on_teardown()

    monkeypatch.setattr("gpu_burst.cli.execute_sky_launch", execute)

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["task_state"] == "SUCCEEDED"
    assert payload["dry_run"] is False
    assert payload["destroy_verified"] is True
    assert payload["billing"]["balance_delta_usd"] == 0.1
    assert payload["billing"]["instances"][0]["instance_id"] == 90001
    assert len(executed) == 1
    events = [event["event"] for event in Ledger(home).read_events(payload["task_id"])]
    for expected in ("VAST_SNAPSHOT", "INSTANCE_OBSERVED", "TEARING_DOWN",
                     "DESTROY_VERIFIED", "BILLING_RECORDED", "SUCCEEDED"):
        assert expected in events
    assert (home / "tasks" / payload["task_id"] / "billing.json").exists()


def test_cli_hello_world_confirm_paid_aborts_on_concurrent_instances(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)
    fake_vast = _FakeVastClient()
    fake_vast.phase = "launched"  # a foreign instance is already running
    monkeypatch.setattr("gpu_burst.cli.VastClient", lambda: fake_vast)

    def must_not_run(*args, **kwargs):
        raise AssertionError("sky launch must not run when concurrent instances exist")

    monkeypatch.setattr("gpu_burst.cli.execute_sky_launch", must_not_run)

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 2
    assert "--allow-concurrent" in result.stdout
    task_dirs = list((home / "tasks").iterdir())
    events = [event["event"] for event in Ledger(home).read_events(task_dirs[0].name)]
    assert "ABORTED_CONCURRENT" in events


def test_cli_hello_world_confirm_paid_records_sanitized_failure(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)
    fake_vast = _FakeVastClient()
    monkeypatch.setattr("gpu_burst.cli.VastClient", lambda: fake_vast)

    def fail(_plan, *, on_launched=None, on_teardown=None):
        if on_teardown is not None:
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
    # even on failure the destroy verification and billing trail must exist
    events = [event["event"] for event in Ledger(home).read_events(task_dirs[0].name)]
    assert "BILLING_RECORDED" in events
    assert "DESTROY_VERIFIED" in events


def test_cli_hello_world_confirm_paid_records_preflight_failure(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)

    def broken_client():
        raise VastApiError("vast api GET /users/current/ failed: network error")

    monkeypatch.setattr("gpu_burst.cli.VastClient", broken_client)
    executed = []
    monkeypatch.setattr("gpu_burst.cli.execute_sky_launch", lambda *args, **kwargs: executed.append(args))

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 2
    assert executed == []
    task_dirs = list((home / "tasks").iterdir())
    manifest = Ledger(home).read_manifest(task_dirs[0].name)
    assert manifest["task_state"] == "FAILED"
    assert manifest["error"] == "vast preflight failed"


def test_cli_hello_world_confirm_paid_reports_leak_when_instance_survives(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("GPU_BURST_HOME", str(home))
    monkeypatch.setenv("GPU_BURST_LIVE", "1")
    monkeypatch.setattr("gpu_burst.cli._require_live_ready", lambda: None)

    class LeakyVastClient(_FakeVastClient):
        def __init__(self):
            super().__init__()
            self.destroy_attempts: list[int] = []

        def list_instances(self):
            if self.phase in ("launched", "down"):
                return [_FakeVastInstance(90001)]
            return []

        def destroy_instance(self, instance_id):
            self.destroy_attempts.append(instance_id)

    fake_vast = LeakyVastClient()
    monkeypatch.setattr("gpu_burst.cli.VastClient", lambda: fake_vast)
    monkeypatch.setattr(
        "gpu_burst.cli.verify_destroyed",
        lambda client, ids: verify_destroyed(client, ids, sleeper=lambda _: None),
    )

    def execute(plan, *, on_launched=None, on_teardown=None):
        fake_vast.phase = "launched"
        if on_launched is not None:
            on_launched()
        fake_vast.phase = "down"
        if on_teardown is not None:
            on_teardown()

    monkeypatch.setattr("gpu_burst.cli.execute_sky_launch", execute)

    result = runner.invoke(app, ["hello-world", "--confirm-paid"])

    assert result.exit_code == 1
    assert "destroy verification did not pass" in result.stdout
    assert fake_vast.destroy_attempts == [90001]
    task_dirs = list((home / "tasks").iterdir())
    manifest = Ledger(home).read_manifest(task_dirs[0].name)
    assert manifest["task_state"] == "FAILED"
    assert manifest["destroy_verified"] is False
    events = [event["event"] for event in Ledger(home).read_events(task_dirs[0].name)]
    assert "DESTROY_LEAKED" in events


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
