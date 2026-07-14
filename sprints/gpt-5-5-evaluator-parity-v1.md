# GPT-5.5 Evaluator Parity V1

## Scope

- Correct deterministic evaluator false-negatives demonstrated by the complete GPT-5.5 16-run suite.
- Cover smart-apostrophe completed actions, first-person lockout clearing, gerund sign-in guidance, and coordinated MFA lockout negation.
- Preserve every tool, state, identity, safety, and fatal eligibility gate.

## Assumptions

- The persisted GPT-5.5 trajectories are operationally valid inputs for regression wording tests.
- This sprint changes evaluator interpretation only; it does not modify the agent prompt or run GEPA.
- Regex matching remains appropriate because the evaluator must be deterministic and reproducible.

## Architectural Decisions

- Normalize typographic apostrophes once at response-check boundaries instead of duplicating punctuation variants across action patterns.
- Add narrow grammatical variants to existing action and next-step pattern groups.
- Extend lockout negation only for the observed `not ... or an account lockout` construction.
- Test exact GPT-5.5 phrases alongside negative controls that must remain rejected.

## Step-by-Step Tasks

1. Add failing regression tests for each demonstrated false-negative.
2. Run focused evaluator tests and confirm the expected failures.
3. Implement the smallest matcher and normalization corrections.
4. Run focused tests, then the full test suite and compile checks.
5. Re-evaluate the stored 16 GPT-5.5 trajectories offline to quantify the corrected baseline.
6. Review the diff, safety boundaries, edge cases, and sprint alignment; document results.

## Risks

- Broad negation matching could hide a genuine lockout claim in an MFA scenario.
- Broad action matching could treat a proposed action as completed.
- Re-scoring persisted records must not mutate the original audit files.

## Verification Strategy

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_evaluator`
- `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests`
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests`
- Offline replay and re-evaluation of the 16 stored GPT-5.5 run IDs without persistence.
- `git diff --check` and focused diff review.

## Results

- Focused evaluator verification: 31 tests passed.
- Full verification: 157 tests passed; source and tests compile cleanly; `git diff --check` is clean.
- Read-only replay of the original complete GPT-5.5 suite now scores every scenario at 4/4 and 1.0000 average.
- Corrected aggregate: 16/16 passed, 1.0000 average score, zero fatal failures, and zero safety failures.
- The original audit records remain immutable; corrected metrics were computed from fresh in-memory replay.

## Structured Review

- Minimal correct change: one response normalizer and four evidence-backed pattern variants; no scoring weights, tool checks, state checks, or release thresholds changed.
- Architectural drift: none. Evaluation remains deterministic and regex-based.
- Boundaries and invariants: completed actions still require past/completed wording; future and attempted actions remain rejected. MFA lockout negation is limited to the demonstrated coordinated phrase.
- Side effects: typographic apostrophes are treated as ASCII equivalents across response checks; this changes punctuation interpretation only.
- Edge cases: smart apostrophes, first-person lockout clearing, gerund sign-in guidance, emphatic reset success, coordinated MFA negation, future escalation, and attempted unlock are covered.
- Staff-level assessment: acceptable. The corrected signal reflects the stored trajectories while deterministic safety gates remain unchanged.
