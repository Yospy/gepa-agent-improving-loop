# Support Agent Reliability Environment V1

## Scope
Create the design foundation for a realistic local environment where a customer support troubleshooting agent can work against fake B2B SaaS systems before any production-like agent is built.

## Assumptions
- The first product is a support reliability lab, not a general agent platform.
- The first scenario is: customer reset their password but still cannot log in.
- The environment must be local and reproducible.
- External network calls are not part of V1 runtime unless explicitly approved.
- The agent must only see visible tools and records; hidden truth is evaluator-only.

## Architectural Decisions
- Build the environment before the agent.
- Model the environment as a small fake SaaS company with stateful internal systems.
- Use seeded structured data for accounts, users, auth logs, support tickets, password resets, and policy docs while keeping hidden truth evaluator-only.
- Expose internal systems through tool APIs rather than giving the agent direct file/database access.
- Evaluate final state and reasoning evidence, not only answer text.
- Record every run as a trajectory: prompt version, scenario, tool calls, observations, final answer, score, and failure tags.

## Tasks
1. Research patterns from realistic agent benchmarks and eval systems.
2. Finalize the local environment design approach in `.context/`.
3. Follow `.context/build-roadmap.md` as the buildflow.
4. Define V1 data entities and visibility boundaries.
5. Define first scenario schema and hidden ground truth schema.
6. Define tool API surface for the agent.
7. Define evaluator rubric and pass/fail checks.
8. Define run record format.

## Phase 1 Environment Implementation

### Scope
- Create the local Python package for the reliability lab.
- Define typed environment records for the fake B2B SaaS company.
- Seed a resettable support/auth environment for the first login-lockout scenario.
- Validate referential integrity and scenario-critical business invariants.
- Keep hidden ground truth out of agent-visible environment records.
- Add tests that prove the seed is coherent and resettable.

### Non-Scope
- No baseline agent.
- No LLM/model calls.
- No external network calls.
- No production UI.
- No evaluator scoring beyond environment integrity checks.

### Step-by-Step Tasks
1. Add package structure under `src/agent_reliability_lab/`.
2. Add environment dataclasses/enums for organizations, accounts, users, tickets, auth events, reset events, identity verification, lockouts, MFA, sessions, docs, policies, and audit entries.
3. Add a deterministic fixture loader for `data/environment/support_env_v1.json`.
4. Add an in-memory environment store with reset, snapshot, deterministic hash, and mutation-safe copies.
5. Add validation checks for identifiers, cross-record references, active lockout evidence, password reset success evidence, explicit identity-verification state, deprecated-doc trap, and wrong-user trap.
6. Add tests under `tests/` for load, validation, reset, state hash stability, no hidden-truth leakage, and first-scenario evidence quality.
7. Document the environment boundary and run commands.

### Verification Checklist
- `python3 -m unittest discover -s tests`
- Review `git diff --stat`.
- Review full diff for architectural drift.
- Confirm Phase 1 did not add agent logic or network dependency.
- Confirm first scenario cannot be considered solved by ticket text alone.

## Phase 2 Tool API Implementation

### Scope
- Expose the environment through realistic support tools only.
- Add deterministic tool-call logging for every successful and failed call.
- Implement read tools for tickets, accounts, users, docs, auth logs, reset events, sessions, and MFA.
- Implement write tools for account unlock and escalation.
- Enforce policy preconditions in write tools, especially identity verification before unlock.
- Keep all tool outputs agent-visible and hidden-truth-free.

### Non-Scope
- No baseline agent.
- No LLM/model calls.
- No evaluator scoring beyond tool behavior tests.
- No UI or HTTP server.
- No external network calls.

### Step-by-Step Tasks
1. Add tool result and log record models.
2. Add `SupportToolService` over `EnvironmentStore`.
3. Implement `get_ticket`, `get_account`, `get_user`, `search_docs`, `get_auth_logs`, `get_password_reset_events`, `get_sessions`, and `get_mfa_status`.
4. Implement `unlock_user` with policy denial when identity verification is not verified.
5. Implement `escalate_case` with ticket status mutation, support note, and audit entry.
6. Add tests for read-tool filtering, call logging, denied unlock, successful unlock after verified identity, escalation mutation, and visible-output boundaries.
7. Document tool API behavior and verification commands.

### Verification Checklist
- `python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Confirm every tool call creates a log record.
- Confirm write tools create audit records.
- Confirm denied unlock does not unlock or clear lockout.
- Confirm no tool output contains hidden-truth keys or forbidden evaluator text.

## Phase 3 Scenario Implementation

### Scope
- Define strict scenario records outside the agent-visible environment fixture.
- Add the first login-lockout scenario with visible prompt, allowed tools, hidden truth, required evidence, policy behavior, expected final state, forbidden actions, and failure traps.
- Validate scenario bindings against the seeded environment.
- Preserve the visibility boundary: agent-visible scenario projection must not include hidden truth.

### Non-Scope
- No evaluator scoring.
- No baseline agent.
- No model calls.
- No run recorder.

### Step-by-Step Tasks
1. Add scenario dataclasses under `src/agent_reliability_lab/scenarios/`.
2. Add `data/scenarios/login_lockout_v1.json`.
3. Add scenario loader and validation.
4. Add tests for loading, strict schema handling, evidence references, hidden-truth separation, and invalid scenario regressions.
5. Document the scenario boundary and verification commands.

### Verification Checklist
- `python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Confirm hidden truth is absent from `Scenario.to_agent_visible_dict()`.
- Confirm required evidence points to real environment records.
- Confirm Phase 3 did not add evaluator, agent, model, or network logic.

## Phase 4 Evaluator Implementation

### Scope
- Add deterministic evaluator models and checks for one completed agent attempt.
- Evaluate tool trajectory, observed evidence, forbidden actions, final state, and final response text against scenario hidden truth.
- Return structured score, pass/fail, checks, failure tags, and notes.
- Keep evaluator local and dependency-free.

### Non-Scope
- No baseline agent.
- No LLM judge.
- No model calls.
- No run recorder persistence.
- No prompt optimization.

### Step-by-Step Tasks
1. Add evaluator package under `src/agent_reliability_lab/evaluation/`.
2. Define `AgentAttempt`, `EvaluationCheck`, and `EvaluationResult`.
3. Implement deterministic checks for required tools, required evidence, root cause, hallucinated reset failure, forbidden actions, policy-safe escalation, expected final state, wrong-user trap, stale-policy trap, and customer-safe final response.
4. Add tests for passing attempt and representative failure modes.
5. Document evaluator behavior and verification commands.

### Verification Checklist
- `python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Confirm evaluator consumes hidden truth but never exposes it through agent-visible scenario projection.
- Confirm evaluator does not add agent, model, network, or persistence logic.
- Run subagent code review and address actionable findings.

## Phase 5-6 Baseline Agent and Run Recorder Implementation

### Scope
- Add an offline deterministic baseline support agent for the first login-lockout scenario.
- Keep the baseline agent limited to scenario-visible input and the support tool API.
- Add a local run recorder that captures complete attempt trajectories.
- Evaluate each recorded run with the deterministic evaluator.
- Persist run records as JSON for later failure analysis.

### Non-Scope
- No LLM/model calls.
- No external network calls.
- No prompt optimization loop.
- No UI or HTTP server.
- No repeated release-threshold suite.

### Step-by-Step Tasks
1. Add baseline agent models and implementation under `src/agent_reliability_lab/agents/`.
2. Add a deterministic run orchestration entry point that loads environment and scenario state, runs the baseline agent, evaluates the attempt, and returns a run record.
3. Add run record models and JSON persistence under `src/agent_reliability_lab/runs/`.
4. Add tests proving the baseline agent passes the evaluator, records all tool calls, stores state hashes, and writes hidden-truth-safe agent-visible projections.
5. Document the baseline run command and run record boundary.

### Verification Checklist
- `python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Execute one local baseline run and inspect the persisted JSON.
- Review `git diff --stat`.
- Review full diff for architectural drift.
- Confirm Phase 5-6 did not add model calls, external network calls, prompt optimization, or UI.

## Phase 7-8 Failure Analysis and Improvement Reports

### Scope
- Load historical run records from `.runs/` or another local run-record directory.
- Analyze failed runs using evaluator `failure_tags`.
- Produce deterministic failure summaries for missing evidence, wrong root cause, policy violation, wrong user, stale policy, and poor final response.
- Emit improvement report rows with agent version, scenario ID, pass/fail, score, failure tags, and suggested improvement targets.
- Compare two run sets or two agent versions by pass rate, score, and failure-tag counts.
- Add a CLI entry point for local analysis:
  `PYTHONPATH=src python3 -m agent_reliability_lab.analysis.failures .runs`

### Non-Scope
- Do not add Phase 9 release gating.
- No LLM/model calls.
- No prompt optimization engine.
- No external network calls.
- No UI or dashboard.

### Assumptions
- Existing run records already contain the internal evaluator payload.
- Missing or malformed run records should fail loudly rather than being silently ignored.
- Stale-policy evaluator tags may appear as `stale_policy_used`; analysis should summarize them under the stale policy bucket.
- The current deterministic baseline run remains the passing reference record.

### Architectural Decisions
- Add a separate `agent_reliability_lab.analysis` package above runs/evaluation.
- Keep analysis pure and file-based: JSON in, dataclass reports out, JSON CLI output.
- Treat evaluator `failure_tags` as the source of truth for failure grouping.
- Keep improvement targets deterministic text mappings, not generated recommendations.

### Step-by-Step Tasks
1. Add a failure-analysis module that loads local run JSON records and normalizes evaluator fields.
2. Add canonical failure buckets and suggested improvement target mappings.
3. Add improvement report rows for every loaded run.
4. Add comparison helpers for two run sets and two agent versions.
5. Add a CLI wrapper that prints deterministic JSON.
6. Add tests using synthetic failed records and a generated current baseline passing record.
7. Document the analysis command and output boundary.

### Risks
- Analysis could drift into a fake optimizer if it generates prompt changes instead of deterministic targets.
- Comparing unrelated scenario sets can mislead unless reports retain scenario IDs and agent versions.
- Hidden evaluator details should stay in local analysis output and not be exposed as agent-visible records.

### Verification Checklist
- `python3 -m unittest tests.test_failure_analysis`
- `python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Execute `PYTHONPATH=src python3 -m agent_reliability_lab.analysis.failures .runs`.
- Review `git diff --stat`.
- Review full diff for architectural drift.
- Confirm Phase 7-8 did not add Phase 9 gates, model calls, external network calls, prompt optimization, or UI.

## Risks
- Toy data will make the agent look reliable without proving the thesis.
- Overbuilding the agent before the environment will hide environment gaps.
- LLM-judge-only scoring can miss policy/state violations.
- If tools expose too much state directly, the task becomes unrealistic.
- If hidden truth leaks into visible context, eval results become invalid.

## Verification Strategy
- Review approach against known benchmark patterns: stateful envs, realistic tools, hidden expected state, executable scoring, run traces.
- Confirm the first scenario can only be solved by inspecting evidence.
- Confirm hidden truth is separated from agent-visible inputs.
- Confirm every proposed tool maps to a realistic support workflow.
- Confirm V1 can run fully offline except model calls.
