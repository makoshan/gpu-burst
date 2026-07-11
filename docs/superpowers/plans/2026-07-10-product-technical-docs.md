# Product and Technical Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current research-heavy README into a clear project entrypoint backed by durable product and technical specifications for the song-cards MVP and later workload expansion.

**Architecture:** Keep `README.md` as the short orientation and decision summary. Put product intent, scope, experience, rollout, and measurable success in `docs/product.md`; put system boundaries, task contracts, lifecycle, security, cost accounting, and failure handling in `docs/technical.md`.

**Tech Stack:** Markdown, Mermaid, Git, shell-based document validation.

---

### Task 1: Product document

**Files:**
- Create: `docs/product.md`

- [x] **Step 1:** Write the product positioning, users, jobs, principles, non-goals, and supported workload maturity levels.
- [x] **Step 2:** Define the CLI experience and song-cards MVP user journey.
- [x] **Step 3:** Define acceptance criteria, 1-3 primary KPIs, driver metrics, guardrails, and rollout gates using only evidence available in this repository and linked workload repos.
- [x] **Step 4:** Review the document for claims that confuse planned, experimental, verified, and production-ready states.

### Task 2: Technical document

**Files:**
- Create: `docs/technical.md`

- [x] **Step 1:** Document the control-plane/workload-adapter/data-plane boundaries and include a Mermaid architecture diagram.
- [x] **Step 2:** Define task and item manifests with concrete JSON examples and lifecycle states.
- [x] **Step 3:** Document provider selection, ComfyUI execution, R2 layout, credentials, cost accounting, idempotency, recovery, teardown, and observability.
- [x] **Step 4:** Add implementation phases and explicit technical acceptance gates for doctor, hello-world, one-image, and 20-image runs.

### Task 3: README entrypoint

**Files:**
- Modify: `README.md`

- [x] **Step 1:** Add a documentation navigation section linking to `docs/product.md` and `docs/technical.md`.
- [x] **Step 2:** Keep the README's concise positioning, decisions, roadmap, and safety summary; remove only material duplicated verbatim by the new documents.
- [x] **Step 3:** Confirm existing research links and user-authored uncommitted decisions remain intact.

### Task 4: Verification and commit

**Files:**
- Verify: `README.md`
- Verify: `docs/product.md`
- Verify: `docs/technical.md`
- Verify: `docs/superpowers/plans/2026-07-10-product-technical-docs.md`

- [x] **Step 1:** Run `git diff --check` and require exit code 0.
- [x] **Step 2:** Run a local Markdown link/path check for every relative link and require zero missing targets.
- [x] **Step 3:** Search for `TBD`, `TODO`, contradictory maturity claims, and accidentally exposed credential values; require no unresolved findings.
- [x] **Step 4:** Review `git diff --stat` and the complete diff to confirm scope is documentation-only.
- [x] **Step 5:** Commit the verified documentation with message `docs: define gpu-burst product and architecture`.
