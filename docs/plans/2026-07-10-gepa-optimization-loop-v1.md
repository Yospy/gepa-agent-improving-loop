# GEPA Optimization Loop V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a bounded, offline-testable GEPA loop that reflects on evaluated parent runs, creates a validated child prompt, evaluates equal parent/child suites, and deterministically accepts or rejects each generation.

**Architecture:** Keep reflection and candidate creation in a pure mutation module, and keep suite execution plus generation control in a separate optimizer driver. Compose the existing `CandidatePool`, `CandidateSuiteRun`, `run_candidate_suite()`, and `compare_candidate_suites()` contracts rather than adding parallel scoring or evaluation paths.

**Tech Stack:** Python 3.11+, frozen dataclasses, standard-library JSON/hash/UUID/path utilities, existing OpenAI Responses client abstraction, and `unittest` with injected fakes.

---

### Task 1: Activate Sprint 14

**Files:**
- Create: `sprints/gepa-optimization-loop-v1.md`
- Create: `docs/plans/2026-07-10-gepa-optimization-loop-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Record scope, assumptions, architecture, risks, definition of done, and verification.
2. Set Sprint 14 as active and add unchecked execution tasks.
3. Confirm Sprint 13 remains recorded as complete.

### Task 2: Add candidate-pool extension and reflection tests

**Files:**
- Modify: `src/agent_reliability_lab/optimization/candidates.py`
- Create: `tests/test_gepa_reflection.py`

**Steps:**
1. Write a failing test proving `CandidatePool.with_candidate()` returns a new pool and leaves the source unchanged.
2. Run `PYTHONPATH=src python3 -m unittest tests.test_gepa_reflection` and confirm the missing API failure.
3. Implement `with_candidate()` by reconstructing `CandidatePool` with the appended candidate so all existing validation is reused.
4. Run the targeted test and confirm it passes.

### Task 3: Build deterministic reflection examples

**Files:**
- Create: `src/agent_reliability_lab/optimization/reflection.py`
- Modify: `tests/test_gepa_reflection.py`

**Steps:**
1. Write failing tests for complete-suite enforcement, one lowest-score example per scenario, deterministic tie-breaking, and required evaluator field validation.
2. Run the reflection tests and confirm failures.
3. Add frozen `ReflectionExample` and `ReflectionBundle` models with `to_dict()` methods.
4. Implement `build_reflection_bundle(parent, suite_run)` with parent/suite identity checks and deterministic record selection.
5. Run reflection tests and confirm they pass.

### Task 4: Add strict mutation and live/fake reflection boundary

**Files:**
- Modify: `src/agent_reliability_lab/optimization/reflection.py`
- Modify: `tests/test_gepa_reflection.py`

**Steps:**
1. Write failing tests for reflection prompt contents, strict JSON parsing, API errors, unchanged prompts, size limits, identifier memorization, and valid child lineage.
2. Run the reflection tests and confirm failures.
3. Add `ReflectionClient`, `OpenAIReflectionClient`, `MutationProposal`, `MutationError`, and `MutationResult` contracts.
4. Format optimizer-only JSON input and call the existing Responses abstraction without tools.
5. Parse exactly `analysis` and `system_instruction`; reject invalid or unsafe proposals before candidate creation.
6. Generate stable human-readable IDs with UUID suffixes and store mutation provenance inside the child payload under `optimizer_metadata`, leaving `system_instruction` as the only agent-consumed mutable field.
7. Run reflection and OpenAI-agent tests.

### Task 5: Add deterministic acceptance policy

**Files:**
- Create: `src/agent_reliability_lab/optimization/gepa.py`
- Create: `tests/test_gepa_driver.py`

**Steps:**
1. Write failing tests for acceptance, pass regression, score regression, safety regression, and unchanged outcomes.
2. Run `PYTHONPATH=src python3 -m unittest tests.test_gepa_driver` and confirm failures.
3. Add `AcceptanceDecision` and `decide_candidate_acceptance()` using per-scenario comparison deltas.
4. Run driver tests and confirm they pass.

### Task 6: Add the bounded GEPA driver

**Files:**
- Modify: `src/agent_reliability_lab/optimization/gepa.py`
- Modify: `tests/test_gepa_driver.py`

**Steps:**
1. Write failing tests for config validation, accepted-child iteration, perfect-parent short circuit, invalid mutation, reflection failure, incomplete parent/child suite, rejection, and max-generation stopping.
2. Add frozen `GEPAConfig`, `GEPAGeneration`, and `GEPAOptimizationResult` models.
3. Implement `run_gepa_optimization()` with injected suite runner, reflection client, ID factory, and clock.
4. Reuse accepted child suite results as the next generation's parent results.
5. Ensure no child suite runs after invalid mutation or reflection failure.
6. Run driver tests and confirm they pass.

### Task 7: Add history persistence and CLI

**Files:**
- Modify: `src/agent_reliability_lab/optimization/gepa.py`
- Modify: `tests/test_gepa_driver.py`

**Steps:**
1. Write failing tests for collision-safe exclusive history creation and compact CLI JSON output.
2. Add `.gepa-runs` default output, UUID-backed optimization IDs, and `persist_gepa_result()` using exclusive file creation.
3. Add `main()` arguments for candidate, scenario directory, repeat count, generation count, model, run output, history output, and no-persist mode.
4. Load `.env` only in the CLI entry point, matching the existing recorder boundary.
5. Run targeted CLI/persistence tests.

### Task 8: Export and document the feature

**Files:**
- Modify: `src/agent_reliability_lab/optimization/__init__.py`
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Export reflection, mutation, acceptance, and driver public contracts without creating import cycles.
2. Document the live command, offline test boundary, mutation surface, acceptance semantics, and Sprint 15 non-scope.
3. Keep Sprint 14 active until verification and review complete.

### Task 9: Verify and review

**Files:**
- Review all Sprint 14 files.
- Modify: `tasks/todo.md`

**Steps:**
1. Run all targeted Sprint 14 and regression tests from the sprint verification strategy.
2. Run `PYTHONPATH=src python3 -m unittest discover -s tests` and require all tests to pass.
3. Run `python3 -m compileall -q src tests`.
4. Run a deterministic offline end-to-end smoke test.
5. Review the complete diff for minimality, architectural drift, visibility boundaries, mutation validation, bounded execution, persistence safety, and unrelated changes.
6. Mark Sprint 14 checklist items complete only after every verification item succeeds.
