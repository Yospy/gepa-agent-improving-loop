# Scenario Suite V1

## Scope
- Add multiple support-task scenarios bound to the shared local environment seed.
- Extend the seed only with realistic visible records needed by those scenarios.
- Generalize scenario validation so non-primary tickets/users can be valid.
- Generalize deterministic evaluation enough to score scenario-specific evidence, root cause, expected write action, and final state.
- Add a scenario-suite loader for future GEPA matrix runs.

## Assumptions
- The support tool schema remains fixed.
- No model calls are needed for this sprint.
- Scenarios share one environment fixture and are reset independently per run.
- Existing login-lockout behavior must remain backward compatible.
- New scenarios should create different failure pressure: wrong user, verified unlock, and MFA investigation.

## Architectural Decisions
- Keep scenario truth in JSON fixtures under `data/scenarios/`.
- Keep environment records visible and hidden truth separate.
- Make evaluator behavior scenario-contract-driven where practical instead of adding one evaluator per scenario.
- Keep the first evaluator generalization small: evidence records, expected write action, final state, root-cause keywords, and response safety.

## Step-by-Step Tasks
1. Add sprint and implementation plan docs.
2. Extend the environment fixture with new tickets, auth/reset/verification/session/MFA records.
3. Add scenario fixtures for wrong-user trap, verified unlock allowed, and MFA blocker.
4. Add `load_scenario_suite()` for all local scenarios.
5. Relax scenario validation away from environment primary-ticket-only assumptions.
6. Generalize evaluator checks for scenario-specific required tools, expected final state, write action, and root-cause text.
7. Add tests proving all scenarios bind to existing environment records and representative good attempts pass.
8. Run full verification and self-review.

## Risks
- A generic evaluator can become vague and miss scenario-specific safety failures.
- Adding seed data can weaken the first scenario if records become ambiguous.
- Prompt-visible text can accidentally disclose hidden truth.
- Baseline agent is not expected to solve every new scenario yet.

## Verification Strategy
- `PYTHONPATH=src python3 -m unittest tests.test_scenarios`
- `PYTHONPATH=src python3 -m unittest tests.test_evaluator`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Confirm every new scenario loads with `load_scenario_suite()`.
- Confirm no hidden-truth markers appear in visible projections.
