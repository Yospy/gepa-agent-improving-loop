# Agent Reliability Lab Context

## Goal
Build a local, realistic agent reliability environment inspired by Bespoke Labs.

The purpose is to understand their product deeply by recreating the core loop:

environment -> agent attempt -> evaluation -> failure analysis -> improvement -> release decision

## Core Thesis
Bespoke Labs' thesis is that reliable agents are not created mainly by better prompts or bigger models.

Reliable agents need realistic environments where they can practice real workflows, fail safely, get evaluated, and improve before touching production users.

## What We Are Building First
Build from scratch before using Bespoke tools.

Initial product:
Support Agent Reliability Lab

Initial agent:
Customer Support Troubleshooting Agent for a fake B2B SaaS company.

The agent investigates customer support issues using realistic company context:
- support tickets
- product docs
- policies
- logs
- account state
- fake service data
- hidden ground truth

## Build Order
1. Environment first
   - Fake SaaS company
   - Internal systems
   - Docs, logs, accounts, billing, auth, API keys

2. Scenarios second
   - Realistic customer tickets
   - Hidden truth
   - Expected behavior
   - Failure traps

3. Evaluator third
   - Define what "correct" means before building the agent
   - Score root cause, evidence use, policy compliance, escalation, safety, hallucination

4. Agent fourth
   - Agent gets only visible information and tools
   - Agent must inspect environment and produce action/response

5. Run recorder fifth
   - Capture tool calls, observations, final answer, score, failure reason

6. Improvement loop sixth
   - Analyze failed trajectories
   - Rewrite prompt/tool instructions
   - Rerun and compare versions

## First Scenario
Customer says they reset their password but still cannot log in.

Hidden truth:
- account is locked after repeated failed login attempts
- logs reveal lockout
- docs explain unlock policy

Correct behavior:
- inspect login/account evidence
- identify account lock
- avoid hallucinating a password reset issue
- explain next step
- escalate or perform unlock only if policy/tooling allows

## Design Principle
Do not build the smartest agent first.
Build the most realistic environment first.

The environment is the product.

Finalized environment approach:
- See `.context/realistic-agent-environment-approach.md`
- See `.context/build-roadmap.md`
- Build a local, stateful fake B2B SaaS support simulator before building the agent.
- The agent should interact through realistic tools, while hidden ground truth remains evaluator-only.
- Score root cause, evidence use, tool trajectory, policy compliance, safety, hallucination avoidance, and final state.

Final buildflow:
`environment -> tools -> scenarios -> evaluator -> agent -> runs -> failures -> improvements -> release threshold`

## Later Bespoke Mapping
After V1 works from scratch:
- Curator maps to scenario/data generation
- Terminal-Bench maps to packaged agent tasks and eval harness
- GEPA maps to prompt/policy optimization from failures

## Current Assumption
OPENAI_API_KEY exists in `.env`.
Do not rely on external network calls unless explicitly approved at runtime.
