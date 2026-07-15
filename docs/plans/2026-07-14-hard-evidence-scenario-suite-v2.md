# Hard Evidence Scenario Suite V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the saturated eight-case benchmark with eight solvable but materially harder evidence-reasoning cases that produce useful GEPA prompt-optimization signal.

**Architecture:** Add an isolated Contoso dataset to the shared environment and rewrite the eight training fixtures around chronology, mixed evidence, reset ordering, compromise exceptions, and verification expiry. Generalize the OpenAI runner to expose both writes after evidence collection, retain tool-level safety enforcement, and extend evaluator semantics only where new ground truth requires it.

**Tech Stack:** Python 3.11, `unittest`, strict JSON fixtures, dataclass environment models, deterministic evaluator, OpenAI Responses API runner.

---

### Task 1: Write failing contracts

**Files:**
- Modify: `tests/test_environment_state.py`
- Modify: `tests/test_support_tools.py`
- Modify: `tests/test_openai_agent.py`
- Modify: `tests/test_scenarios.py`
- Modify: `tests/test_evaluator.py`
- Modify: `tests/test_baseline_agent.py`

**Steps:**

1. Assert all eight Contoso ticket/user bindings and V2 scenario IDs.
2. Assert unlock denial for expired verification and unresolved compromise.
3. Assert both write schemas are available after evidence/policy completion and escalation-only recovery follows denied unlock.
4. Assert genuine reset-failure responses are accepted only in the reset-failure scenario while successful-reset cases retain hallucination rejection.
5. Assert compromise and expired-verification scenarios require the distinguishing customer-response language.
6. Run the focused tests and confirm failures before implementation.

### Task 2: Add the independent hard-case environment

**Files:**
- Modify: `data/environment/support_env_v1.json`
- Modify: `tests/test_environment_state.py`

**Steps:**

1. Add Contoso organization/account, eight users, and eight tickets (`tkt_7001` through `tkt_7008`).
2. Add scenario-specific auth/reset/verification/lockout/MFA/session records with deterministic timestamps and unique IDs.
3. Add active password-reset recovery and account-compromise policies.
4. Validate strict environment loading and cross-record integrity.

### Task 3: Replace all eight training fixtures

**Files:**
- Modify: all eight JSON files under `data/scenarios/`.
- Modify: `tests/test_scenarios.py`

**Steps:**

1. Map the eight fixture filenames to the V2 hard-case matrix documented in the sprint.
2. Bind every required evidence ID to real Contoso records.
3. Keep visible prompts neutral and hidden truth excluded.
4. Run scenario validation tests and correct fixture contracts only.

### Task 4: Restore prompt-controlled action selection safely

**Files:**
- Modify: `src/agent_reliability_lab/agents/openai_runner.py`
- Modify: `src/agent_reliability_lab/environment/tools.py`
- Modify: `tests/test_openai_agent.py`
- Modify: `tests/test_support_tools.py`

**Steps:**

1. Return both bound write schemas after active policy observation.
2. Preserve escalation-only recovery after a denied unlock.
3. Make verification validity use the latest record and expiry time.
4. Deny unlock when an auth event contains an unresolved compromise indicator.
5. Run runner/tool tests and confirm unsafe state mutations remain impossible.

### Task 5: Extend deterministic interpretation

**Files:**
- Modify: `src/agent_reliability_lab/scenarios/validation.py`
- Modify: `src/agent_reliability_lab/evaluation/evaluator.py`
- Modify: `src/agent_reliability_lab/agents/baseline.py`
- Modify: `tests/test_evaluator.py`
- Modify: `tests/test_baseline_agent.py`

**Steps:**

1. Add reset-failure evidence validation without weakening successful-reset validation.
2. Make reset-failure hallucination checks scenario-dependent.
3. Require compromise and expired-verification acknowledgement only for matching roots.
4. Make verified-identity evidence accept the policy-safe escalation path when unlock is forbidden by another gate.
5. Update the deterministic oracle to use a broad evidence window, latest-event ordering, and compromise/expiry branches.
6. Run focused evaluator and baseline tests.

### Task 6: Verify, document, and run live

**Files:**
- Modify: `README.md`
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`
- Modify: `sprints/hard-evidence-scenario-suite-v2.md`

**Steps:**

1. Run the full offline verification matrix and structured review.
2. Document the V2 suite and preserve historical metric scope.
3. Run the live GPT-5.5 baseline once across all eight cases.
4. Inspect persisted failed trajectories, separate prompt failures from evaluator/runtime defects, and record the concrete GEPA improvement targets.
5. Do not commit until the user requests the checkpoint.
