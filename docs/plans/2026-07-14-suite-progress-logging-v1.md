# Suite Progress Logging V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make long live suites visibly active without breaking their JSON output contract.

**Architecture:** Extend the suite runner with an optional string callback and keep it disabled for library callers. The CLI supplies a flushed stderr printer, leaving stdout reserved for the final JSON summary.

**Tech Stack:** Python 3.11, argparse, unittest, stderr/stdout streams.

---

### Task 1: Specify progress behavior

**Files:**
- Modify: `tests/test_candidate_suite.py`

1. Add a library test that records start and completed messages for each rollout.
2. Add coverage for exception and non-comparable-agent terminal messages.
3. Extend the CLI test to capture stderr and verify stdout remains valid JSON.
4. Run the focused tests and confirm they fail.

### Task 2: Add progress reporting

**Files:**
- Modify: `src/agent_reliability_lab/runs/suite.py`

1. Add an optional `progress_callback` argument with a quiet default.
2. Emit `[current/total] starting` before each scenario runner call.
3. Emit `completed`, `failed`, or `invalid` after each runner result.
4. Pass a `print(..., file=sys.stderr, flush=True)` reporter from the CLI.
5. Preserve the final JSON summary on stdout.

### Task 3: Document, verify, and publish

**Files:**
- Modify: `docs/environment-v1.md`
- Modify: `sprints/suite-progress-logging-v1.md`
- Modify: `tasks/todo.md`

1. Document stderr progress and stdout JSON behavior.
2. Run targeted and full tests, compileall, CLI smoke, and diff checks.
3. Review compatibility, error paths, and side effects.
4. Commit and push the existing GPT-5.5 branch.
5. Update draft PR #2.
