# OpenAI Agent Policy Interface Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a minimal OpenAI Responses API agent runner whose only GEPA-mutable surface is the system instruction.

**Architecture:** The runner owns a small while-loop around model responses and fixed local support tools. Tool schemas map directly to `SupportToolService`; typed union states record the model/tool/final/failure transitions while existing evaluator inputs remain unchanged.

**Tech Stack:** Python 3.11 standard library, optional `openai` SDK for live runs, dataclasses, unittest, existing environment/scenario/evaluator/recorder modules.

---

### Task 1: State Models

**Files:**
- Create: `src/agent_reliability_lab/agents/openai_states.py`
- Test: `tests/test_openai_agent.py`

**Steps:**
1. Add frozen dataclasses for `AgentStarted`, `ModelResponded`, `ToolRequested`, `ToolExecuted`, `FinalResponseProduced`, and `AgentFailed`.
2. Add `OpenAIAgentResult` with agent name, version, final response, evidence, trace states, and failure reason.
3. Add `to_dict()` helpers for JSON-safe run/debug output.

### Task 2: Fixed Tool Schemas

**Files:**
- Create: `src/agent_reliability_lab/agents/openai_tools.py`
- Test: `tests/test_openai_agent.py`

**Steps:**
1. Define fixed strict function schemas for all ten `SupportToolService` methods.
2. Parse JSON arguments into exact Python calls.
3. Return the existing `ToolResult.to_dict()` envelope for every dispatch.
4. Reject unknown tools and malformed arguments before calling the service.

### Task 3: Responses Loop

**Files:**
- Create: `src/agent_reliability_lab/agents/openai_runner.py`
- Modify: `src/agent_reliability_lab/agents/__init__.py`
- Test: `tests/test_openai_agent.py`

**Steps:**
1. Define an injectable `ResponsesClient` protocol.
2. Add an optional real OpenAI client wrapper that imports `openai` lazily.
3. Implement `OpenAISupportAgent.run()` with max-step while-loop, `parallel_tool_calls=False`, and `temperature=0`.
4. Treat output text with no tool calls as final.
5. Treat max-step/API failures as `AgentFailed` plus empty final response.

### Task 4: Candidate Runner Integration

**Files:**
- Modify: `src/agent_reliability_lab/optimization/candidates.py`
- Modify: `src/agent_reliability_lab/runs/recorder.py`
- Test: `tests/test_openai_agent.py`
- Test: `tests/test_candidate_optimization.py`

**Steps:**
1. Add degraded candidate `cand_openai_degraded_v1`.
2. Dispatch `candidate.kind == "openai_policy"` to `OpenAISupportAgent`.
3. Preserve old deterministic candidate behavior.
4. Keep live OpenAI runs opt-in through supplied client or API-key-backed wrapper.

### Task 5: Docs and Verification

**Files:**
- Modify: `docs/environment-v1.md`
- Modify: `tasks/todo.md`

**Steps:**
1. Document the OpenAI agent boundary and live-run command.
2. Mark task checklist as complete only after tests, compile, diff review, and subagent review.
3. Confirm no hidden truth is sent to the model.
