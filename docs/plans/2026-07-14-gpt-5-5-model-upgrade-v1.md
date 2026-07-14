# GPT-5.5 Model Upgrade V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make GPT-5.5 the reproducible default for the support agent and GEPA teacher while preserving explicit model overrides.

**Architecture:** Both model roles import one shared default from the OpenAI runner. Change that constant, lock it with a focused test, and update only the active live-run documentation; leave historical results and old sprint records unchanged.

**Tech Stack:** Python 3.11, OpenAI Responses API, unittest, Markdown, GitHub CLI.

---

### Task 1: Lock the requested default

**Files:**
- Modify: `tests/test_openai_agent.py`

1. Import `DEFAULT_OPENAI_MODEL`.
2. Add a test asserting that the default is `gpt-5.5`.
3. Run the test and confirm it fails against `gpt-4.1-mini`.

### Task 2: Upgrade the shared model

**Files:**
- Modify: `src/agent_reliability_lab/agents/openai_runner.py`
- Modify: `docs/environment-v1.md`

1. Set `DEFAULT_OPENAI_MODEL` to `gpt-5.5`.
2. Update the active recorder example to use `gpt-5.5`.
3. Preserve `OPENAI_MODEL` and GEPA `--model` overrides.
4. Leave historical metric and sprint records unchanged.

### Task 3: Verify and publish

**Files:**
- Modify: `sprints/gpt-5-5-model-upgrade-v1.md`
- Modify: `tasks/todo.md`

1. Run targeted and full tests.
2. Run compilation, CLI help, and diff checks.
3. Review provenance, compatibility, side effects, and edge cases.
4. Commit and push the GPT-5.5 branch.
5. Open a follow-up draft PR to `main` with the GPT-5.5 change and validation.
