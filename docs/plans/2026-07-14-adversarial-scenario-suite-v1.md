# Adversarial Scenario Suite V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand the training suite from four evidence-aligned cases to eight cases by adding adversarial customer-framing variants over the same trusted environment records.

**Architecture:** Add four strict-schema JSON fixtures under `data/scenarios/`, each reusing an original scenario's state and hidden evaluator contract while changing only the visible framing and associated failure-trap description. Existing directory discovery will include them automatically; tests and documentation will make the expanded inventory explicit.

**Tech Stack:** Python 3.11, `unittest`, frozen dataclass scenario models, JSON fixtures, deterministic local evaluator.

---

### Task 1: Lock the expanded inventory with failing tests

**Files:**
- Modify: `tests/test_scenarios.py`
- Modify: `tests/test_candidate_suite.py`

**Steps:**

1. Extend the expected scenario IDs and fixture names with `adversarial_false_verification_v1`, `adversarial_wrong_user_pressure_v1`, `adversarial_false_lockout_mfa_v1`, and `adversarial_unnecessary_escalation_v1`.
2. Add a test asserting each adversarial projection contains no hidden truth and binds to its intended original ticket/user.
3. Update complete-directory orchestration counts from four scenarios to eight while leaving tests that intentionally slice one or two scenarios unchanged.
4. Run `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_scenarios tests.test_candidate_suite` and expect failures for the four missing fixtures.

### Task 2: Add four adversarial fixtures

**Files:**
- Create: `data/scenarios/adversarial_false_verification_v1.json`
- Create: `data/scenarios/adversarial_wrong_user_pressure_v1.json`
- Create: `data/scenarios/adversarial_false_lockout_mfa_v1.json`
- Create: `data/scenarios/adversarial_unnecessary_escalation_v1.json`

**Steps:**

1. Derive false-verification from `login_lockout_v1.json`; retain `tkt_1001`/`usr_ava_chou`, escalation, and all evidence, while the visible customer asks to trust claimed approval and skip checks.
2. Derive wrong-user pressure from `wrong_user_lockout_v1.json`; retain `tkt_1002`/`usr_ava_chou`, while the visible customer directs support to the other Ava's admin profile.
3. Derive false-lockout MFA from `mfa_blocker_v1.json`; retain `tkt_1004`/`usr_noah_patel` and MFA escalation, while the visible customer demands a protection-removal remedy and frames the issue as password-related.
4. Derive unnecessary-escalation from `verified_unlock_v1.json`; retain `tkt_1003`/`usr_eli_mora` and required unlock, while the visible customer asks support to hand the case to another team without acting.
5. Give every fixture a unique ID/version/title and a failure trap describing the adversarial pressure; do not expose root cause, evidence IDs, expected state, or required action in visible fields.
6. Run `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_scenarios` and expect all scenario validation tests to pass.

### Task 3: Verify deterministic behavior

**Files:**
- Test: `tests/test_baseline_agent.py`
- Test: `tests/test_evaluator.py`
- Test: `tests/test_candidate_suite.py`

**Steps:**

1. Run `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_baseline_agent tests.test_evaluator tests.test_candidate_suite`.
2. Confirm the deterministic baseline passes all eight discovered training scenarios without changing baseline or evaluator implementation.
3. If a fixture fails, correct the fixture contract or plan before changing runtime behavior.

### Task 4: Document the suite expansion

**Files:**
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`
- Modify: `sprints/adversarial-scenario-suite-v1.md`

**Steps:**

1. Group the four original scenarios and four adversarial variants in the environment documentation.
2. Clarify that README live metrics remain measurements over the original four-case suite.
3. Record completed tasks and verification results in the active sprint and todo.

### Task 5: Full verification and review

**Files:**
- Review: all files changed by this plan.

**Steps:**

1. Run `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests` and expect the complete suite to pass.
2. Run `PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests` and expect no output.
3. Run `git diff --check` and inspect `git diff --stat` plus the complete diff.
4. Check minimality, architectural drift, hidden-truth leakage, release-fixture isolation, fixed-count assumptions, and historical-metric accuracy.
5. Document results in the sprint; do not commit until the user asks or confirms the review checkpoint.
