# Suite Progress Logging V1

## Scope
- Show immediate progress for every scenario rollout in the suite CLI.
- Report completion, score/pass outcome, and rollout failures.
- Preserve final JSON output as a clean stdout contract.

## Assumptions
- Live GPT-5.5 runs can take roughly 40 seconds each.
- Progress is a CLI concern; library callers should remain silent by default.
- Scenario execution remains sequential and deterministic.

## Architectural Decisions
- Add an optional progress callback to `run_candidate_suite()`.
- Send CLI progress to stderr with `flush=True`; keep the final JSON on stdout.
- Emit start and terminal status for each rollout using stable run indexes.
- Avoid concurrency, polling threads, and model-token streaming.

## Tasks
1. Add failing tests for per-run progress and stdout/stderr separation.
2. Add the optional library progress callback.
3. Wire the CLI to flushed stderr progress.
4. Document the progress behavior.
5. Run targeted, full, compile, CLI, and diff verification.
6. Review side effects and update draft PR #2.

## Risks
- Logging to stdout would break JSON consumers.
- Callback exceptions could interrupt the suite if not kept under caller control.
- Progress messages must cover exceptions and non-comparable agent failures.

## Verification Strategy
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_candidate_suite`
- `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests`
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests`
- Confirm CLI stdout remains parseable JSON while stderr contains flushed progress.
- Run `git diff --check` and review the staged diff.

## Results
- Every rollout now emits an immediate start line and one terminal `completed`, `failed`, or `invalid` line.
- Completed lines include pass status and a four-decimal score.
- CLI progress is flushed to stderr; the final JSON remains on stdout.
- Candidate-suite verification: 14 tests passed.
- Full verification: 153 tests passed; compilation and `git diff --check` passed.
- Deterministic four-scenario CLI smoke emitted eight progress lines and completed 4/4 with valid JSON.
- Commit `5a48d53` was pushed and draft PR #2 was updated with the progress contract and outage clarification.

## Structured Review
- Minimal correct change: one optional callback, one CLI stderr adapter, and terminal messages at existing control-flow exits.
- Architectural drift: none. Execution remains sequential; no concurrency, retry, or scoring behavior changed.
- Boundaries and invariants: library callers remain silent by default and stdout remains machine-readable JSON.
- Side effects: interactive CLI users receive two stderr lines per rollout; API/library consumers are unchanged unless they opt into the callback.
- Edge cases: rollout exceptions, record mismatches, non-comparable agent failures, failed evaluations, and missing numeric scores have explicit terminal output.
- Staff-level assessment: acceptable. The observability improvement directly addresses long GPT-5.5 latency without coupling logging to the agent or evaluator.
