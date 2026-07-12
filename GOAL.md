# gpu-burst implementation goal

## Goal

Implement the guarded Vast hello-world lifecycle needed to turn the already
verified manual cloud smoke into a repeatable CLI operation.

The user-visible outcome is a CLI that can still run Phase 1 dry-runs, plus a
guarded Phase 2 hello-world path that can plan SkyPilot execution, enforce live
resource gates, inspect local task ledgers for stale work, and refuse paid
execution unless the explicit live prerequisites are present.

## Non-goals

- No paid Vast.ai instance creation without an explicit run with
  `GPU_BURST_LIVE=1`, `--confirm-paid`, working paid-runtime tools, and
  credentials.
- No real R2 object writes without live credentials.
- No ComfyUI or comfy-batch cloud image execution in this slice; this slice
  only runs the isolated `nvidia-smi` hello-world workload.
- No public publishing flow.

## Success Criteria

- `uv run pytest` passes without cloud credentials.
- `gpu-burst hello-world --dry-run` writes a local ledger and returns the exact
  SkyPilot command plan without provisioning.
- `gpu-burst hello-world --confirm-paid` refuses to run unless
  `GPU_BURST_LIVE=1` and `doctor` reports paid-runtime readiness.
- SkyPilot command construction is argument-array based and includes remote
  autodown.
- `gpu-burst watchdog --dry-run` scans local ledger state and reports stale
  non-terminal tasks without touching providers.
- Existing Phase 1 commands continue to work.
- Every paid CLI path enforces the same `GPU_BURST_LIVE=1` and doctor-ready
  gate before reaching provider code.
- `doctor` rejects invalid TOML and empty Vast credentials without exposing
  secret contents.
- `watchdog --dry-run` reports corrupt ledger entries without aborting the
  entire safety scan.
- Hello-world manifests retain the resource and safety policy used to create
  the plan.
- A paid hello-world launch records lifecycle state and always attempts an
  explicit `sky down`, including when `sky launch` fails.
- Provider command output is not echoed into CLI errors or ledger events.

## Architecture / Approach

- Use `uv`, Python 3.13, Typer, Pydantic v2, and pytest.
- Keep paid-provider behavior behind explicit adapters and require explicit
  live gates before any external execution.
- Store local task ledgers under the XDG data directory, with `GPU_BURST_HOME`
  overriding the location in tests and development.
- Use append-only JSONL events and atomic JSON snapshot writes.
- Keep workload scope to `song-cards`.
- Execute SkyPilot through an injectable argument-array runner so cleanup and
  error paths are testable without cloud access.

## Progress Log

- 2026-07-12: Started the first guarded paid CLI hello-world run requested by
  Mako to validate the full `gpu-burst -> SkyPilot -> Vast -> nvidia-smi ->
  sky down -> ledger` lifecycle.
- 2026-07-12: The paid CLI run failed safely during SkyPilot provisioning.
  Local ledger task `hello-world-20260712-000427-d76a20` reached
  `PROVISIONING`, recorded `TEARING_DOWN`, and ended `FAILED` with sanitized
  error `sky launch failed`.
- 2026-07-12: Diagnosed the provisioning failure and fixed a repo-side planning
  defect found during the run: hello-world now writes a per-task SkyPilot YAML
  using `provider.vast.default_gpu` instead of always launching the static
  `sky/hello-world.yaml` with `RTX4090`.
- 2026-07-11: Created implementation branch `codex/implement-phase1-local-cli`.
- 2026-07-11: Established Phase 1 scope and success criteria.
- 2026-07-11: Added pytest contract/unit coverage before implementation. Initial
  test run failed because `gpu_burst` did not exist, confirming the red phase.
- 2026-07-11: Implemented Python package, Typer CLI, Pydantic task schema,
  deterministic item keys, local ledger, fake-cloud quote, redaction, and doctor
  checks.
- 2026-07-11: Added `tasks/song-cards.example.json`, `.gitignore`, and updated
  README/product/technical docs to reflect Phase 1 local implementation.
- 2026-07-11: Corrected dry-run semantics: dry-run manifests now keep the real
  task at `QUOTED` and expose `dry_run_state: SUCCEEDED`, instead of pretending
  image generation succeeded.
- 2026-07-11: Started remaining-work slice on branch
  `codex/complete-remaining-guarded-live`.
- 2026-07-11: Added TDD coverage for TOML settings, SkyPilot command planning,
  hello-world dry-run, live guard, and local watchdog stale-task detection.
- 2026-07-11: Implemented `hello-world --dry-run`, `watchdog --dry-run`,
  `sky/hello-world.yaml`, SkyPilot launch/down argument planning, TOML settings,
  and `GPU_BURST_LIVE=1` paid-resource guard.
- 2026-07-11: Updated README, product docs, and technical docs to separate
  non-paid Phase 2 preparation from true Vast/R2 live execution.
- 2026-07-11: Started the post-review hardening slice for uniform live gates,
  semantic doctor checks, watchdog scan isolation, and auditable policy
  snapshots.
- 2026-07-11: Completed the hardening slice: `run --confirm-paid` now shares
  the live readiness gate, doctor validates configuration/key semantics and
  permissions, watchdog isolates corrupt entries, and hello-world persists a
  policy snapshot.
- 2026-07-11: Started guarded live hello-world lifecycle implementation after
  the manual Vast/R2/ComfyUI smoke succeeded and all test instances were
  destroyed.
- 2026-07-11: Implemented guarded SkyPilot execution with correct idle-autostop
  syntax, explicit finally-down cleanup, sanitized failures, teardown state
  callbacks, and CLI success/failure ledger snapshots.

## Verification

- 2026-07-12 paid run preflight:
  - `vastai show instances-v1 --raw` returned `instances_found: 0`.
  - `uv run gpu-burst doctor` returned `paid_runtime_ready: true`.
- 2026-07-12 paid run result:
  - `GPU_BURST_LIVE=1 uv run gpu-burst hello-world --confirm-paid` exited 1
    with sanitized output `sky launch failed`.
  - Ledger manifest
    `~/.local/share/gpu-burst/tasks/hello-world-20260712-000427-d76a20/manifest.json`
    recorded `task_state: FAILED`, `dry_run: false`, cluster
    `gb-hello-world-d76a20`, and a `TEARING_DOWN` event before failure.
  - SkyPilot provision logs showed `AttributeError: VastAI has no attribute
    client` inside SkyPilot's Vast provider before any active cluster remained.
  - `sky down -y gb-hello-world-d76a20` reported the cluster was not found.
  - `vastai show instances-v1 --raw` returned `instances_found: 0`.
  - `sky status` reported no clusters, no in-progress managed jobs, and no live
    services.
- 2026-07-12 follow-up verification after the per-task SkyPilot YAML fix:
  - New TDD red run failed because `launch_args` still pointed at
    `sky/hello-world.yaml`.
  - Targeted green run passed:
    `uv run pytest tests/contract/test_cli_phase1.py::test_cli_hello_world_plan_uses_configured_gpu_in_generated_sky_task -q`.
  - Related contract/unit run passed:
    `uv run pytest tests/unit/test_skypilot_provider.py tests/contract/test_cli_phase1.py -q`
    reported 20 passed.
  - Full verification passed: `uv run pytest -q` reported 45 passed.
  - `uv run python -m compileall -q src tests` exited 0.
  - `git diff --check` exited 0.
  - `GPU_BURST_HOME=/tmp/gpu-burst-dynamic-sky-task-smoke uv run gpu-burst
    hello-world --dry-run` generated a task-local `sky-task.yaml` containing
    `accelerators: RTX3060:1` and policy `max_hourly_cost_usd: 0.1`.
- `uv run pytest` initially failed with `ModuleNotFoundError: No module named
  'gpu_burst'`, as expected before implementation.
- `uv run pytest` passed: 14 tests passed.
- `env GPU_BURST_HOME=/tmp/gpu-burst-smoke-codex uv run gpu-burst quote
  song-cards tasks/song-cards.example.json` passed and returned a fake-cloud
  estimate of `0.195` USD.
- `env GPU_BURST_HOME=/tmp/gpu-burst-smoke-codex uv run gpu-burst doctor`
  returned exit code 2 because `sky`, `vastai`, `s5cmd`, config, and Vast key
  are missing locally; it did not print secret values.
- `env GPU_BURST_HOME=/tmp/gpu-burst-smoke-codex-2 uv run gpu-burst run
  song-cards --dry-run tasks/song-cards.example.json` passed and wrote a local
  manifest with `task_state: QUOTED`, `dry_run_state: SUCCEEDED`, and provider
  `fake-cloud`.
- Final verification before commit:
  - `uv lock --check` exited 0.
  - `uv run pytest` passed: 14 tests passed.
  - `uv run python -m compileall -q src tests` exited 0.
  - `git diff --check` exited 0.
  - Markdown relative link check exited 0.
- High-risk credential pattern scan found no matches.
- Post-review hardening TDD red runs exposed the missing watchdog scan API,
  unsafe key permissions, missing timestamps, non-object manifests, naive
  timestamps, malformed providers, and invalid terminal manifests.
- Final post-review verification:
  - `uv lock --check` exited 0.
  - `uv run pytest -q` passed: 34 tests passed.
  - `uv run python -m compileall -q src tests` exited 0.
  - `uv build --out-dir /tmp/gpu-burst-dist-hardening-final` built the sdist
    and wheel.
  - `git diff --check` exited 0.
  - `hello-world --dry-run` persisted and returned its policy snapshot.
  - `watchdog --dry-run --max-age-minutes 1` returned both `stale_tasks` and
    `scan_errors` without provider side effects.
  - Old contradictory status wording scan found no matches.
- Guarded live lifecycle TDD red runs confirmed missing executor behavior,
  incorrect `--down 10` syntax, missing CLI state handling, and cleanup loss
  when the teardown callback failed.
- Final guarded lifecycle verification:
  - `uv lock --check` exited 0.
  - `uv run pytest -q` passed: 44 tests passed.
  - `uv run python -m compileall -q src tests` exited 0.
  - `uv build --out-dir /tmp/gpu-burst-dist-live-lifecycle-final` built the
    sdist and wheel.
  - `git diff --check` exited 0.
  - `hello-world --dry-run` emitted
    `--idle-minutes-to-autostop 5 --down` and a separate `sky down` plan.
  - `vastai show instances-v1 --raw` reported zero instances.
  - High-risk credential pattern scan found no matches.
- New TDD red run failed as expected: missing `Settings`, `providers`, and
  `safety` modules.
- `uv run pytest tests/unit/test_config.py tests/unit/test_skypilot_provider.py
  tests/unit/test_watchdog.py tests/contract/test_cli_phase1.py` passed: 13
  tests passed.
- `uv run pytest` passed: 22 tests passed.
- `env GPU_BURST_HOME=/tmp/gpu-burst-remaining-smoke uv run gpu-burst
  hello-world --dry-run` passed and returned a SkyPilot launch plan with
  `--down 10`.
- `env GPU_BURST_HOME=/tmp/gpu-burst-remaining-smoke uv run gpu-burst watchdog
  --dry-run --max-age-minutes 1` passed and returned an empty stale task list.
- Final verification before commit:
  - `uv run pytest` passed: 22 tests passed.
  - `uv run python -m compileall -q src tests` exited 0.
  - `uv build --out-dir /tmp/gpu-burst-dist-remaining` built sdist and wheel.
  - `git diff --check` exited 0.
  - `uv lock --check` exited 0.
  - `hello-world --dry-run` smoke passed with `sky launch ... --down 10`.
  - `watchdog --dry-run --max-age-minutes 1` smoke passed.
  - `hello-world --confirm-paid` without `GPU_BURST_LIVE=1` exited 2 with the
    expected guard message.
  - Markdown relative link check exited 0.
  - High-risk credential pattern scan found no matches.

## Decisions and Issues

- The current repository only contained documentation before this work.
- Default Python on this Mac is 3.14, but the target runtime is Python 3.13;
  `uv` has Python 3.13.5 available locally.
- Phase 1 intentionally does not install or call SkyPilot/Vast/R2 live provider
  paths. `doctor` surfaces missing paid-runtime dependencies as exit code 2.
- Paid-runtime tools and credentials are configured locally and a manual Vast
  smoke has succeeded. Development remains non-paid; a new paid CLI run still
  requires Mako's explicit invocation.
- The live guard is intentionally stricter than `--confirm-paid` alone:
  `GPU_BURST_LIVE=1` and a ready `doctor` are both required.
- First paid CLI run did not complete `nvidia-smi`; current blocker is the
  local SkyPilot Vast provider environment. SkyPilot 0.12.3.post1 calls
  `vast.vast().client.api_key`, but its installed `vastai-sdk 0.2.5` object no
  longer exposes `.client`.
- The run also exposed that the previous static `sky/hello-world.yaml` ignored
  the configured GPU and selected RTX4090 resources. That repo-side defect is
  fixed by generating a per-task SkyPilot YAML from settings.

## Final Review

- Post-review hardening success criteria are implemented and verified.
- Guarded live hello-world code is implemented and locally verified without
  creating paid resources.
- Remaining gates are deliberately separate: repair or pin the local
  SkyPilot/Vast SDK compatibility, run the guarded CLI path again against Vast,
  and correlate any resulting charge. Song-cards automation remains Phase 3.
