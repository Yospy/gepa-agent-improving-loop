# GPT-5.5 Model Upgrade V1

## Scope
- Change the default OpenAI model from `gpt-4.1-mini` to `gpt-5.5`.
- Apply the default to both the evaluated support agent and GEPA reflection teacher.
- Omit `temperature` at the shared SDK boundary for GPT-5.5 models.
- Update the live-run documentation and publish a follow-up draft PR.

## Assumptions
- The explicit requested target is `gpt-5.5`, even though OpenAI currently documents GPT-5.6 as newer.
- Existing `OPENAI_MODEL` and GEPA `--model` overrides remain supported.
- No live API run is required; the user will run the supplied command.

## Architectural Decisions
- Change the shared default constant so both model roles stay aligned.
- Keep callers' internal temperature contract stable, but filter unsupported parameters in the shared OpenAI SDK adapter.
- Preserve temperature for model families that accept it and omit it for `gpt-5.5` aliases.
- Keep historical agent versions and metric claims unchanged; the new model must produce fresh run records before new performance claims.

## Tasks
1. Add a regression test for the GPT-5.5 default.
2. Update the shared model constant and live-run documentation.
3. Run targeted, full, compile, CLI, and diff verification.
4. Review model provenance, overrides, side effects, and sprint alignment.
5. Commit, push, and open a follow-up draft pull request.
6. Reproduce the GPT-5.5 API failure from persisted records and add a failing transport-boundary test.
7. Implement model-aware omission of `temperature` in the shared Responses adapter.
8. Rerun targeted/full verification and update the follow-up PR.

## Risks
- GPT-5.5 may have different latency, cost, or instruction-following behavior.
- Existing 4.1-mini metrics cannot be attributed to GPT-5.5.
- Account access to the model is verified only by the user's live run.
- Removing temperature globally would weaken deterministic behavior for older models, so omission must remain model-specific.

## Verification Strategy
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_openai_agent tests.test_gepa_reflection tests.test_gepa_driver`
- `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests`
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests`
- Confirm CLI help and the documented command use `gpt-5.5`.
- Run `git diff --check` and review the staged diff.
- Simulate the SDK request and assert GPT-5.5 omits `temperature` while GPT-4.1-mini retains it.

## Results
- The shared default now resolves to `gpt-5.5` for both the support agent and GEPA reflection client.
- The `OPENAI_MODEL` environment override and GEPA `--model` option remain intact.
- The focused regression test failed against `gpt-4.1-mini` and passed after the change.
- The first live GPT-5.5 suite produced 16/16 non-comparable API failures because the model rejected `temperature`.
- A transport-boundary test reproduced the unsupported parameter, then passed after model-aware filtering.
- GPT-5.5 aliases now omit `temperature`; GPT-4.1-mini still receives the configured `0.0` value.
- Targeted verification: 46 tests passed.
- Full verification: 151 tests passed; compilation, both CLI help commands, and `git diff --check` passed.
- No live API request was made; fresh GPT-5.5 metrics must come from the user's live suite.
- PR #1 merged before the model commits were pushed; follow-up draft PR #2 contains the clean GPT-5.5-only diff and fresh-run caveat.

## Structured Review
- Minimal correct change: the shared SDK adapter filters one unsupported parameter for the affected model family; callers and protocols remain unchanged.
- Architectural drift: none. Both model roles continue to share the existing default and preserve explicit overrides.
- Boundaries and invariants: tool schemas, deterministic evaluation, safety gates, and candidate promotion rules are unchanged.
- Side effects: expected GPT-5.5 latency and cost differences are runtime concerns to measure in the fresh suite.
- Edge cases: GPT-5.5 aliases omit temperature, older models retain it, explicit overrides still work, and historical results remain unchanged.
- Staff-level assessment: acceptable. Model provenance is visible in the recorded agent trace, and no new performance claim is made without fresh runs.
