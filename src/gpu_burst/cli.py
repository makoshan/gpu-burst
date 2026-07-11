from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from gpu_burst.config import data_home
from gpu_burst.config import load_settings
from gpu_burst.doctor import build_report, exit_code
from gpu_burst.ledger import Ledger, utc_now
from gpu_burst.lifecycle import ItemState, TaskState
from gpu_burst.manifests import TaskSpec, item_key, load_task_json, validate_for_run
from gpu_burst.providers.skypilot import SkyExecutionError, SkyLaunchPlan, execute_sky_launch
from gpu_burst.quote import build_quote
from gpu_burst.safety.watchdog import scan_stale_tasks


app = typer.Typer(no_args_is_help=True)


def _emit_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def _load_and_check(workload: str, task_path: Path) -> TaskSpec:
    if workload != "song-cards":
        raise typer.BadParameter("only song-cards is supported")
    task = load_task_json(task_path)
    if task.workload != workload:
        raise typer.BadParameter("workload argument does not match task workload")
    return task


def _new_task_id(workload: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{workload}-{stamp}-{secrets.token_hex(3)}"


def _require_live_ready() -> None:
    if os.environ.get("GPU_BURST_LIVE") != "1":
        typer.echo("Paid execution requires GPU_BURST_LIVE=1.")
        raise typer.Exit(2)
    report = build_report()
    if not report.paid_runtime_ready:
        typer.echo("Paid execution requires doctor to report paid_runtime_ready=true.")
        raise typer.Exit(exit_code(report))


@app.command()
def doctor() -> None:
    report = build_report()
    _emit_json(report.model_dump(mode="json"))
    raise typer.Exit(exit_code(report))


@app.command()
def quote(workload: str, task_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    task = _load_and_check(workload, task_path)
    validate_for_run(task, dry_run=True)
    estimate = build_quote(task)
    _emit_json(estimate.model_dump(mode="json"))


@app.command()
def run(
    workload: str,
    task_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate and write local ledger without cloud side effects."),
    confirm_paid: bool = typer.Option(False, "--confirm-paid", help="Required before any paid provider execution."),
) -> None:
    if not dry_run and not confirm_paid:
        typer.echo("Use --confirm-paid for paid cloud execution, or --dry-run for local Phase 1 validation.")
        raise typer.Exit(2)

    task = _load_and_check(workload, task_path)
    try:
        validate_for_run(task, dry_run=dry_run)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc

    if confirm_paid and not dry_run:
        _require_live_ready()
        typer.echo("Paid provider execution is not implemented in Phase 1.")
        raise typer.Exit(2)

    task_id = _new_task_id(workload)
    ledger = Ledger(data_home())
    quote_estimate = build_quote(task)
    manifest = {
        "task_id": task_id,
        "task_state": TaskState.QUOTED,
        "created_at": utc_now(),
        "dry_run": True,
        "dry_run_state": "SUCCEEDED",
        "quote_usd": quote_estimate.estimated_total_usd,
        "budget_usd": task.budget.max_total_usd,
        "provider": {
            "name": "fake-cloud",
            "cluster_name": None,
            "instance_id": None,
        },
        "items": {
            item.item_id: {
                "state": ItemState.PENDING,
                "item_key": item_key(task, item),
                "output_key": item.output_key,
                "attempts": 0,
                "duration_seconds": 0,
            }
            for item in task.items
        },
    }

    ledger.create_task(task_id, task.model_dump(mode="json"))
    ledger.append_event(task_id, "CREATED", {"phase": "local"})
    ledger.append_event(task_id, "VALIDATED", {"phase": "local"})
    ledger.write_quote(task_id, quote_estimate.model_dump(mode="json"))
    ledger.append_event(task_id, "QUOTED", {"estimated_total_usd": quote_estimate.estimated_total_usd})
    ledger.write_manifest(task_id, manifest)
    ledger.append_event(task_id, "DRY_RUN_COMPLETE", {"dry_run_state": "SUCCEEDED"})
    _emit_json(manifest)


@app.command()
def status(task_id: str) -> None:
    ledger = Ledger(data_home())
    try:
        _emit_json(ledger.read_manifest(task_id))
    except FileNotFoundError as exc:
        typer.echo(f"Unknown task_id: {task_id}")
        raise typer.Exit(2) from exc


@app.command()
def logs(task_id: str) -> None:
    ledger = Ledger(data_home())
    events = ledger.read_events(task_id)
    if not events:
        typer.echo(f"No events found for task_id: {task_id}")
        raise typer.Exit(2)
    for event in events:
        typer.echo(json.dumps(event, sort_keys=True, ensure_ascii=False))


@app.command()
def cancel(task_id: str) -> None:
    ledger = Ledger(data_home())
    ledger.append_event(task_id, "CANCEL_REQUESTED", {"phase": "local"})
    typer.echo("Cancel is recorded locally. Provider cancellation is not implemented in Phase 1.")


@app.command("hello-world")
def hello_world(
    dry_run: bool = typer.Option(False, "--dry-run", help="Write a local hello-world plan without launching cloud resources."),
    confirm_paid: bool = typer.Option(False, "--confirm-paid", help="Required before a paid hello-world launch."),
) -> None:
    if not dry_run and not confirm_paid:
        typer.echo("Use --confirm-paid for paid cloud execution, or --dry-run for local planning.")
        raise typer.Exit(2)
    if confirm_paid:
        _require_live_ready()

    settings = load_settings()
    task_id = _new_task_id("hello-world")
    cluster_name = f"gb-hello-world-{task_id.rsplit('-', 1)[-1]}"
    plan = SkyLaunchPlan(
        cluster_name=cluster_name,
        task_file=Path("sky/hello-world.yaml"),
        autodown_idle_minutes=settings.safety.autodown_idle_minutes,
    )
    manifest = {
        "task_id": task_id,
        "task_state": TaskState.QUOTED,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "dry_run": dry_run,
        "provider": {
            "name": "skypilot-vast",
            "cluster_name": cluster_name,
            "instance_id": None,
        },
        "policy": {
            "datacenter_only": settings.provider.vast.datacenter_only,
            "max_hourly_cost_usd": settings.provider.vast.max_hourly_cost_usd,
            "default_gpu": settings.provider.vast.default_gpu,
            "autodown_idle_minutes": settings.safety.autodown_idle_minutes,
        },
        "launch_args": plan.launch_args(),
        "down_args": plan.down_args(),
    }
    ledger = Ledger(data_home())
    ledger.create_task(task_id, {"task_id": task_id, "workload": "hello-world"})
    ledger.append_event(task_id, "CREATED", {"phase": "hello-world"})
    ledger.append_event(task_id, "PLANNED", {"cluster_name": cluster_name})
    if dry_run:
        manifest["dry_run_state"] = "SUCCEEDED"
        ledger.write_manifest(task_id, manifest)
        ledger.append_event(task_id, "DRY_RUN_COMPLETE", {"dry_run_state": "SUCCEEDED"})
        _emit_json(manifest)
        return

    manifest["task_state"] = TaskState.PROVISIONING
    manifest["updated_at"] = utc_now()
    ledger.write_manifest(task_id, manifest)
    ledger.append_event(task_id, "PROVISIONING", {"cluster_name": cluster_name})

    def record_teardown() -> None:
        manifest["task_state"] = TaskState.TEARING_DOWN
        manifest["updated_at"] = utc_now()
        ledger.write_manifest(task_id, manifest)
        ledger.append_event(task_id, "TEARING_DOWN", {"cluster_name": cluster_name})

    try:
        execute_sky_launch(plan, on_teardown=record_teardown)
    except SkyExecutionError as exc:
        manifest["task_state"] = TaskState.FAILED
        manifest["updated_at"] = utc_now()
        manifest["error"] = str(exc)
        ledger.write_manifest(task_id, manifest)
        ledger.append_event(task_id, "FAILED", {"error": str(exc)})
        typer.echo(str(exc))
        raise typer.Exit(1) from exc

    manifest["task_state"] = TaskState.SUCCEEDED
    manifest["updated_at"] = utc_now()
    ledger.write_manifest(task_id, manifest)
    ledger.append_event(task_id, "SUCCEEDED", {"cluster_name": cluster_name})
    _emit_json(manifest)


@app.command()
def watchdog(
    dry_run: bool = typer.Option(False, "--dry-run", help="Report stale local tasks without touching providers."),
    max_age_minutes: int | None = typer.Option(None, "--max-age-minutes", min=1),
) -> None:
    if not dry_run:
        typer.echo("Provider watchdog actions are not implemented yet. Use --dry-run for local stale-task reporting.")
        raise typer.Exit(2)
    settings = load_settings()
    max_age = max_age_minutes or settings.safety.max_unverified_age_minutes
    ledger = Ledger(data_home())
    scan = scan_stale_tasks(ledger, max_age_minutes=max_age)
    _emit_json(
        {
            "dry_run": True,
            "max_age_minutes": max_age,
            "stale_tasks": [task.as_dict() for task in scan.stale_tasks],
            "scan_errors": [error.as_dict() for error in scan.scan_errors],
        }
    )


if __name__ == "__main__":
    app()
