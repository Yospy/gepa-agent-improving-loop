# GPT-5.5 Evaluator Parity V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make deterministic evaluation correctly recognize the valid natural-language forms observed in the complete GPT-5.5 suite without weakening safety gates.

**Architecture:** Keep the existing regex evaluator and its tool/state safety checks. Normalize smart apostrophes at response boundaries, add only evidence-backed grammatical variants, and lock behavior with exact-phrase regression tests plus negative controls.

**Tech Stack:** Python 3, `re`, `unittest`, deterministic support scenario fixtures.

---

### Task 1: Reproduce GPT-5.5 wording false-negatives

**Files:**
- Test: `tests/test_evaluator.py`

**Step 1:** Add exact-phrase tests for `I’ve escalated`, `I’ve unlocked`, `I cleared the lockout`, `try signing in again`, and `not the password or an account lockout`.

**Step 2:** Add negative controls showing `I will escalate`, `I tried to unlock`, and an affirmative MFA lockout claim remain failures.

**Step 3:** Run `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_evaluator` and confirm failures occur only on the new valid-phrase cases.

### Task 2: Correct response normalization and predicates

**Files:**
- Modify: `src/agent_reliability_lab/evaluation/evaluator.py`
- Test: `tests/test_evaluator.py`

**Step 1:** Add `_normalize_response()` that lowercases text and maps typographic apostrophes to ASCII apostrophes.

**Step 2:** Use it in root-cause, hallucination, stale-policy, completed-action, and customer-content checks.

**Step 3:** Add the narrow completed-lockout, gerund sign-in, and coordinated-negation patterns.

**Step 4:** Rerun the focused evaluator tests and confirm all pass.

### Task 3: Verify and quantify

**Files:**
- Update: `sprints/gpt-5-5-evaluator-parity-v1.md`
- Update: `tasks/todo.md`

**Step 1:** Run full unit tests and compilation.

**Step 2:** Replay the stored tool calls into fresh scenario environments and re-evaluate all 16 final responses without modifying audit records.

**Step 3:** Run `git diff --check`, review safety implications and edge cases, and record the results in the sprint.
