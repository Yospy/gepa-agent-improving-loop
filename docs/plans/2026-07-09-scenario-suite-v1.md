# Scenario Suite V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a small scenario suite so future GEPA runs evaluate candidates across multiple support tasks instead of one fixture.

**Architecture:** Scenarios remain JSON fixtures with hidden truth and visible projections. The shared environment seed gains only visible support/auth records. Validation and evaluation are generalized just enough to bind arbitrary scenario ticket/user pairs against the seed and score scenario-specific evidence, write actions, final state, and root-cause response.

**Tech Stack:** Python 3.11 standard library, dataclasses, JSON fixtures, unittest, existing environment/tool/evaluator modules.

---

### Task 1: Environment Records

**Files:**
- Modify: `data/environment/support_env_v1.json`
- Test: `tests/test_environment_state.py`

**Steps:**
1. Add realistic tickets and supporting records for wrong-user, verified-unlock, and MFA scenarios.
2. Keep the original `tkt_1001` primary scenario unchanged.
3. Run environment tests to ensure references and hidden-truth boundaries remain valid.

### Task 2: Scenario Suite Fixtures

**Files:**
- Create: `data/scenarios/wrong_user_unlock_v1.json`
- Create: `data/scenarios/verified_unlock_v1.json`
- Create: `data/scenarios/mfa_blocker_v1.json`
- Modify: `src/agent_reliability_lab/scenarios/store.py`
- Modify: `src/agent_reliability_lab/scenarios/__init__.py`
- Test: `tests/test_scenarios.py`

**Steps:**
1. Add three fixtures that reference real environment records.
2. Add `DEFAULT_SCENARIO_DIR` and `load_scenario_suite()`.
3. Test that every fixture validates and visible projections omit hidden truth.

### Task 3: Validation Generalization

**Files:**
- Modify: `src/agent_reliability_lab/scenarios/validation.py`
- Test: `tests/test_scenarios.py`

**Steps:**
1. Remove primary-ticket-only validation for scenario metadata.
2. Require scenario ticket and user to exist and match each other.
3. Validate evidence record IDs generically.
4. Keep semantic lockout checks for scenarios whose root cause contains lockout.

### Task 4: Evaluator Generalization

**Files:**
- Modify: `src/agent_reliability_lab/evaluation/evaluator.py`
- Test: `tests/test_evaluator.py`

**Steps:**
1. Derive required read tools from required evidence record types.
2. Derive response root-cause checks from scenario root-cause keywords.
3. Validate expected write action as `escalate_case`, `unlock_user`, or no write.
4. Keep existing anti-hacking/fatal gates working for the original scenario.

### Task 5: Docs and Verification

**Files:**
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Document Scenario Suite V1 and GEPA matrix relevance.
2. Run targeted tests, full tests, compileall, and self-review.
