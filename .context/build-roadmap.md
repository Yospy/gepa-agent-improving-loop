# Build Roadmap

## Final Buildflow
1. Build fake SaaS environment.
2. Expose realistic support tools.
3. Create scenarios with hidden truth and traps.
4. Build evaluator.
5. Add baseline agent.
6. Record every run.
7. Analyze failures.
8. Improve prompt/tool policy.
9. Stop improving when release thresholds are met.

## Phase 1: Environment
Build a local fake B2B SaaS company.

Core systems:
- Support Desk
- Account Admin
- Auth Console
- Knowledge Base
- Audit Log

Core data:
- Organizations
- Accounts
- Users
- Roles
- Tickets
- Login events
- Password reset events
- Lockout state
- MFA state
- Sessions
- Support policies
- Product docs

Output:
- Seeded local environment state.
- Resettable scenario state.
- No agent yet.

## Phase 2: Tools
Expose internal systems only through realistic tools.

Initial tools:
- `get_ticket`
- `get_account`
- `get_user`
- `search_docs`
- `get_auth_logs`
- `get_password_reset_events`
- `get_sessions`
- `get_mfa_status`
- `unlock_user`
- `escalate_case`

Output:
- Agent-facing tool API.
- Tool call logging.
- State mutations for write tools.

## Phase 3: Scenarios
Create support tasks the agent must solve.

Each scenario includes:
- Visible customer issue
- Initial environment state
- Allowed tools
- Hidden ground truth
- Required evidence
- Expected behavior
- Forbidden actions
- Failure traps

First scenario:
- Customer says they reset their password but still cannot log in.
- Hidden truth: password reset succeeded, but account is locked after failed login attempts.

Output:
- Scenario schema.
- First login-lockout scenario.

## Phase 4: Evaluator
Define correctness before building the agent.

Evaluator checks:
- Root cause correctness
- Required evidence use
- Tool trajectory
- Policy compliance
- Safety
- Hallucination avoidance
- Final response quality
- Final state correctness

Output:
- Deterministic checks.
- Rubric scoring where needed.
- Failure tags.

## Phase 5: Baseline Agent
Add a simple support troubleshooting agent.

Rules:
- Agent sees only ticket and tools.
- Agent must inspect environment before answering.
- Agent must follow policy before taking action.

Output:
- First full agent attempt.
- Pass/fail result from evaluator.

## Phase 6: Run Recorder
Persist every attempt.

Record:
- Run ID
- Scenario ID
- Agent version
- Prompt version
- Model/config
- Tool calls
- Tool outputs
- Final answer
- State diff
- Score
- Failure tags
- Evaluator notes

Output:
- Auditable trajectory history.

## Phase 7: Failure Analysis
Use failed runs to identify why the agent failed.

Common failure categories:
- Missed evidence
- Wrong root cause
- Bad tool sequence
- Policy violation
- Unsafe action
- Hallucinated claim
- Wrong user/account
- Unnecessary escalation

Output:
- Concrete improvement targets.

## Phase 8: Improvement Loop
Improve prompt and tool instructions from failures.

Rules:
- Rerun the same eval suite.
- Compare versions.
- Reject improvements that regress old scenarios.
- Keep holdout scenarios unseen until release check.

Output:
- Better prompt/tool policy versions.
- Measured reliability improvement.

## Phase 9: Release Threshold
Stop improving when:
- Target pass rate is met.
- Repeated runs pass.
- Critical flows have zero safety/policy failures.
- No old scenarios regress.
- Holdout scenarios pass.
- Marginal improvement is no longer meaningful.

V1 threshold:
- Login-lockout scenario passes 10/10 repeated runs.
- No wrong-user action.
- No hallucinated password reset failure.
- Required evidence used.
- Correct unlock/escalation policy followed.

## Short Version
`environment -> tools -> scenarios -> evaluator -> agent -> runs -> failures -> improvements -> release threshold`
