# Baseline Agent Run Recorder Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first offline full loop from scenario-visible input through baseline agent, run recording, and deterministic evaluation.

**Architecture:** Keep the baseline deterministic and tool-driven. Add a run orchestration layer that owns environment/scenario loading, state snapshots, evaluator invocation, and JSON persistence.

**Tech Stack:** Python 3.11 standard library, dataclasses, unittest, existing local environment/tool/scenario/evaluator modules.

---

### Task 1: Baseline Agent

**Files:**
- Create: `src/agent_reliability_lab/agents/__init__.py`
- Create: `src/agent_reliability_lab/agents/baseline.py`
- Test: `tests/test_baseline_agent.py`

**Steps:**
1. Write a failing test that runs the baseline against `support_login_lockout_v1` and expects a passing evaluation.
2. Implement an offline `BaselineSupportAgent` that uses only `SupportToolService`.
3. Run `python3 -m unittest tests.test_baseline_agent`.

### Task 2: Run Records

**Files:**
- Create: `src/agent_reliability_lab/runs/__init__.py`
- Create: `src/agent_reliability_lab/runs/models.py`
- Create: `src/agent_reliability_lab/runs/recorder.py`
- Test: `tests/test_run_recorder.py`

**Steps:**
1. Write tests for run IDs, hashes, tool-call capture, evaluation capture, and JSON persistence.
2. Implement `RunRecord`, `RunRecorder`, and `run_baseline_scenario`.
3. Run `python3 -m unittest tests.test_run_recorder`.

### Task 3: Docs and Verification

**Files:**
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Document the baseline run command, output path, and run-record boundary.
2. Run `python3 -m unittest discover -s tests`.
3. Run `python3 -m compileall -q src tests`.
4. Review `git diff --stat` and full diff for scope drift.
