# Candidate Pool Selection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first local optimizer substrate: registered candidates, generic candidate runs, score matrix aggregation, Pareto frontier, and deterministic parent selection.

**Architecture:** Candidate metadata lives in `agent_reliability_lab.optimization`; runnable deterministic agents live in `agent_reliability_lab.agents`. The existing recorder remains the source of persisted trajectories, with candidate metadata added to run records. Score matrix and selection consume run records only.

**Tech Stack:** Python 3.11 standard library, dataclasses, unittest, existing environment/scenario/tool/evaluator/recorder modules.

---

### Task 1: Candidate Pool

**Files:**
- Create: `src/agent_reliability_lab/optimization/__init__.py`
- Create: `src/agent_reliability_lab/optimization/candidates.py`
- Test: `tests/test_candidate_optimization.py`

**Steps:**
1. Add `Candidate` and `CandidatePool`.
2. Register baseline plus deterministic synthetic candidate metadata.
3. Verify candidate IDs are unique and baseline is present.

### Task 2: Generic Candidate Runner

**Files:**
- Create: `src/agent_reliability_lab/agents/variants.py`
- Modify: `src/agent_reliability_lab/agents/__init__.py`
- Modify: `src/agent_reliability_lab/runs/models.py`
- Modify: `src/agent_reliability_lab/runs/recorder.py`
- Modify: `src/agent_reliability_lab/runs/__init__.py`
- Test: `tests/test_candidate_optimization.py`

**Steps:**
1. Add deterministic failing/partial support-agent variants.
2. Add `run_candidate_scenario`.
3. Persist candidate ID, parent ID, and generation in run records.
4. Keep `run_baseline_scenario` backward compatible.

### Task 3: Score Matrix

**Files:**
- Create: `src/agent_reliability_lab/optimization/scoring.py`
- Test: `tests/test_candidate_optimization.py`

**Steps:**
1. Aggregate run records by candidate and scenario.
2. Compute run count, pass rate, average score, failure counts, and safety failures.
3. Preserve scenario IDs in every cell.

### Task 4: Pareto Selection

**Files:**
- Create: `src/agent_reliability_lab/optimization/selection.py`
- Modify: `src/agent_reliability_lab/optimization/__init__.py`
- Test: `tests/test_candidate_optimization.py`

**Steps:**
1. Compute non-dominated candidates using pass rate, average score, and safety failures.
2. Select one parent from safety-eligible frontier candidates with deterministic weighted scoring.
3. Tie-break by candidate ID.

### Task 5: Docs and Verification

**Files:**
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Document Phase 9-10 commands and boundaries.
2. Run targeted and full tests.
3. Run compile verification.
4. Review diff and confirm no Phase 11 mutation/model-call scope leaked in.
