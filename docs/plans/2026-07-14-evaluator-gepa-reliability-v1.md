# Evaluator + GEPA Reliability V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make evaluator feedback semantically accurate and let GEPA explore multiple valid prompt children without weakening safety or fatal-regression gates.

**Architecture:** Preserve deterministic checks and fixed agent runtime invariants. Split response-quality semantics at equal total weight, focus reflection on mutable behavior, and add bounded valid-child trials inside each logical GEPA generation with conservative deterministic selection.

**Tech Stack:** Python 3, unittest, OpenAI Responses API runner, deterministic scenario evaluator, GEPA prompt optimizer.

---

### Task 1: Evaluator semantics

**Files:**
- Modify: `src/agent_reliability_lab/evaluation/evaluator.py`
- Test: `tests/test_evaluator.py`

**Step 1:** Add failing tests for `account lock`, reordered reset-success language, exact near-prefix wrong-user IDs, explicit action confirmation, and independent safe-next-step guidance.

**Step 2:** Run `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_evaluator` and confirm the new tests fail for the intended reasons.

**Step 3:** Implement exact identifier boundaries and two response checks with weights `0.5` and `0.5`.

**Step 4:** Rerun the evaluator tests and confirm they pass.

### Task 2: Reflection focus

**Files:**
- Modify: `src/agent_reliability_lab/optimization/reflection.py`
- Test: `tests/test_gepa_reflection.py`

**Step 1:** Add a failing instruction-contract test for runtime invariants and mutable behavior.

**Step 2:** Update reflection instructions to preserve enforced workflow and optimize diagnosis, policy query, evidence composition, action confirmation, and safe next steps.

**Step 3:** Run `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_gepa_reflection`.

### Task 3: Comparison and acceptance

**Files:**
- Modify: `src/agent_reliability_lab/optimization/comparison.py`
- Modify: `src/agent_reliability_lab/optimization/gepa.py`
- Test: `tests/test_candidate_suite.py`
- Test: `tests/test_gepa_driver.py`

**Step 1:** Add failing tests for fatal eligibility regression and a 0.05 nonfatal score tolerance.

**Step 2:** Add eligibility deltas to per-scenario comparison and preserve serialization.

**Step 3:** Update acceptance ordering: safety, eligibility, pass rate, score beyond tolerance, measurable improvement.

### Task 4: Multi-child exploration

**Files:**
- Modify: `src/agent_reliability_lab/optimization/gepa.py`
- Test: `tests/test_gepa_driver.py`

**Step 1:** Add failing tests where child one is rejected and child two is accepted.

**Step 2:** Add `children_per_generation`, child-trial history, deterministic best-child selection, and CLI serialization.

**Step 3:** Preserve the existing top-level generation fields for backward-compatible consumers.

**Step 4:** Run targeted GEPA tests.

### Task 5: Integration verification

**Files:**
- Update: `sprints/evaluator-gepa-reliability-v1.md`
- Update: `tasks/todo.md`

**Step 1:** Run targeted tests, full tests, and compile verification.

**Step 2:** Run one controlled live optimization using two repeats and two children.

**Step 3:** Review safety, fatal eligibility, pass rates, score deltas, persisted history, and the final diff.
