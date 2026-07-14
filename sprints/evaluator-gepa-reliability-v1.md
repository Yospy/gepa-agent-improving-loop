# Evaluator + GEPA Reliability V1

## Scope

- Correct evaluator wording and exact-identifier semantics without weakening deterministic safety checks.
- Separate completed-action confirmation from safe-next-step quality while preserving total response-check weight.
- Align GEPA reflection with runtime-enforced agent invariants and the remaining mutable response behavior.
- Add bounded multi-child exploration per GEPA generation.
- Reject all safety, fatal-eligibility, and pass regressions while tolerating only tiny nonfatal score noise.
- Verify targeted modules, full tests, compilation, and one controlled live GEPA run when local credentials are available.

## Assumptions

- Existing uncommitted evaluator, GEPA, reflection, agent, test, plan, and documentation changes are intentional and must be preserved.
- The OpenAI runner mechanically enforces ticket binding, requester reads, active-policy lookup, and allowed writes.
- `poor_final_response` remains nonfatal; safety and fatal checks remain deterministic.
- User explicitly requested subagent implementation and authorized the controlled workflow.

## Architectural Decisions

- Keep regex-based deterministic evaluation, but normalize known natural paraphrases and use exact boundaries for trap identifiers.
- Replace the single conflated response-quality check with two half-weight checks so the total evaluator score weight remains unchanged.
- Keep mutation-validation retries distinct from valid-child exploration.
- Record every valid child trial within its logical generation and select the best acceptable child deterministically.
- Default multi-child breadth to one for backward compatibility; expose an explicit CLI/config bound for broader search.
- Preserve hard per-scenario safety, fatal eligibility, and pass-rate regression rejection; allow at most 0.05 nonfatal score regression.

## Step-by-Step Tasks

1. Add failing evaluator tests for exact wrong-user matching, lock/reset paraphrases, action confirmation, and safe-next-step separation.
2. Implement the minimal evaluator predicates and precise feedback.
3. Add reflection tests that exclude runtime-enforced workflow rewrites and emphasize mutable response/evidence behavior.
4. Update reflection instructions and serialization-compatible feedback.
5. Add GEPA comparison/driver tests for fatal regression, 0.05 score tolerance, multiple valid children, first-child rejection recovery, serialization, and CLI bounds.
6. Implement comparison fields, conservative acceptance, child-trial history, and bounded valid-child search.
7. Run targeted tests for evaluator, comparison/suite, GEPA reflection, and GEPA driver.
8. Run the full test suite and compile verification.
9. Run one live GEPA generation with two repeats and two valid children, then inspect parent/child safety and response metrics.
10. Review diff, side effects, edge cases, backward compatibility, and sprint intent.

## Risks

- Splitting checks can unintentionally change score normalization unless weights sum to the original weight.
- Identifier matching can become too permissive or too strict around punctuation and near-prefix IDs.
- Multi-child search increases live API cost and persisted run volume.
- Selecting a child from noisy rollouts can overfit unless safety/fatal/pass constraints remain hard.
- Parallel agents share the worktree; file ownership must remain non-overlapping.

## Verification Strategy

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_evaluator`
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_candidate_suite`
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_gepa_reflection`
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_gepa_driver`
- `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests`
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests`
- Live: `PYTHONPATH=src ./.venv/bin/python -m agent_reliability_lab.optimization.gepa --candidate-id cand_openai_degraded_v1 --scenario-dir data/scenarios --repeat-count 2 --max-generations 1 --children-per-generation 2 --max-mutation-attempts 2`
- Review `git diff --check`, focused diffs, failure tags, safety counts, and serialized history.

## Integration Checkpoints

### Evaluator + Reflection

- Evaluator now separates completed-action confirmation from safe-next-step content at weights 0.5 + 0.5.
- Natural lockout/reset variants and exact wrong-user boundaries are covered.
- Reflection preserves runtime-enforced calls while retaining event-window and response quality as mutable behavior.
- Integrated focused result: 41 tests passed before final edge-case additions.

### GEPA Driver

- Candidate-suite and GEPA-driver targeted result: 30 tests passed.
- Added fatal eligibility deltas, 0.05 score tolerance, bounded serial child trials, deterministic selection, and audited history.
- Full-suite discovery exposed one reference-agent response without a post-unlock next step; the sprint was updated and the baseline response now asks the customer to sign in again.

## Results

- Integrated targeted verification: 71 tests passed.
- Full verification: 149 tests passed; source and tests compile cleanly; `git diff --check` is clean.
- Live optimization `gepa_25c4e0e542ef42bb93876c46d57617e6` completed one generation with two repetitions and two child trials.
- Both children improved `support_login_lockout_v1`, but both were correctly rejected for pass regressions elsewhere. No safety or fatal regression occurred, and the parent `cand_openai_degraded_v1` remained selected.
- Child 1 moved login-lockout from 0% / 0.95 to 100% / 1.00, but reduced verified-unlock and wrong-user-lockout from 100% to 50% pass rate.
- Child 2 moved login-lockout from 0% / 0.95 to 50% / 0.975, but reduced MFA blocker to 50% and verified-unlock to 0% pass rate.
- Persisted audited history: `.gepa-runs/gepa_25c4e0e542ef42bb93876c46d57617e6.json`.

## Structured Review

- Minimal correct change: evaluator weight was redistributed rather than increased; child breadth defaults to one; the release gate remains strict.
- Architectural drift: none observed. Deterministic runtime safety remains separate from mutable response policy and optimizer search.
- Boundaries and invariants: exact requester matching, safety failures, fatal eligibility, and per-scenario pass rate remain hard gates.
- Side effects: broader search increases serial API cost and persisted run volume only when explicitly configured above one child.
- Edge cases: near-prefix identifiers, negated lock wording, natural reset phrasing, action-without-next-step, next-step-without-action, invalid mutation retries, rejected-first-child continuation, tie-breaking, and history compatibility are covered by tests.
- Staff-level assessment: acceptable. The live run demonstrated the intended behavior by preserving the stronger parent instead of promoting a locally improved but unstable child.
