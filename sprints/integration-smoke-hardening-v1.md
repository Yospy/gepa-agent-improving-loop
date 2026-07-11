# Integration Smoke Hardening V1

## Scope
- Make the deterministic baseline complete and pass every training scenario.
- Make the documented release-gate module CLI executable.
- Add regression coverage at the real integration boundaries.

## Assumptions
- Internal ticket tags are trusted support-desk metadata.
- The baseline may branch only on records returned by agent-facing tools.
- Automated verification must remain offline.

## Architectural Decisions
- Keep one deterministic baseline and derive the workflow from observed auth
  events, ticket metadata, MFA state, sessions, reset events, and active policy.
- Treat an MFA-stage auth failure as distinct from lockout.
- Use the trusted `verified-requester` ticket tag to select policy-safe unlock;
  the write tool remains the final enforcement boundary.
- Keep the standard Python module guard after every function definition.
- Exercise the actual candidate suite and a subprocess `python -m` invocation
  through validated preflight so mocks cannot hide module-order failures.

## Step-by-Step Tasks
1. Add failing all-scenario baseline integration coverage.
2. Generalize baseline diagnosis, evidence, action, and response behavior.
3. Add a real release-module subprocess regression test.
4. Move the release module guard to the end of the file.
5. Run targeted tests, full tests, compilation, and offline CLI smoke tests.
6. Review the diff, side effects, boundaries, and sprint alignment.

## Risks
- Scenario branching could accidentally use hidden truth.
- MFA evidence could omit a required record identifier.
- Verified unlock behavior could regress unverified safety.
- A subprocess test could depend on the caller's environment.

## Verification Strategy
- `PYTHONPATH=src python3 -m unittest tests.test_baseline_agent -v`
- `PYTHONPATH=src python3 -m unittest tests.test_release_gate -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m compileall -q src tests`
- Run the baseline over `data/scenarios` with `--no-persist`.
- Run the release gate module through deterministic over-budget preflight with
  `--no-persist`; behavioral verdict paths remain covered with injected runners.

## Results
- 46 targeted integration/evaluator/release tests passed.
- 128 full tests passed.
- Source and test compilation passed.
- The real baseline suite completed 4/4 scenarios at score `1.0`, pass rate
  `1.0`, zero safety failures, and no rollout errors.
- Release-threshold repetition completed 40/40 deterministic rollouts with
  average score `1.0`, pass rate `1.0`, and zero safety failures.
- The real release module reached validated rollout-budget preflight and no
  longer fails from helper-definition ordering.
- Review found no hidden-truth access, unsafe direct state mutation, new network
  use, or unrelated source changes.
