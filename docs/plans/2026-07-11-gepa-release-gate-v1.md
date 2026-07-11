# GEPA Release Gate V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a minimal, deterministic release gate that compares an optimized candidate with the released baseline on fresh regression coverage, evaluates sealed holdout coverage, and emits an immutable three-state verdict.

**Architecture:** Add fresh scenario data but preserve the existing scenario schema, evaluator, suite runner, and comparison code. Put only suite-role validation, thresholds, orchestration, decision models, report persistence, and CLI behavior in a new `agent_reliability_lab.release` package.

**Tech Stack:** Python 3.11+, frozen dataclasses, standard-library JSON/path/UUID utilities, existing candidate-suite runner/comparator, and `unittest` with injected fake suite runners.

---

### Task 1: Activate Sprint 15

**Files:**
- Create: `sprints/gepa-release-gate-v1.md`
- Create: `docs/plans/2026-07-11-gepa-release-gate-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Record scope, non-scope, architecture, risks, and verification strategy.
2. Set Sprint 15 as active with an unchecked task list.
3. Preserve Sprint 14 as completed history.

### Task 2: Add fresh release scenarios

**Files:**
- Modify: `data/environment/support_env_v1.json`
- Create: `data/release/regression/northwind_lockout_v1.json`
- Create: `data/release/holdout/northwind_mfa_v1.json`
- Modify: `tests/test_scenarios.py`

**Steps:**
1. Write failing tests that load and validate every release scenario against a fresh environment state.
2. Add Northwind-specific ticket, user, auth, reset, verification, lockout, session, and MFA records.
3. Add one unverified-lockout regression and one MFA-only holdout fixture.
4. Run scenario and evaluator tests.

### Task 3: Add manifest and thresholds

**Files:**
- Create: `src/agent_reliability_lab/release/__init__.py`
- Create: `src/agent_reliability_lab/release/gate.py`
- Create: `tests/test_release_manifest.py`

**Steps:**
1. Write failing tests for empty, duplicate, overlapping, missing, and valid paths.
2. Add frozen `ReleaseSuiteManifest` with train/regression/holdout roles and repeat counts.
3. Add frozen `ReleaseThresholds` and `ReleaseGateConfig` with candidate and rollout-budget validation.
4. Prove over-budget configuration fails before any suite call.

### Task 4: Add three-state release decisions

**Files:**
- Modify: `src/agent_reliability_lab/release/gate.py`
- Create: `tests/test_release_gate.py`

**Steps:**
1. Write failing tests for promoted, regression-rejected, safety-rejected, holdout-rejected, and incomplete/inconclusive outcomes.
2. Add `ReleaseDecision`, `ReleaseGateResult`, and compact stage-result models.
3. Run baseline and candidate regression suites through the existing suite runner.
4. Compare regression suites through the existing comparator and apply strict per-scenario gates.
5. Run holdout only after regression passes and apply absolute thresholds.
6. Return stable reason codes and supporting run IDs.

### Task 5: Add report persistence and CLI

**Files:**
- Modify: `src/agent_reliability_lab/release/gate.py`
- Modify: `tests/test_release_gate.py`
- Modify: `.gitignore`

**Steps:**
1. Write failing tests for exclusive report creation and compact CLI output.
2. Add `.release-runs/`, UUID-backed release IDs, and `persist_release_result()` using exclusive file creation.
3. Add CLI arguments for baseline, candidate, manifest directories, repeats, rollout budget, run output, report output, and no-persist.
4. Load `.env` only in the CLI entry point and make no network calls in tests.

### Task 6: Export, document, verify, and close

**Files:**
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Export the release-gate public API from `agent_reliability_lab.release`.
2. Document suite isolation, decision semantics, command usage, and limitations.
3. Run all targeted tests, the complete suite, compile checks, and three offline smoke paths.
4. Review the full Sprint 15 change surface and side effects.
5. Mark Sprint 15 complete only after every verification item passes.
