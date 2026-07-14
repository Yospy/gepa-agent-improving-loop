# GEPA Quality Hardening V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the mutation-validation false positive and make one-child GEPA evolution produce more actionable, retryable prompt improvements without weakening evaluation.

**Architecture:** Correct identifier matching and evaluator feedback at their sources, keep the existing reflection JSON contract, and add one validation-aware retry through a revision field on the reflection bundle. Preserve the terminal mutation field for existing history consumers while recording every attempt separately.

**Tech Stack:** Python 3.11+, frozen dataclasses, standard-library regex/JSON, existing Responses client abstraction, and `unittest` with injected fake clients.

---

### Task 1: Identifier validation correctness

**Files:**
- Modify: `tests/test_gepa_reflection.py`
- Modify: `src/agent_reliability_lab/optimization/reflection.py`

1. Add a failing test whose feedback exposes `mfa_status` but whose child
   instruction legitimately names `get_mfa_status`.
2. Confirm the existing substring check rejects it.
3. Replace substring matching with complete underscore-aware token matching.
4. Keep tests proving exact scenario and record identifiers remain rejected.
5. Run `tests.test_gepa_reflection`.

### Task 2: Actionable evaluator feedback

**Files:**
- Modify: `tests/test_evaluator.py`
- Modify: `src/agent_reliability_lab/evaluation/evaluator.py`

1. Add a failing test that calls `get_auth_logs` for the requester with a narrow
   time window that excludes pre-lockout events.
2. Require feedback to distinguish the call from a missing tool and recommend
   reviewing its time window/filter.
3. Add a failing test for `successful support verification and password reset`.
4. Add structured missing-evidence diagnostics and bounded reset-success patterns.
5. Run evaluator tests and confirm anti-keyword-stuffing tests still pass.

### Task 3: Operational reflection contract

**Files:**
- Modify: `tests/test_gepa_reflection.py`
- Modify: `src/agent_reliability_lab/optimization/reflection.py`

1. Assert reflection instructions require explicit investigation order,
   requester binding, time-window reasoning, record-ID citation, policy-safe
   writes, and final-response requirements.
2. Add `revision_feedback: str | None` to `ReflectionBundle` and serialize it
   only when present.
3. Confirm hidden-truth containers remain absent from reflection input.

### Task 4: One audited mutation retry

**Files:**
- Modify: `tests/test_gepa_driver.py`
- Modify: `src/agent_reliability_lab/optimization/gepa.py`
- Modify: `src/agent_reliability_lab/optimization/reflection.py`

1. Add config validation for `max_mutation_attempts` and default it to `2`.
2. Add a failing driver test: first proposal is unchanged, retry bundle contains
   the validation error, second proposal succeeds, and the child runs once.
3. Add ordered `mutation_attempts` while retaining terminal `mutation`.
4. Retry `invalid_response` and local instruction-validation errors once; do not
   retry API/transport failures.
5. Add `--max-mutation-attempts` to the CLI and serialized config.
6. Run driver, reflection, and release-history tests.

### Task 5: Documentation and full verification

**Files:**
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`
- Modify: `sprints/gepa-quality-hardening-v1.md`

1. Document exact identifier behavior, actionable feedback, retry semantics,
   history compatibility, and CLI usage.
2. Run targeted tests, full tests, and compilation.
3. Review changes for hidden-truth leakage, unbounded retries, history breakage,
   score weakening, and unrelated edits.
4. Record results and close the sprint checklist.
