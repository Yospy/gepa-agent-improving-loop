# GEPA Optimization Loop V1 (Sprint 14)

## Goal
Build the first complete, bounded GEPA-style prompt optimization loop on top of
the existing candidate, reward, suite-runner, and comparison contracts.

```text
evaluate parent
-> build deterministic reflection examples
-> reflect and mutate system instruction
-> create traceable child candidate
-> evaluate child on equal coverage
-> accept or reject deterministically
-> repeat within a generation limit
```

## Scope
- Build optimizer-only reflection examples from complete comparable run records.
- Send the parent instruction and deterministic evaluator feedback through an
  injectable reflection client.
- Parse and validate one complete replacement `system_instruction`.
- Create a uniquely identified child candidate with correct parent/generation
  lineage and mutation provenance.
- Extend immutable candidate pools without mutating existing registries.
- Evaluate parent and child candidates through the Sprint 13 suite runner.
- Apply a conservative deterministic accept/reject policy.
- Repeat accepted improvements up to an explicit positive generation limit.
- Record every generation, decision, stop reason, and source run ID.
- Add a JSON CLI and optional collision-safe optimization-history persistence.

## Non-Scope
- No train/regression/holdout split or release certification.
- No parallel children, crossover, prompt merging, or multi-parent evolution.
- No retry policy after a rejected mutation or child.
- No resumable checkpoints, UI, dashboards, or distributed execution.
- No cost optimizer or dynamic token budgeting.
- No mutation of tools, scenarios, evaluator rules, model configuration,
  temperature, or agent step limits.
- No external network calls in automated tests.

## Assumptions
- Only candidates with `kind="openai_policy"` and a non-empty string
  `payload["system_instruction"]` are mutable.
- `CandidateSuiteRun.complete` remains the comparability gate.
- Evaluator-only `feedback_text` and `trace_excerpt` may be used by the optimizer
  but never enter the task agent's visible scenario.
- A complete child suite can still be behaviorally poor; infrastructure
  completeness and acceptance are separate decisions.
- Accepted child suite results are reused as the next parent results rather than
  rerunning the same candidate immediately.

## Architectural Decisions
- Add reflection/mutation primitives under
  `agent_reliability_lab.optimization.reflection`; they create candidates but do
  not execute scenarios.
- Add acceptance and generation orchestration under
  `agent_reliability_lab.optimization.gepa`; it composes existing suite and
  comparison functions without duplicating evaluator or scoring logic.
- Reuse the existing `ResponsesClient` abstraction for the live reflection call
  with no tools, while tests inject a narrower fake `ReflectionClient`.
- Require the reflection response to be a JSON object with exactly
  `analysis` and `system_instruction` string fields.
- Use deterministic, one-example-per-scenario feedback selection. Select the
  lowest-scoring record per scenario, breaking ties by run ID, so repeats do not
  inflate the reflection prompt.
- Reject prompts that are unchanged, empty, oversized, or contain known
  scenario/run identifiers from the source suite.
- Extend `CandidatePool` through `with_candidate()` and retain its existing
  duplicate and lineage validation.
- Accept a child only when no scenario regresses in pass rate, average score, or
  safety failures and at least one scenario improves.
- Treat incomplete suites, reflection failures, and invalid mutations as stop
  conditions, not candidate-quality evidence.
- Persist one optimizer-history JSON with exclusive file creation; individual
  rollout persistence remains owned by the existing run recorder.

## Public Contract

```python
@dataclass(frozen=True)
class ReflectionExample:
    run_id: str
    scenario_id: str
    passed: bool
    score: float
    failure_tags: tuple[str, ...]
    feedback_text: str
    trace_excerpt: tuple[str, ...]
    final_response: str


@dataclass(frozen=True)
class MutationProposal:
    analysis: str
    system_instruction: str


def build_reflection_examples(
    suite_run: CandidateSuiteRun,
) -> tuple[ReflectionExample, ...]: ...


def create_child_candidate(
    parent: Candidate,
    proposal: MutationProposal,
    *,
    source_run_ids: tuple[str, ...],
    mutation_id: str,
) -> Candidate: ...


@dataclass(frozen=True)
class AcceptanceDecision:
    accepted: bool
    reason: str


def decide_candidate_acceptance(
    comparison: CandidateSuiteComparison,
) -> AcceptanceDecision: ...


def run_gepa_optimization(
    config: GEPAConfig,
    *,
    reflection_client: ReflectionClient,
    candidate_pool: CandidatePool = DEFAULT_CANDIDATE_POOL,
    suite_runner: CandidateSuiteRunner = run_candidate_suite,
) -> GEPAOptimizationResult: ...
```

## Acceptance Semantics
- Reject when any scenario has a higher child safety-failure count.
- Reject when any scenario has a lower child pass rate.
- Reject when any scenario has a lower child average score.
- Reject when every scenario is unchanged.
- Accept only a complete comparable child with at least one improved scenario
  and no regression above.

## Step-by-Step Tasks
1. Add Sprint 14 tracking and an executable implementation plan.
2. Add immutable candidate-pool extension and reflection data models.
3. Add deterministic reflection-example construction and prompt formatting.
4. Add fake-friendly reflection client, strict response parsing, mutation
   validation, and child-candidate creation.
5. Add acceptance policy models and unit tests.
6. Add bounded generation driver, stop reasons, history models, and tests.
7. Add collision-safe history persistence and JSON CLI.
8. Update package exports and environment documentation.
9. Run targeted tests, the complete suite, compile checks, a deterministic
   offline smoke run, and structured diff review.

## Risks
- Evaluator-only details could leak into the task agent prompt.
- Reflection could memorize scenario/run identifiers rather than generalize.
- API failures could be misclassified as prompt-quality failures.
- A child could improve aggregate score while silently regressing one scenario.
- Candidate-pool mutation could corrupt parent lineage across generations.
- An unbounded loop could create uncontrolled rollout or API cost.

## Definition of Done
- A complete parent suite produces deterministic one-per-scenario reflection
  examples without task-agent visibility changes.
- A valid fake reflection response creates a unique generation-correct child.
- Empty, unchanged, malformed, oversized, or identifier-memorizing mutations
  stop before child evaluation.
- A child with any pass, score, or safety regression is rejected.
- A non-regressing child with at least one improvement is accepted and becomes
  the next parent.
- The driver stops deterministically on perfect result, rejection, reflection
  failure, incomplete suite, or generation limit.
- Generation history includes candidates, source run IDs, comparison, decision,
  and stop reason and can be serialized/persisted collision-safely.
- All live OpenAI behavior is behind injected interfaces in tests.
- Existing 91 tests remain passing and new Sprint 14 tests pass offline.

## Verification Strategy
- `PYTHONPATH=src python3 -m unittest tests.test_gepa_reflection`
- `PYTHONPATH=src python3 -m unittest tests.test_gepa_driver`
- `PYTHONPATH=src python3 -m unittest tests.test_candidate_optimization`
- `PYTHONPATH=src python3 -m unittest tests.test_candidate_suite`
- `PYTHONPATH=src python3 -m unittest tests.test_openai_agent`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Run an offline end-to-end optimization smoke test with fake reflection and
  suite runners.
- Review the complete diff for hidden-truth exposure, mutation-surface drift,
  comparison bypasses, unbounded work, persistence collisions, and unrelated
  changes.
