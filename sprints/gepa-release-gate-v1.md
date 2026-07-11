# GEPA Release Gate V1 (Sprint 15)

## Goal
Decide whether a Sprint 14 optimized candidate may replace the current released
candidate using fresh repeated regression and sealed holdout evaluations.

```text
release candidate + released baseline + suite manifest + fixed thresholds
-> equal-coverage regression comparison
-> sealed candidate-only holdout
-> PROMOTED | REJECTED | INCONCLUSIVE
-> immutable release report
```

## Scope
- Treat all existing `data/scenarios/*.json` fixtures as training-visible.
- Add one fresh lockout regression fixture and one fresh MFA holdout fixture.
- Define a versioned manifest with disjoint train, regression, and holdout paths.
- Reuse `run_candidate_suite()` for every rollout and
  `compare_candidate_suites()` for regression comparison.
- Fix repeat counts before execution; default release coverage is 10 attempts per
  regression and holdout scenario.
- Enforce a maximum total rollout budget before execution.
- Return `PROMOTED`, `REJECTED`, or `INCONCLUSIVE`.
- Reject behavioral, eligibility, pass-rate, score, or safety regressions.
- Mark incomplete/API/protocol execution as inconclusive rather than candidate
  failure.
- Run holdout only after regression passes.
- Persist one collision-safe immutable JSON release report.
- Add one JSON CLI, exports, documentation, tests, and review evidence.

## Non-Scope
- No prompt reflection or mutation from regression or holdout runs.
- No exposure of holdout evaluator feedback to Sprint 14.
- No retry engine, checkpoint resume, token accounting, or cost estimation.
- No multi-candidate search, parallel rollout scheduler, or candidate crossover.
- No deployment, production traffic, UI, or external release registry.
- No network calls in automated tests.

## Assumptions
- The current released baseline and release candidate are registered candidates.
- The release candidate differs from the baseline.
- Regression baseline/candidate coverage must match exactly.
- Holdout evaluation is candidate-only and absolute-threshold based.
- A holdout fixture is retired operationally after its release verdict; rotation
  automation belongs to later hardening.

## Architectural Decisions
- Add release contracts under `agent_reliability_lab.release`; do not extend the
  Sprint 14 optimizer driver.
- Store suite role only in `ReleaseSuiteManifest`; scenario schema remains
  evaluator-focused and unchanged.
- Validate non-empty, unique, pairwise-disjoint paths and require every path to
  exist before any rollout.
- Calculate the worst-case rollout count as
  `2 * regression slots + holdout slots` and reject over-budget configs before
  calling a suite runner.
- Evaluate gates in this order: infrastructure completeness, regression
  comparison, candidate eligibility/safety/absolute threshold, then holdout.
- Require all runs to be eligible, zero safety failures, and pass rate `1.0` for
  V1. Thresholds remain explicit dataclass fields for testability.
- Return only compact suite summaries and run IDs in release reports. The
  optimizer never receives a release report or raw holdout records.
- Persist reports using exclusive file creation; never overwrite a verdict.

## Decision Semantics
- `INCONCLUSIVE`: preflight, rollout, coverage, API, protocol, or comparison
  infrastructure failure.
- `REJECTED`: complete evidence shows regression, safety failure, ineligibility,
  or pass rate below threshold.
- `PROMOTED`: regression and holdout are complete, non-regressing, eligible,
  safety-clean, and meet all absolute thresholds.

## Step-by-Step Tasks
1. Add Sprint 15 documents and activate tracking.
2. Add fresh Northwind regression/holdout environment records and scenarios.
3. Add manifest and threshold validation.
4. Add release decision/report models and deterministic regression/holdout gates.
5. Add bounded orchestration using existing suite/comparison functions.
6. Add collision-safe report persistence and JSON CLI.
7. Add package exports and environment documentation.
8. Run targeted/full tests, compile checks, offline smoke tests, and structured
   self-review.

## Risks
- Existing training-visible scenarios could be mislabeled as holdout.
- Holdout could run before regression and waste or leak evaluation coverage.
- API failure could incorrectly reject a good candidate.
- Aggregate improvement could hide a per-scenario regression.
- Repeated reruns could allow a stochastic candidate to pass by chance.
- Release reports could overwrite previous evidence.

## Definition of Done
- Training, regression, and holdout paths are disjoint and validated.
- Fresh release fixtures load and pass scenario/environment validation.
- Worst-case rollout cost is fixed and budget-checked before execution.
- Regression failure prevents any holdout call.
- Infrastructure failure returns `INCONCLUSIVE`.
- Behavioral/safety/eligibility failure returns `REJECTED`.
- A complete non-regressing 10/10 regression and holdout result returns
  `PROMOTED`.
- Report persistence is collision-safe and includes thresholds, manifest,
  candidate IDs, run IDs, gate results, and final reason.
- All tests run offline and the existing 112 tests remain passing.

## Verification Strategy
- `PYTHONPATH=src python3 -m unittest tests.test_release_manifest`
- `PYTHONPATH=src python3 -m unittest tests.test_release_gate`
- `PYTHONPATH=src python3 -m unittest tests.test_scenarios`
- `PYTHONPATH=src python3 -m unittest tests.test_evaluator`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Run deterministic offline promoted, rejected, and inconclusive smoke paths.
- Review all Sprint 15 files for leakage, duplicated execution/scoring logic,
  unbounded work, decision misclassification, and unrelated changes.
