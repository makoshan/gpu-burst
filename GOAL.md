# gpu-burst implementation goal

## Goal

Implement the Phase 1 local development loop for gpu-burst.

The user-visible outcome is a runnable Python CLI that can validate a
song-cards task, estimate local/fake-cloud cost, write a reviewable local
ledger, report status/logs, and run local dry-run flows without creating paid
cloud resources.

## Non-goals

- No paid Vast.ai instance creation in this phase.
- No real R2 object writes in this phase.
- No ComfyUI or comfy-batch cloud image execution in this phase.
- No public publishing flow.

## Success Criteria

- `uv run pytest` passes without cloud credentials.
- `gpu-burst doctor` distinguishes missing tools/config from a fully ready paid
  runtime and never prints credential values.
- `gpu-burst quote song-cards tasks/song-cards.example.json` returns a bounded
  estimate without provisioning.
- `gpu-burst run song-cards --dry-run tasks/song-cards.example.json` validates
  the task, writes a local ledger, generates manifest/events, and exits without
  cloud side effects.
- `gpu-burst status <task_id>` and `gpu-burst logs <task_id>` read the local
  ledger.
- Placeholder runtime digests are rejected for non-dry-run paid execution.

## Architecture / Approach

- Use `uv`, Python 3.13, Typer, Pydantic v2, and pytest.
- Keep paid-provider behavior behind explicit adapters and leave Phase 2 live
  provider commands gated.
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

## Decisions and Issues

- The current repository only contained documentation before this work.
- Default Python on this Mac is 3.14, but the target runtime is Python 3.13;
  `uv` has Python 3.13.5 available locally.
- Phase 1 intentionally does not install or call SkyPilot/Vast/R2 live provider
  paths. `doctor` surfaces missing paid-runtime dependencies as exit code 2.

## Final Review

- Phase 1 local development loop is implemented and verified.
- The CLI can validate and quote the example task, write a local dry-run
  ledger, and read status/logs without cloud side effects.
- Paid provider execution remains intentionally blocked until Phase 2 adds
  SkyPilot/Vast/R2 live integrations and paid-resource verification.
