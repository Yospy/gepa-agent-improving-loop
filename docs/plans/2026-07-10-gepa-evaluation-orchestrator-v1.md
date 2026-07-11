# GEPA Evaluation Orchestrator V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run a candidate across a complete repeated scenario suite, aggregate the existing deterministic evaluations, and compare two candidates scenario-by-scenario without permitting missing or infrastructure-corrupted evidence.

**Architecture:** Keep `run_candidate_scenario()` as the one-rollout primitive. Add suite orchestration under `runs`, coverage enforcement and pure comparison under `optimization`, and a small JSON CLI. A suite is comparable only when every expected scenario/repeat slot produces a valid evaluated record.

**Tech Stack:** Python 3.11 standard library, frozen dataclasses, `uuid`, existing scenario/run/evaluation/optimization modules, `unittest`.

---

### Task 1: Collision-Safe Run Persistence

**Files:**
- Modify: `src/agent_reliability_lab/runs/recorder.py`
- Test: `tests/test_run_recorder.py`

**Step 1: Write the failing fixed-clock repeat test**

Add a test that runs the same candidate/scenario twice with the same fixed clock
inside one temporary output directory. Assert that both `run_id` values differ,
both JSON paths exist, and the directory contains two files.

**Step 2: Write the failing overwrite-protection test**

Save the exact same `RunRecord` twice through `RunRecorder`. Assert the second
save raises `FileExistsError` instead of replacing the first file.

**Step 3: Run the tests and confirm the current collision**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_run_recorder
```

Expected: the repeated fixed-clock run reuses one ID/path or the overwrite test
does not raise.

**Step 4: Implement unique and exclusive persistence**

Update `_build_run_id()` to retain the timestamp and readable scenario/version
slug, then append `uuid.uuid4().hex`. Open the destination with mode `"x"` in
`RunRecorder.save()`.

Target shape:

```python
return f"run_{timestamp}_{slug}_{uuid4().hex}"
```

**Step 5: Run the targeted tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_run_recorder
```

Expected: PASS.

**Step 6: Commit**

```bash
git add src/agent_reliability_lab/runs/recorder.py tests/test_run_recorder.py
git commit -m "fix: make repeated run persistence collision-safe"
```

### Task 2: Explicit Agent Failure Provenance

**Files:**
- Modify: `src/agent_reliability_lab/runs/models.py`
- Modify: `src/agent_reliability_lab/runs/recorder.py`
- Test: `tests/test_openai_agent.py`
- Test: `tests/test_run_recorder.py`

**Step 1: Write the failing provenance tests**

Add an API-error test through `run_candidate_scenario()` and assert:

```python
self.assertEqual(record.agent_failure_reason, "api_error")
```

Also assert `agent_failure_reason` is absent from
`RunRecord.to_agent_visible_dict()` and is `None` for a successful baseline run.
Keep the existing direct-agent max-step test unchanged; Sprint 13 does not need
to add max-step configurability to `run_candidate_scenario()`.

**Step 2: Run the tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_openai_agent tests.test_run_recorder
```

Expected: FAIL because `RunRecord` does not expose internal failure provenance.

**Step 3: Implement the minimal internal field**

Add this backward-compatible field to the end of `RunRecord`:

```python
agent_failure_reason: str | None = None
```

In the recorder, populate it through a small safe helper:

```python
def _agent_failure_reason(result: Any) -> str | None:
    value = getattr(result, "failure_reason", None)
    return value if isinstance(value, str) and value else None
```

Do not add it to the agent-visible projection.

**Step 4: Run the targeted tests**

Run the command from Step 2. Expected: PASS.

**Step 5: Commit**

```bash
git add src/agent_reliability_lab/runs/models.py src/agent_reliability_lab/runs/recorder.py tests/test_openai_agent.py tests/test_run_recorder.py
git commit -m "feat: record agent failure provenance"
```

### Task 3: Candidate Suite Models and Orchestration

**Files:**
- Create: `src/agent_reliability_lab/runs/suite.py`
- Modify: `src/agent_reliability_lab/runs/__init__.py`
- Create: `tests/test_candidate_suite.py`

**Step 1: Write failing suite-spec validation tests**

Cover an empty name, no scenario paths, duplicate paths, and repeat counts of
zero or less. Each invalid spec must raise `ValueError` before execution.

**Step 2: Write the failing complete-sweep test**

Use an injected fake `scenario_runner` that records its calls and returns
synthetic `RunRecord` objects. With four scenario paths and `repeat_count=2`,
assert eight calls in sorted-scenario/ascending-attempt order, eight records,
zero errors, and `expected_run_count == 8`.

**Step 3: Write the failing error-isolation test**

Make the fake runner raise on one scenario/attempt. Assert later slots still
run, `SuiteRunError` contains the scenario ID and attempt number, `complete` is
false, and `matrix` is `None`.

Add a second case where the fake runner returns a record whose
`agent_failure_reason` is `api_error`. Assert the record remains available for
audit, the suite adds a non-comparable error, and no matrix is built.

**Step 4: Run the tests and verify missing APIs**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_candidate_suite
```

Expected: FAIL because the suite module does not exist.

**Step 5: Implement the suite contracts**

Add frozen `ScenarioSuiteSpec`, `SuiteRunError`, and `CandidateSuiteRun`
dataclasses with `to_dict()` methods. Add a callable protocol for the injected
single-scenario runner.

`CandidateSuiteRun.complete` must require:

```python
not self.errors and len(self.records) == self.expected_run_count and self.matrix is not None
```

**Step 6: Implement preflight and orchestration**

Before execution:
- Load the configured environment seed once for scenario validation.
- Load every sorted scenario path and derive unique scenario IDs.
- Reject empty or duplicate scenario IDs.

For each scenario and attempt, call `run_candidate_scenario()` with the existing
candidate pool, environment/output settings, and persistence option. Catch
uncaught exceptions into `SuiteRunError` and continue.

Treat these returned `agent_failure_reason` values as non-comparable errors:

```python
NON_COMPARABLE_AGENT_FAILURES = frozenset({
    "api_error",
    "response_error",
    "response_incomplete",
    "response_not_completed",
    "missing_response_id",
})
```

Keep returned records for audit, but do not build a matrix when any error exists.

**Step 7: Export the suite APIs and run tests**

Run the command from Step 4. Expected: PASS.

**Step 8: Commit**

```bash
git add src/agent_reliability_lab/runs/suite.py src/agent_reliability_lab/runs/__init__.py tests/test_candidate_suite.py
git commit -m "feat: orchestrate repeated candidate suite runs"
```

### Task 4: Complete Matrix Enforcement

**Files:**
- Modify: `src/agent_reliability_lab/optimization/scoring.py`
- Modify: `src/agent_reliability_lab/optimization/__init__.py`
- Modify: `src/agent_reliability_lab/runs/suite.py`
- Test: `tests/test_candidate_optimization.py`
- Test: `tests/test_candidate_suite.py`

**Step 1: Write failing coverage tests**

Add tests for a missing candidate/scenario cell, an unexpected scenario, and a
cell with the wrong run count. Each must raise `ValueError`. Add a passing test
for a complete two-candidate/two-scenario/two-repeat matrix.

**Step 2: Run the optimization tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_candidate_optimization
```

Expected: FAIL because strict coverage validation does not exist.

**Step 3: Implement pure coverage validation**

Add and export:

```python
def assert_complete_score_matrix(
    matrix: ScoreMatrix,
    *,
    expected_candidate_ids: Iterable[str],
    expected_scenario_ids: Iterable[str],
    expected_runs_per_cell: int,
) -> None: ...
```

Validate exact candidate/scenario sets, every cross-product cell, and the exact
run count for every cell. Reject duplicate expected IDs and non-positive run
counts.

**Step 4: Wire completed suites to scoring**

When the suite has no errors, call `build_score_matrix(records)` and then
`assert_complete_score_matrix()` with one candidate, all suite scenario IDs,
and the suite repeat count. Store the validated matrix on the result.

**Step 5: Run targeted tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_candidate_optimization tests.test_candidate_suite
```

Expected: PASS.

**Step 6: Commit**

```bash
git add src/agent_reliability_lab/optimization/scoring.py src/agent_reliability_lab/optimization/__init__.py src/agent_reliability_lab/runs/suite.py tests/test_candidate_optimization.py tests/test_candidate_suite.py
git commit -m "feat: enforce complete score matrix coverage"
```

### Task 5: Per-Scenario Candidate Comparison

**Files:**
- Create: `src/agent_reliability_lab/optimization/comparison.py`
- Modify: `src/agent_reliability_lab/optimization/__init__.py`
- Test: `tests/test_candidate_suite.py`

**Step 1: Write failing comparison tests**

Build synthetic complete parent and child suite results and cover:
- One scenario improves in pass rate.
- Equal pass rate with a higher average score counts as improvement.
- Lower pass rate sets `pass_regressed`.
- Higher safety failures sets `safety_regressed`.
- Incomplete suites, the same candidate ID, different suite/scenario IDs, and
  different repeat counts raise `ValueError`.

**Step 2: Run tests and verify missing comparison API**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_candidate_suite
```

Expected: FAIL because comparison types/functions do not exist.

**Step 3: Implement comparison dataclasses**

Add frozen `ScenarioScoreDelta` and `CandidateSuiteComparison` dataclasses with
deterministic `to_dict()` output. Include summary lists for regressed, improved,
and safety-regressed scenario IDs.

**Step 4: Implement strict matched comparison**

Implement `compare_candidate_suites(parent, child)` using matched
`ScoreMatrixCell` values. Round numeric deltas to four decimals. Report facts
only; do not add an `accepted` field or an acceptance policy.

**Step 5: Export and run tests**

Run the command from Step 2. Expected: PASS.

**Step 6: Commit**

```bash
git add src/agent_reliability_lab/optimization/comparison.py src/agent_reliability_lab/optimization/__init__.py tests/test_candidate_suite.py
git commit -m "feat: compare candidate suites per scenario"
```

### Task 6: Suite CLI and Documentation

**Files:**
- Modify: `src/agent_reliability_lab/runs/suite.py`
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`
- Test: `tests/test_candidate_suite.py`

**Step 1: Write the failing CLI argument/summary test**

Patch the suite runner in-process and call `main()` with a candidate ID,
scenario directory, repeat count, output directory, and `--no-persist`. Assert
the JSON summary includes suite/candidate identity, completeness, expected and
actual run counts, errors, and score-matrix data.

**Step 2: Implement the CLI**

Support:

```text
--candidate-id
--scenario-dir
--repeat-count
--output-dir
--no-persist
```

Load `.env` only in `main()` using the existing recorder helper behavior. Return
exit code `0` for a complete suite and `1` for an incomplete suite.

Document this command:

```bash
PYTHONPATH=src python3 -m agent_reliability_lab.runs.suite \
  --candidate-id cand_openai_degraded_v1 \
  --repeat-count 1
```

Clearly label it as a live network call only for OpenAI candidates. Automated
tests must use fakes or deterministic local candidates.

**Step 3: Update sprint tracking**

Keep Sprint 13 active until every verification item is complete, then mark its
todo items done without changing Sprint 14/15 scope.

**Step 4: Run targeted tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_candidate_suite
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/agent_reliability_lab/runs/suite.py docs/environment-v1.md tasks/todo.md tests/test_candidate_suite.py
git commit -m "docs: add candidate suite execution workflow"
```

### Task 7: Full Verification and Review

**Files:**
- Review all Sprint 13 files.
- Update: `tasks/todo.md`

**Step 1: Run all targeted tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_run_recorder
PYTHONPATH=src python3 -m unittest tests.test_openai_agent
PYTHONPATH=src python3 -m unittest tests.test_candidate_suite
PYTHONPATH=src python3 -m unittest tests.test_candidate_optimization
```

Expected: PASS.

**Step 2: Run the complete verification suite**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall -q src tests
```

Expected: PASS with no network access.

**Step 3: Run a local integration smoke test**

Use a deterministic candidate and a two-scenario subset known to execute
locally, with persistence disabled. Confirm the suite is complete and its
matrix contains exactly two cells.

**Step 4: Review side effects and invariants**

Confirm:
- The evaluator implementation and reward contract did not change.
- Every rollout still starts from a fresh environment.
- Incomplete suites cannot be compared.
- Agent/API execution failures are not presented as mutation feedback.
- Agent-visible projections contain no new internal details.
- No reflection, candidate spawning, accept/reject, or loop code leaked in.

**Step 5: Review the diff**

```bash
git diff --stat
git diff
```

**Step 6: Mark Sprint 13 complete and commit**

```bash
git add tasks/todo.md
git commit -m "chore: complete GEPA evaluation orchestrator sprint"
```
