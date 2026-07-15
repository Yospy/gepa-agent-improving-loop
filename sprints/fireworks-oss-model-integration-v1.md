# Fireworks OSS Model Integration V1

## Scope

- Replace the live OpenAI Responses API transport with Fireworks' OpenAI-compatible Chat Completions transport.
- Use `accounts/fireworks/models/minimax-m3` for evaluated support-agent runs.
- Use `accounts/fireworks/models/glm-5p2` for GEPA reflection/teacher calls.
- Send the user-confirmed Fireworks generation contract: MiniMax M3 `max_tokens=64000`, GLM-5.2 `max_tokens=131072`, `top_k=40`, and zero presence/frequency penalties.
- Preserve the existing agent loop, deterministic tool dispatcher, evaluator, candidate records, and injected offline-test boundary.
- Document the Fireworks environment variables and live commands.
- Make the GEPA teacher contract robust to OSS structured-output formatting and expose live phase progress without leaking prompts or secrets.

## Assumptions

- `.env` provides `FIREWORKS_API_KEY`; its value must never be logged or persisted.
- The user-provided GLM identifier is authoritative pending read-only verification against Fireworks documentation.
- `minimaxm3` maps to the Fireworks identifier `accounts/fireworks/models/minimax-m3`, pending the same verification.
- Fireworks exposes both models through `https://api.fireworks.ai/inference/v1/chat/completions` with OpenAI-compatible tool calls.
- Historical `openai_policy` candidate kinds, IDs, class names, and recorded metrics remain stable because renaming them would be a data migration unrelated to the transport change.
- Automated tests remain offline and use injected fake clients.

## Architectural Decisions

- Keep the repository's small `ResponsesClient` protocol as the internal boundary so the agent and GEPA orchestration do not depend directly on provider response objects.
- Add a Fireworks adapter that uses the installed OpenAI SDK with a Fireworks `base_url` and `FIREWORKS_API_KEY`; do not add a second HTTP stack.
- Translate flat Responses-style tool schemas to Chat Completions function tools at the adapter boundary.
- Maintain per-response chat history inside the adapter so the existing `previous_response_id` tool loop remains unchanged while Fireworks receives complete stateless message history.
- Normalize Fireworks chat completions into the response shape already consumed by the runner and reflection client.
- Split agent and teacher model defaults and environment overrides instead of sharing one model setting.
- Carry role-specific output limits through the internal client boundary; pass standard penalties directly and Fireworks-only `top_k` through the SDK's `extra_body`, which merges it into the top-level HTTP payload.

## Step-by-Step Tasks

1. Add failing offline tests for Fireworks endpoint configuration, message/tool translation, continuation history, normalized outputs, and distinct model defaults.
2. Implement the minimal Fireworks Chat Completions adapter and response normalization.
3. Wire `FIREWORKS_AGENT_MODEL` into support-agent construction and `FIREWORKS_TEACHER_MODEL` into the GEPA CLI/reflection client.
4. Remove OpenAI-key/default assumptions from active docs while retaining historical names and results.
5. Run focused tests, then the full offline test suite and compilation.
6. Review the complete diff, provider side effects, error paths, model provenance, and sprint alignment.
7. Only after explicit runtime approval, verify official Fireworks documentation/model metadata; only after separate approval, run a bounded live smoke test.
8. Add the user-confirmed MiniMax/GLM generation parameters to the adapter contract and repeat offline verification.

## Risks

- Fireworks model IDs or tool-call support may differ from the user shorthand.
- Chat Completions is stateless, so incomplete history translation would break multi-step tool execution.
- Provider finish reasons or response content can differ from OpenAI Responses objects.
- Some OSS models may emit malformed tool arguments; the existing dispatcher must remain the enforcement point.
- A live test can consume credits and mutate local run artifacts, so it is excluded until explicitly approved.
- Fireworks/GLM may reject provider-level JSON mode; local parsing must remain strict and the bounded live check is authoritative.
- Logging raw teacher text can expose optimizer inputs, so progress logs must remain content-free and parse diagnostics bounded/non-content-bearing.

## Verification Strategy

- Focused: `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_openai_agent tests.test_gepa_reflection tests.test_gepa_driver`
- Full: `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests`
- Syntax/import: `PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests`
- Diff: inspect only planned files and confirm existing hard-evidence changes are preserved.
- Edge cases: missing key, missing/duplicate response IDs, empty choices, non-completed finish reasons, malformed tool calls, and unknown continuation IDs.
- No network calls are part of automated verification.

## Results (2026-07-15)

- Added a Fireworks Chat Completions adapter using the installed OpenAI-compatible SDK client at `https://api.fireworks.ai/inference/v1`.
- The adapter translates fixed tool schemas, reconstructs stateless chat history across tool outputs, and normalizes Fireworks text/tool responses into the existing injected protocol.
- Agent default: `accounts/fireworks/models/minimax-m3`; override: `FIREWORKS_AGENT_MODEL`.
- GEPA teacher default: `accounts/fireworks/models/glm-5p2`; override: `FIREWORKS_TEACHER_MODEL`; CLI: `--teacher-model` with `--model` retained as an alias.
- Focused result: 50 tests passed.
- Full result: 170 tests passed.
- `compileall`, CLI-help simulation, and `git diff --check` passed.
- Secret review found no credential value added to tracked files; `.env` was read only to confirm key presence.
- Diff review confirmed the pre-existing hard-evidence runner/tool changes remain intact; no evaluator, scenario, environment, release, or persistence schema was changed by this sprint.
- Side effects are bounded to live provider construction, chat-history translation, model-role configuration, tests, and active documentation. Historical `openai_policy` identifiers remain compatible.
- Edge review: missing keys, invalid completion structure, malformed tool calls, unknown continuations, duplicate response IDs, and non-completed finish reasons fail closed through explicit errors or the existing agent failure path.
- Structured self-review: this is the minimal transport-boundary change; it reuses the existing SDK and injected protocol, does not introduce evaluator drift, and keeps tool dispatch as the safety authority.
- Official Fireworks model/tool metadata verification remains pending explicit outbound-network approval. No live inference was attempted.
- Follow-up contract evidence: the user confirmed MiniMax M3 uses `accounts/fireworks/models/minimax-m3`, `max_tokens=64000`, `top_k=40`, and zero presence/frequency penalties. The initial adapter omitted these fields because the old internal protocol exposed only `temperature`; this is the identified root cause of the incomplete payload.
- Follow-up implementation: the internal boundary now carries explicit generation settings; MiniMax uses `64000`, GLM-5.2 uses `131072` from the earlier confirmed teacher payload, and both send `top_k=40` plus zero penalties. The focused 50-test suite passes with exact payload assertions.
- Follow-up verification: the full 170-test suite, `compileall`, GEPA CLI-help simulation, secret scan, and `git diff --check` all pass after the generation-payload correction.
- First live GEPA result: parent rollout completed, but two GLM-5.2 mutation attempts returned non-empty text that failed strict whole-string JSON decoding. The run stopped as `mutation_failed` before creating a child; raw teacher text was discarded and GEPA emitted no phase progress.
- Subagent assessment: request broadly compatible `response_format={"type":"json_object"}`, retain exact local proposal validation, accept only one unambiguous bare/fenced/prose-wrapped JSON object, reject malformed or multiple objects, add non-content parse diagnostics, and forward the existing suite progress callback through GEPA with explicit teacher-attempt events.
- Structured-output fix: GLM reflection now requests JSON-object mode, retains exact-key and instruction validation, accepts one unambiguous wrapped JSON object, reports non-content diagnostics, and uses a linear-time extraction path that fails safely on excessive nesting.
- Observability fix: library use remains quiet by default; the CLI streams parent, mutation, child, decision, and terminal `stop_reason` events to stderr while reserving stdout for the result JSON.
- Independent review: three subagents reviewed provider structured output, parser safety, and GEPA observability. Their response-format, terminal-event, quiet-library, and parser-complexity findings are covered by regression tests.
- Final offline verification: 175 tests passed; `compileall`, CLI-help simulation, `git diff --check`, side-effect review, and credential-safety review passed.
- Authorized live one-generation verification: `gepa_50aa1581561049f1ba743fc7e9ed2822` completed with 8/8 parent runs, one successful GLM mutation on attempt 1, a created child, and 8/8 child runs. The child improved two scenarios but introduced a fatal regression on `support_hard_expired_verification_v2`, so GEPA correctly retained the parent and stopped as `child_rejected`/`fatal_regression`.
- Live history: `.gepa-runs/gepa_50aa1581561049f1ba743fc7e9ed2822.json`.
