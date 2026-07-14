# OpenAI Agent Baseline Tuning V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce a live OpenAI support policy that passes all four scenarios, then slightly reduce non-safety guidance to leave controlled GEPA optimization headroom.

**Architecture:** Strengthen the mutable system instruction and sequence the existing tool schemas through ticket binding, requester evidence, active-policy lookup, and policy-allowed action phases. Use the existing live scenario suite as the single end-to-end behavioral test, preserving requester binding and write safety throughout tuning.

**Tech Stack:** Python 3, OpenAI Responses API runner, JSON scenario suite, deterministic evaluator.

---

### Task 1: Establish the behavioral contract

**Files:**
- Reference: `.runs/run_20260713T111039Z_support-login-lockout-v1-openai-degraded-policy-v1_0feb313315b54cbf8bd20828408710ee.json`
- Reference: `.runs/run_20260713T111055Z_support-mfa-blocker-v1-openai-degraded-policy-v1_7347e9a952fa483bbb8ecf1d0128a4d9.json`
- Reference: `.runs/run_20260713T111109Z_support-verified-unlock-v1-openai-degraded-policy-v1_44e874e00221404787b1afca78a7e221.json`
- Reference: `.runs/run_20260713T111119Z_support-wrong-user-lockout-v1-openai-degraded-policy-v1_00d30168073440a5919d094cce21cc62.json`

**Step 1:** Confirm the reproduced baseline is 0/4 and classify missing evidence, unsafe actions, wrong-user targeting, and response failures.

**Step 2:** Compare the model policy with the complete workflow in `src/agent_reliability_lab/agents/baseline.py`.

### Task 2: Implement the strong policy

**Files:**
- Modify: `src/agent_reliability_lab/agents/openai_runner.py`

**Step 1:** Replace the speed-first instruction with an ordered investigation contract.

**Step 2:** Require ticket requester binding, complete reads, active policy selection, prerequisite checks, evidence-backed action, and a complete final response.

**Step 3:** Restrict each model turn to the existing tools valid for the current investigation phase and bind user/ticket arguments to observed ticket fields.

**Step 4:** Run the exact live suite command from the sprint.

**Expected:** Four scenario runs, 4/4 passed, and zero safety failures.

### Task 3: Apply a controlled nerf

**Files:**
- Modify: `src/agent_reliability_lab/agents/openai_runner.py`

**Step 1:** Remove one non-safety instruction detail while retaining requester binding, active-policy lookup, and write prerequisites.

**Step 2:** Rerun the exact live suite command.

**Expected:** All four scenarios execute; record the resulting pass and safety profile without running GEPA.

### Task 4: Review

**Files:**
- Review: `src/agent_reliability_lab/agents/openai_runner.py`
- Update: `sprints/openai-agent-baseline-tuning-v1.md`
- Update: `tasks/todo.md`

**Step 1:** Review the final diff for minimality and unrelated changes.

**Step 2:** Check safety, requester isolation, step-budget pressure, and scenario-general wording.

**Step 3:** Document strong and nerfed suite outcomes.
