# gpu-burst implementation goal

## Goal

Implement the remaining non-paid control-plane work needed before the first
Vast hello-world run.

The user-visible outcome is a CLI that can still run Phase 1 dry-runs, plus a
guarded Phase 2 hello-world path that can plan SkyPilot execution, enforce live
resource gates, inspect local task ledgers for stale work, and refuse paid
execution unless the explicit live prerequisites are present.

## Non-goals

- No paid Vast.ai instance creation without an explicit follow-up run with
  `GPU_BURST_LIVE=1`, `--confirm-paid`, working paid-runtime tools, and
  credentials.
- No real R2 object writes without live credentials.
- No ComfyUI or comfy-batch cloud image execution in this slice.
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

## Architecture / Approach

- Use `uv`, Python 3.13, Typer, Pydantic v2, and pytest.
- Keep paid-provider behavior behind explicit adapters and require explicit
  live gates before any external execution.
- Store local task ledgers under the XDG data directory, with `GPU_BURST_HOME`
  overriding the location in tests and development.
- Use append-only JSONL events and atomic JSON snapshot writes.
- Keep workload scope to `song-cards`.

## Progress Log

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

## Verification

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
  - Old contradictory status wording scan found no matches.
- New remaining-work verification pending.
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
- Completing the true Vast hello-world live run is blocked until paid-runtime
  tools and credentials exist and Mako explicitly authorizes a paid run.
- The live guard is intentionally stricter than `--confirm-paid` alone:
  `GPU_BURST_LIVE=1` and a ready `doctor` are both required.

## Final Review

- Remaining non-paid control-plane work is implemented and verified.
- The first true paid Vast hello-world run is still blocked by missing
  paid-runtime tools/credentials and requires explicit live execution.
