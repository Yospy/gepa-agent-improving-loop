# Reward Contract V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the deterministic evaluator so every run produces score, fatal eligibility gates, and rich deterministic feedback text for GEPA reflection.

**Architecture:** Extend existing evaluation models and evaluator helpers. Feedback is assembled from already-available deterministic data: check messages, check details, scenario expected evidence, tool-call trace, final response, and final state mismatches. Candidate scoring consumes the new eligibility field without adding mutation or LLM calls.

**Tech Stack:** Python 3.11 standard library, dataclasses, unittest, existing evaluator/run/candidate modules.

---

### Task 1: Evaluation Contract Fields

**Files:**
- Modify: `src/agent_reliability_lab/evaluation/models.py`
- Modify: `src/agent_reliability_lab/evaluation/evaluator.py`
- Test: `tests/test_evaluator.py`

**Steps:**
1. Add `FATAL_FAILURE_TAGS`.
2. Add `fatal_tags`, `nonfatal_tags`, `eligible_for_selection`, `feedback_text`, and `trace_excerpt`.
3. Keep `to_agent_visible_dict()` limited to `passed` and `score`.

### Task 2: Deterministic Feedback Formatter

**Files:**
- Modify: `src/agent_reliability_lab/evaluation/evaluator.py`
- Test: `tests/test_evaluator.py`

**Steps:**
1. Format failed checks as `[FAIL] check_name`.
2. Include deterministic expected-vs-observed details for tools, evidence, policy escalation, forbidden actions, final state, and response checks.
3. Include a concise tool-call trace and final response excerpt.

### Task 3: Optimizer Eligibility Consumption

**Files:**
- Modify: `src/agent_reliability_lab/optimization/scoring.py`
- Modify: `src/agent_reliability_lab/optimization/selection.py`
- Test: `tests/test_candidate_optimization.py`

**Steps:**
1. Add fatal failure counts and eligibility to matrix cells and candidate summaries.
2. Treat older run records as eligible only when they have no fatal tags.
3. Filter parent selection by evaluator eligibility.

### Task 4: Docs and Verification

**Files:**
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Document Reward Contract V1.
2. Run targeted tests and full suite.
3. Run compile verification.
4. Run subagent code review and address actionable findings.
