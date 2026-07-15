# Fireworks OSS Model Integration V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run support agents on MiniMax M3 and GEPA reflection on GLM-5.2 through Fireworks while preserving the repository's deterministic, offline-testable orchestration.

**Architecture:** Introduce one Fireworks Chat Completions adapter behind the existing injected response-client protocol. The adapter converts the repository's Responses-style requests, tool schemas, and continuation tokens into complete Chat Completions message histories, then normalizes Fireworks output back into the shape already consumed by the support agent and reflection client. Agent and teacher models receive separate defaults and environment overrides.

**Tech Stack:** Python 3.11, OpenAI Python SDK configured for Fireworks compatibility, Fireworks Chat Completions API, `unittest`, `python-dotenv`.

---

### Task 1: Lock the Fireworks transport contract with failing tests

**Files:**
- Modify: `tests/test_openai_agent.py`
- Modify: `tests/test_gepa_reflection.py`
- Modify: `tests/test_gepa_driver.py`

**Steps:**
1. Replace the shared GPT-5.5 default assertion with separate MiniMax M3 agent and GLM-5.2 teacher assertions.
2. Add a fake `chat.completions.create` SDK surface and assert the adapter sends system/user messages to the configured model.
3. Assert Responses-style flat tools become Chat Completions `function` tools with strict JSON schemas preserved.
4. Assert assistant tool calls and subsequent tool outputs are retained in the next stateless Fireworks request.
5. Assert text and tool calls normalize into the current internal response contract.
6. Assert the GEPA CLI defaults to the teacher model while support runs use the agent model.
7. Run the focused tests and expect failures because the Fireworks adapter/defaults do not yet exist.

### Task 2: Implement the Fireworks Chat Completions adapter

**Files:**
- Modify: `src/agent_reliability_lab/agents/openai_runner.py`
- Test: `tests/test_openai_agent.py`

**Steps:**
1. Add Fireworks base URL, agent model, and teacher model constants.
2. Replace the live Responses wrapper with `FireworksChatCompletionsClient`, lazily constructing `OpenAI(api_key=FIREWORKS_API_KEY, base_url=FIREWORKS_BASE_URL)`.
3. Validate the injected SDK exposes `chat.completions`.
4. Convert initial instructions/input into system and user messages.
5. Convert flat function schemas into Chat Completions function schemas.
6. Normalize one completion choice into `id`, `status`, `output_text`, and Responses-style `output` items.
7. Cache normalized assistant history by completion ID and reconstruct tool messages for the next call.
8. Fail clearly for invalid choices, missing IDs, unknown continuation IDs, and incomplete finish reasons.
9. Run `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_openai_agent` and expect all adapter tests to pass.

### Task 3: Wire distinct agent and teacher roles

**Files:**
- Modify: `src/agent_reliability_lab/agents/__init__.py`
- Modify: `src/agent_reliability_lab/runs/recorder.py`
- Modify: `src/agent_reliability_lab/optimization/reflection.py`
- Modify: `src/agent_reliability_lab/optimization/gepa.py`
- Test: `tests/test_openai_agent.py`
- Test: `tests/test_gepa_reflection.py`
- Test: `tests/test_gepa_driver.py`

**Steps:**
1. Export the Fireworks client and distinct model constants.
2. Resolve support runs from `FIREWORKS_AGENT_MODEL`, falling back to MiniMax M3.
3. Default the reflection client and GEPA CLI to `FIREWORKS_TEACHER_MODEL`, falling back to GLM-5.2.
4. Keep `--model` as a compatible alias for the clearer `--teacher-model` option.
5. Update `.env` loading documentation strings to reference Fireworks settings.
6. Run the focused agent/reflection/driver tests and expect them to pass.

### Task 4: Document live Fireworks usage

**Files:**
- Modify: `README.md`
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Replace active OpenAI credential/provider wording with Fireworks configuration.
2. Document `FIREWORKS_API_KEY`, `FIREWORKS_AGENT_MODEL`, and `FIREWORKS_TEACHER_MODEL` without including secrets.
3. Explain that historical `openai_policy` identifiers remain stable while the live provider is Fireworks.
4. Add exact suite and GEPA commands.
5. Mark sprint tasks complete only after verification and structured review.

### Task 5: Verify and review

**Files:**
- Review: all files listed above

**Steps:**
1. Run `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_openai_agent tests.test_gepa_reflection tests.test_gepa_driver` and expect success.
2. Run `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests` and expect success.
3. Run `PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests` and expect success.
4. Review the diff against baseline and confirm unrelated dirty-worktree changes remain intact.
5. Analyze API errors, stateless continuation behavior, key handling, model-role separation, evaluator boundaries, and stored-record compatibility.
6. Record results in the sprint and `tasks/todo.md`.
7. Do not make an official-doc request or live inference request without the runtime approvals required by `AGENTS.md`.

### Task 6: Complete the confirmed Fireworks generation payload

**Files:**
- Modify: `src/agent_reliability_lab/agents/openai_runner.py`
- Modify: `src/agent_reliability_lab/optimization/reflection.py`
- Modify: `tests/test_openai_agent.py`
- Modify: `tests/test_gepa_reflection.py`
- Modify: `README.md`

**Steps:**
1. Add a failing adapter assertion for MiniMax M3 `max_tokens=64000`, `top_k=40`, `presence_penalty=0`, and `frequency_penalty=0`.
2. Add a failing reflection assertion for the GLM-5.2 `max_tokens=131072` role limit.
3. Extend the internal response-client boundary with explicit generation settings.
4. Send SDK-supported fields directly and send `top_k` through `extra_body` so it becomes a top-level Fireworks request field.
5. Document both role-specific output limits.
6. Repeat focused tests, full tests, compilation, CLI simulation, diff review, and secret review.

### Task 7: Harden live GEPA structured output and progress

**Files:**
- Modify: `src/agent_reliability_lab/agents/openai_runner.py`
- Modify: `src/agent_reliability_lab/optimization/reflection.py`
- Modify: `src/agent_reliability_lab/optimization/gepa.py`
- Modify: `tests/test_openai_agent.py`
- Modify: `tests/test_gepa_reflection.py`
- Modify: `tests/test_gepa_driver.py`
- Modify: `tasks/todo.md`
- Modify: `sprints/fireworks-oss-model-integration-v1.md`

**Steps:**
1. Add failing adapter/reflection tests proving the teacher requests `response_format={"type":"json_object"}` while ordinary agent calls omit it.
2. Add failing parser tests that accept one bare, fenced, or prose-wrapped proposal and reject malformed, repaired, array-wrapped, or multiple JSON objects.
3. Add failing diagnostics assertions for decode location, response length/hash, and fence flags without embedding raw teacher text.
4. Add failing GEPA progress tests for parent suite rollouts, generation/teacher attempt boundaries, retry status, child suite rollouts, and CLI stderr/stdout separation.
5. Extend the internal Fireworks boundary with optional response format forwarding.
6. Implement one-object extraction while preserving exact keys, string types, non-empty values, instruction length, identifier, and unchanged-instruction validation.
7. Thread an optional quiet-by-default progress callback through GEPA and enable flushed stderr progress only in the CLI.
8. Run `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_openai_agent tests.test_gepa_reflection tests.test_gepa_driver` and expect success.
9. Run the full offline suite, `compileall`, CLI simulation, diff review, side-effect review, and secret scan.
10. Run one explicitly authorized live GEPA generation with one child and inspect its history. Success requires a parsed mutation and an evaluated child trial; acceptance is not required.
