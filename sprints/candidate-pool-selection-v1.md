# Candidate Pool Selection V1

## Scope
- Add first-class candidate records for baseline and deterministic variants.
- Run any registered candidate against the existing support login-lockout scenario.
- Record candidate lineage metadata in run records.
- Build a candidate-by-scenario score matrix from run records.
- Compute a Pareto frontier and select one parent candidate with deterministic weighted selection.

## Assumptions
- The first candidate pool is local and deterministic.
- The existing baseline remains the passing reference candidate.
- Synthetic failing candidates are useful test fixtures until reflection mutation exists.
- The first score matrix may contain one scenario but must preserve scenario IDs.
- No model calls or external network calls are needed for Phase 9-10.

## Architectural Decisions
- Keep candidate metadata in a new `agent_reliability_lab.optimization` package.
- Keep runnable support-agent behavior under `agent_reliability_lab.agents`.
- Extend the existing run recorder instead of creating a parallel persistence format.
- Treat evaluator `score`, `passed`, and `failure_tags` as the score-matrix source of truth.
- Select parents only from safety-eligible Pareto candidates by default.

## Step-by-Step Tasks
1. Add candidate and candidate-pool dataclasses with a default local pool.
2. Add deterministic synthetic support-agent variants for meaningful candidate comparisons.
3. Add a generic `run_candidate_scenario` recorder entry point.
4. Add score-matrix aggregation from run records.
5. Add Pareto-frontier and weighted parent-selection helpers.
6. Add tests for candidate pool, runner, score matrix, selection, and candidate metadata persistence.
7. Document the Phase 9-10 boundary and commands.

## Risks
- Candidate records could duplicate agent implementation details instead of describing runnable versions.
- Score matrix logic could hide scenario identity if it only ranks global averages.
- Selection could accidentally choose unsafe candidates unless policy/safety tags are constrained.
- Synthetic variants must stay deterministic and local; they are not substitutes for mutation.

## Verification Strategy
- `python3 -m unittest tests.test_candidate_optimization`
- `python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Run a local candidate matrix from generated in-memory records.
- Review `git diff --stat` and full diff for scope drift.
- Confirm Phase 9-10 does not add reflection mutation, model calls, external network calls, or release gates.
