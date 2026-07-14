# GPT-5.5 Model Upgrade V1

## Scope
- Change the default OpenAI model from `gpt-4.1-mini` to `gpt-5.5`.
- Apply the default to both the evaluated support agent and GEPA reflection teacher.
- Update the live-run documentation and existing draft PR.

## Assumptions
- The explicit requested target is `gpt-5.5`, even though OpenAI currently documents GPT-5.6 as newer.
- Existing `OPENAI_MODEL` and GEPA `--model` overrides remain supported.
- No live API run is required; the user will run the supplied command.

## Architectural Decisions
- Change the shared default constant so both model roles stay aligned.
- Preserve the current Responses API request shape because official API documentation supports GPT-5.5 with Responses and tool calling.
- Keep historical agent versions and metric claims unchanged; the new model must produce fresh run records before new performance claims.

## Tasks
1. Add a regression test for the GPT-5.5 default.
2. Update the shared model constant and live-run documentation.
3. Run targeted, full, compile, CLI, and diff verification.
4. Review model provenance, overrides, side effects, and sprint alignment.
5. Commit, push, and update the existing draft pull request.

## Risks
- GPT-5.5 may have different latency, cost, or instruction-following behavior.
- Existing 4.1-mini metrics cannot be attributed to GPT-5.5.
- Account access to the model is verified only by the user's live run.

## Verification Strategy
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_openai_agent tests.test_gepa_reflection tests.test_gepa_driver`
- `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests`
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests`
- Confirm CLI help and the documented command use `gpt-5.5`.
- Run `git diff --check` and review the staged diff.

## Results
- The shared default now resolves to `gpt-5.5` for both the support agent and GEPA reflection client.
- The `OPENAI_MODEL` environment override and GEPA `--model` option remain intact.
- The focused regression test failed against `gpt-4.1-mini` and passed after the change.
- Targeted verification: 45 tests passed.
- Full verification: 150 tests passed; compilation, both CLI help commands, and `git diff --check` passed.
- No live API request was made; fresh GPT-5.5 metrics must come from the user's live suite.
- Commit `ae418be` was pushed and draft PR #1 was updated with the model change and fresh-run caveat.

## Structured Review
- Minimal correct change: one shared default constant, one regression assertion, and one active documentation example changed.
- Architectural drift: none. Both model roles continue to share the existing default and preserve explicit overrides.
- Boundaries and invariants: tool schemas, deterministic evaluation, safety gates, and candidate promotion rules are unchanged.
- Side effects: expected GPT-5.5 latency and cost differences are runtime concerns to measure in the fresh suite.
- Edge cases: explicit model overrides still bypass the default; historical GPT-4.1-mini results and sprint records remain unchanged.
- Staff-level assessment: acceptable. Model provenance is visible in the recorded agent trace, and no new performance claim is made without fresh runs.
