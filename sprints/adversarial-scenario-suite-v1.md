# Adversarial Scenario Suite V1

## Scope

- Add four training-visible scenario variants that preserve existing hidden truth while making the customer framing actively misleading.
- Cover false verification pressure, wrong-user redirection, false lockout framing for MFA, and unnecessary-escalation pressure after verified identity.
- Keep release regression and holdout fixtures unchanged.

## Assumptions

- Harder cases should test whether the policy follows tool evidence over customer instructions, not introduce new tools or evaluator semantics.
- Reusing existing environment records is intentional: each new case isolates instruction-following difficulty from new state-model complexity.
- The four original live-run measurements remain historical and must not be rewritten as eight-scenario results.

## Architectural Decisions

- Represent each harder case as a first-class scenario fixture with a unique scenario ID.
- Reuse the matching original ticket, user, required evidence, expected action, and final state so evaluator invariants stay identical.
- Put adversarial pressure only in agent-visible issue framing and record the corresponding trap in evaluator-only hidden truth.
- Keep all variants in `data/scenarios/` so normal training-suite discovery includes them automatically.

## Step-by-Step Tasks

1. Add failing fixture-inventory and adversarial-boundary tests.
2. Add four strict-schema scenario fixtures derived from the existing lockout, wrong-user, MFA, and verified-unlock cases.
3. Update suite-size assertions that intentionally cover the complete discovered training directory.
4. Document the original and adversarial scenario groups without changing historical metrics.
5. Run focused scenario, baseline, evaluator, and suite tests; then run the full suite and compile checks.
6. Review the diff, hidden-truth boundary, release isolation, edge cases, and sprint alignment; document results.

## Risks

- Visible wording could accidentally leak evaluator-only truth.
- Duplicate ticket bindings could be mistaken for duplicate scenario identities.
- Fixed-count orchestration tests could silently retain four-scenario assumptions.
- Historical live metrics could be misrepresented as results for the expanded suite.

## Verification Strategy

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_scenarios`
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_baseline_agent tests.test_evaluator tests.test_candidate_suite`
- `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests`
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests`
- `git diff --check` and focused diff review.

## Results

- Red phase: 7 expected failures from missing fixtures and expanded suite counts.
- Focused scenario, baseline, evaluator, and suite verification: 60 tests passed.
- Full verification: 158 tests passed; source and tests compile cleanly; every new JSON fixture parses; `git diff --check` is clean.
- The deterministic baseline passes all eight training scenarios without agent, evaluator, tool, environment, or release-gate changes.
- Canonical comparisons confirm each adversarial fixture preserves its source case's root cause, evidence, policy behavior, expected final state, and forbidden actions.

## Structured Review

- Minimal correct change: four scenario fixtures, inventory/orchestration assertions, and documentation; no runtime implementation changed.
- Architectural drift: none. Existing directory discovery, strict schema validation, deterministic evaluation, and release boundaries are reused.
- Boundaries and invariants: all visible projections pass hidden-truth leak validation; scenario IDs are unique while trusted ticket/user bindings intentionally repeat.
- Side effects: the default training suite and its live rollout cost double from four to eight scenarios. Historical README metrics remain explicitly scoped to the original four.
- Release isolation: Northwind regression and holdout fixtures, release thresholds, and rollout budgets are unchanged.
- Edge cases: false approval, explicit wrong-user redirection, false lockout remedy for MFA, and unnecessary escalation after verified identity are covered with neutral guidance that does not reveal the expected action.
- Staff-level assessment: acceptable. The cases increase instruction-conflict difficulty while holding state and evaluator semantics constant.
