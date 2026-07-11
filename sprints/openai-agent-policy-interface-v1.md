# OpenAI Agent Policy Interface V1

## Scope
- Add a model-backed support agent runner using the OpenAI Responses API shape.
- Keep support tool schemas fixed and mapped 1:1 to `SupportToolService`.
- Make only `system_instruction` mutable through candidate payloads.
- Add typed union states for replayable agent traces.
- Keep unit tests local and deterministic with an injectable fake client.
- Add one intentionally degraded OpenAI candidate for GEPA measurement.

## Assumptions
- `OPENAI_API_KEY` is required only for optional live runs.
- Unit tests must not call the network or require the OpenAI package at runtime.
- The evaluator remains unchanged and continues to consume existing tool-call records.
- A failed/max-step model run still produces an evaluator attempt with an empty final response.
- Final answer means a model response with output text and no tool-call item.

## Architectural Decisions
- Own the while-loop instead of using the Agents SDK so GEPA can inspect every transition.
- Define fixed strict tool schemas manually near the tool dispatcher.
- Use a small client protocol so fake tests and real OpenAI calls share one runner.
- Map candidate `payload["system_instruction"]` to the Responses API `instructions` parameter.
- Keep scenario/ticket data in user input, separate from mutable instructions.

## Step-by-Step Tasks
1. Add OpenAI agent union-state models and final-result model.
2. Add fixed OpenAI tool schemas plus argument parsing and dispatch.
3. Add injectable Responses client protocol, fake-friendly runner, and optional real client wrapper.
4. Wire OpenAI candidates into `run_candidate_scenario`.
5. Add degraded candidate `cand_openai_degraded_v1`.
6. Add tests for schemas, tool loop, final answer detection, max-step failure, API failure, and run recording.
7. Document commands, live-run boundary, and GEPA mutation surface.
8. Run verification and subagent review.

## Risks
- Live model nondeterminism can make repeated-run thresholds noisy.
- Tool-call item formats can drift if OpenAI SDK output objects differ from fake objects.
- A careless prompt assembly could leak hidden scenario truth.
- Overbuilding the runner could obscure the simple GEPA mutation contract.

## Verification Strategy
- `PYTHONPATH=src python3 -m unittest tests.test_openai_agent`
- `PYTHONPATH=src python3 -m unittest tests.test_candidate_optimization`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Subagent review focused on tool schema correctness, hidden-truth boundaries, failure handling, and unnecessary complexity.
