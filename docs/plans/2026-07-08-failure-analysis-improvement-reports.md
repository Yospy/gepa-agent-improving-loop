# Failure Analysis Improvement Reports Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the offline loop from persisted run records to failure summaries, improvement targets, and version/run-set comparisons.

**Architecture:** Add a pure analysis package that reads local JSON run records and uses evaluator `failure_tags` as the source of truth. Keep output deterministic dataclasses and JSON, with no model calls or prompt optimizer.

**Tech Stack:** Python 3.11 standard library, dataclasses, JSON, argparse, unittest, existing run/evaluator records.

---

### Task 1: Failure Analysis Module

**Files:**
- Create: `src/agent_reliability_lab/analysis/__init__.py`
- Create: `src/agent_reliability_lab/analysis/failures.py`
- Test: `tests/test_failure_analysis.py`

**Steps:**
1. Write tests for loading a generated baseline run and synthetic failed records.
2. Implement run-record loading from a file or directory of `.json` records.
3. Implement canonical failure summaries for required evaluator tags.
4. Run `python3 -m unittest tests.test_failure_analysis`.

### Task 2: Improvement Reports and Comparisons

**Files:**
- Modify: `src/agent_reliability_lab/analysis/failures.py`
- Test: `tests/test_failure_analysis.py`

**Steps:**
1. Add report rows with agent version, scenario ID, pass/fail, score, failure tags, and deterministic improvement targets.
2. Add comparison helpers for two run sets and two agent versions.
3. Run `python3 -m unittest tests.test_failure_analysis`.

### Task 3: CLI and Docs

**Files:**
- Modify: `src/agent_reliability_lab/analysis/failures.py`
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Add `python3 -m agent_reliability_lab.analysis.failures .runs` CLI JSON output.
2. Document the analysis command and output boundary.
3. Run `python3 -m unittest discover -s tests`.
4. Run `python3 -m compileall -q src tests`.
5. Review `git diff --stat` and full diff for scope drift.
