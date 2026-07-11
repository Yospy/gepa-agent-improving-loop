# GEPA Evaluation Orchestrator V1 (Sprint 13)

## Goal
Turn the existing one-candidate/one-scenario run path into a trustworthy
candidate-suite execution and comparison layer for the later GEPA driver.

```text
candidate + scenario suite + repeat count
-> agent rollouts
-> existing deterministic evaluator
-> complete score matrix
-> per-scenario comparison report
```

## Scope
- Run one registered candidate across an explicit scenario suite.
- Reset the environment independently for every rollout by reusing
  `run_candidate_scenario()`.
- Support a configurable positive repeat count per scenario.
- Collect existing `RunRecord` evaluation output; do not add another evaluator.
- Detect rollout exceptions and non-comparable model/API failures without
  treating them as prompt-quality feedback.
- Require complete and equal candidate-by-scenario coverage before comparison.
- Compare two complete candidate suites per scenario by pass rate, average
  score, and safety-failure count.
- Print one JSON suite summary from a CLI entry point.
- Make repeated persisted runs collision-safe.

## Non-Scope
- No reflection LLM or prompt mutation.
- No child-candidate creation or candidate-pool extension.
- No GEPA accept/reject policy or generation loop.
- No parent-selection changes.
- No new evaluator checks, failure tags, or feedback formatting.
- No train/regression/holdout policy; later sprints compose separate explicit
  suite specifications using this runner.
- No network calls in automated tests.

## Assumptions
- `run_candidate_scenario()` remains the single-rollout source of truth and
  already creates a fresh `EnvironmentStore` and invokes the evaluator.
- All scenarios use the shared environment seed but each rollout starts from a
  fresh copy.
- Scenario files are validated before the first rollout begins.
- Repeat counts are equal within a suite so parent/child cells are comparable.
- The existing score, pass/fail, fatal tags, safety tags, `feedback_text`, and
  `trace_excerpt` remain unchanged.

## Public Contract

```python
@dataclass(frozen=True)
class ScenarioSuiteSpec:
    name: str
    scenario_paths: tuple[Path, ...]
    repeat_count: int = 1


@dataclass(frozen=True)
class SuiteRunError:
    scenario_id: str
    attempt_number: int
    error_type: str
    message: str


@dataclass(frozen=True)
class CandidateSuiteRun:
    suite_name: str
    candidate_id: str
    scenario_ids: tuple[str, ...]
    repeat_count: int
    expected_run_count: int
    records: tuple[RunRecord, ...]
    errors: tuple[SuiteRunError, ...]
    matrix: ScoreMatrix | None

    @property
    def complete(self) -> bool: ...


def run_candidate_suite(
    candidate_id: str,
    suite: ScenarioSuiteSpec,
    *,
    candidate_pool: CandidatePool = DEFAULT_CANDIDATE_POOL,
    environment_path: Path | str = DEFAULT_ENVIRONMENT_PATH,
    output_dir: Path | str = DEFAULT_RUN_OUTPUT_DIR,
    persist: bool = True,
    scenario_runner: CandidateScenarioRunner = run_candidate_scenario,
) -> CandidateSuiteRun: ...


def compare_candidate_suites(
    parent: CandidateSuiteRun,
    child: CandidateSuiteRun,
) -> CandidateSuiteComparison: ...
```

`scenario_runner` is injectable only to keep orchestration tests offline and
deterministic. Production execution uses `run_candidate_scenario()`.

## Architectural Decisions
- Keep suite orchestration under `agent_reliability_lab.runs`; it owns execution,
  not scoring policy.
- Keep score-matrix coverage validation under
  `agent_reliability_lab.optimization.scoring` so the later GEPA driver cannot
  accidentally rank sparse matrices.
- Keep parent/child comparison under `agent_reliability_lab.optimization`; it is
  pure and consumes completed suite results.
- Iterate scenarios in sorted path order and attempts from `1..repeat_count` for
  reproducible presentation.
- Validate a non-empty suite, unique scenario IDs, and `repeat_count >= 1`
  before running any candidate.
- Continue collecting other rollout slots after an exception, but mark the
  suite incomplete and prohibit comparison.
- Persist `agent_failure_reason` in internal run records. Transport/protocol
  failures (`api_error`, `response_error`, `response_incomplete`,
  `response_not_completed`, and `missing_response_id`) make a suite
  non-comparable. Behavioral failures such as `max_steps_exceeded` and
  `empty_model_response` remain evaluator-scored candidate outcomes.
- Build a score matrix only when every expected rollout slot produced a
  comparable record.
- The comparator reports facts only. Sprint 15 will decide whether those facts
  mean accept or reject.
- Add a UUID suffix to human-readable run IDs and use exclusive file creation
  so repeated trials can never silently overwrite a run.

## Comparison Semantics
For every matched scenario, report:
- Parent and child run count.
- Parent and child pass rate plus delta.
- Parent and child average score plus delta.
- Parent and child safety-failure count plus delta.
- `pass_regressed`: child pass rate is lower.
- `safety_regressed`: child safety-failure count is higher.
- `improved`: pass rate is higher, or pass rate is equal and average score is
  higher.

Comparison must fail loudly when either suite is incomplete, candidate IDs are
the same, suite names/scenario IDs differ, or repeat counts differ.

## Step-by-Step Tasks
1. Make run IDs unique and recorder writes collision-safe.
2. Persist internal agent failure reasons without changing agent-visible output.
3. Add suite specification, error, result models, and the suite runner.
4. Add strict score-matrix coverage validation.
5. Add pure per-scenario parent/child comparison models and logic.
6. Add the suite CLI, exports, documentation, and usage examples.
7. Run targeted tests, the complete test suite, compile checks, and structured
   self-review.

## Risks
- A rollout exception could silently remove a matrix cell and make a candidate
  appear stronger than it is.
- An API outage could be misread as prompt failure and later poison mutation
  feedback.
- Repeated runs could overwrite each other if run IDs are not genuinely unique.
- Parent and child could be compared using different scenario sets or repeat
  counts.
- Sprint 13 could drift into acceptance policy or mutation logic owned by later
  sprints.

## Definition of Done
- A suite with four scenarios and `repeat_count=2` attempts exactly eight
  independent rollouts.
- Every successful rollout contains the existing evaluator score, tags,
  `feedback_text`, and `trace_excerpt` unchanged.
- Two runs started with the same fixed clock produce distinct run IDs and files.
- Missing, duplicate, or unequal score-matrix cells fail coverage validation.
- An uncaught rollout exception is recorded with scenario and attempt identity,
  other slots still run, and the result is not comparable.
- Non-comparable API/protocol failures cannot reach suite comparison.
- Complete parent and child suites produce deterministic per-scenario deltas and
  regression flags.
- Existing 73 tests remain passing and new Sprint 13 tests pass offline.

## Verification Strategy
- `PYTHONPATH=src python3 -m unittest tests.test_run_recorder`
- `PYTHONPATH=src python3 -m unittest tests.test_openai_agent`
- `PYTHONPATH=src python3 -m unittest tests.test_candidate_suite`
- `PYTHONPATH=src python3 -m unittest tests.test_candidate_optimization`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Run the baseline candidate over a two-scenario subset with persistence disabled.
- Run the suite CLI with an injected/fake runner in tests; do not call the network.
- Review the complete diff for evaluator changes, mutation leakage, hidden-truth
  exposure, sparse-matrix acceptance, and unrelated scope.
