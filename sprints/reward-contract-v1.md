# Reward Contract V1

## Scope
- Extend deterministic evaluation output with fatal tags, nonfatal tags, and selection eligibility.
- Add deterministic text feedback assembled from existing check messages, details, expected evidence, tool calls, final response, and final state mismatches.
- Preserve the current numeric score and pass/fail semantics.
- Keep agent-visible projections hidden-truth-safe.
- Update candidate score aggregation/selection to respect evaluator eligibility.

## Assumptions
- No LLM is needed for scoring or feedback generation.
- Feedback may include evaluator-only scenario details because it is intended for the optimizer/teacher path, not the task agent.
- Fatal tags should prevent a run from winning during GEPA-style selection.
- Existing short `notes` should remain for backward-compatible summaries.

## Architectural Decisions
- Keep the reward contract inside `agent_reliability_lab.evaluation`.
- Derive feedback from existing `EvaluationCheck.details` and scenario hidden truth instead of adding a second evaluator.
- Use hard gates before scalar score: eligibility is independent of the raw score.
- Keep `EvaluationResult.to_agent_visible_dict()` minimal: only pass/fail and score.

## Step-by-Step Tasks
1. Add fatal-tag constants and new reward-contract fields to evaluation result models.
2. Build deterministic trace excerpts and failure feedback text in the evaluator.
3. Add targeted tests for fatal eligibility, nonfatal eligibility, feedback content, and hidden-detail projection safety.
4. Update score matrix and parent selection to consume `eligible_for_selection`.
5. Document the reward contract and run verification.

## Risks
- Feedback can become too vague if it only repeats failure tags.
- Feedback can leak hidden truth if accidentally exposed through agent-visible projections.
- Numeric score can still reward partial unsafe behavior unless eligibility gates are enforced downstream.

## Verification Strategy
- `PYTHONPATH=src python3 -m unittest tests.test_evaluator`
- `PYTHONPATH=src python3 -m unittest tests.test_candidate_optimization`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall -q src tests`
- Subagent code review focused on reward hacking, hidden-truth leakage, and backward compatibility.
