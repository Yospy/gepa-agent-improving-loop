# Integration Smoke Hardening V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Repair the two end-to-end failures found after Sprint 15 and encode both smoke paths as automated regressions.

**Architecture:** Generalize the existing deterministic baseline using only agent-visible tool observations, with separate MFA, verified-lockout, and unverified-lockout decisions. Restore normal Python module execution ordering for the release CLI and cover it through a subprocess rather than an imported/mocked call.

**Tech Stack:** Python 3.11+, standard-library `unittest` and `subprocess`, existing support tools, evaluator, suite runner, and release gate.

---

### Task 1: Baseline suite regression

**Files:**
- Modify: `tests/test_baseline_agent.py`
- Modify: `src/agent_reliability_lab/agents/baseline.py`

1. Add a test that loads every training scenario, runs the real baseline, and
   requires a passing deterministic evaluation.
2. Run the test and confirm the current MFA failure.
3. Retain the existing common evidence-gathering sequence.
4. Detect MFA-stage failures from auth output and escalate with reset, auth,
   MFA, session, and active-policy record identifiers.
5. For lockout evidence, unlock only when trusted ticket metadata says the
   requester is verified; otherwise escalate with lockout evidence.
6. Run baseline and evaluator tests and require every scenario to pass.

### Task 2: Release module-entry regression

**Files:**
- Modify: `tests/test_release_gate.py`
- Modify: `src/agent_reliability_lab/release/gate.py`

1. Add a subprocess test invoking
   `python -m agent_reliability_lab.release.gate` with deterministic candidates,
   one repeat, an intentionally insufficient rollout budget, and no persistence.
2. Assert the process does not report a `NameError` and reaches the expected
   validated rollout-budget preflight result. Behavioral verdict paths remain
   covered by the existing injected-runner CLI and orchestration tests because
   registered offline candidates intentionally belong to different families.
3. Run the test and confirm the current helper-definition failure.
4. Move the module guard below all helper definitions.
5. Rerun release tests and the exact offline CLI smoke command.

### Task 3: Full verification and review

**Files:**
- Modify: `tasks/todo.md`

1. Run all 126+ tests verbosely.
2. Compile all source and test modules.
3. Run the real baseline suite smoke test and require four complete passing
   records.
4. Run the release CLI as a subprocess and require validated budget preflight
   rather than a module-definition failure.
5. Review the diff for hidden-truth leakage, unsafe unlock behavior, duplicated
   policy logic, unrelated changes, and documentation accuracy.
6. Mark the corrective sprint complete in `tasks/todo.md`.
