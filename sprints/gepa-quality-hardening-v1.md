# GEPA Quality Hardening V1 (Sprint 16)

## Scope
- Prevent legitimate public tool names from triggering identifier-memorization rejection.
- Improve deterministic feedback when a required tool was called with arguments
  that excluded required evidence.
- Recognize natural, semantically valid password-reset-success wording.
- Require reflection proposals to express explicit evidence/action workflow rules.
- Retry one retryable mutation failure with validation feedback and preserve
  every mutation attempt in optimization history.

## Assumptions
- Evaluator pass criteria and check weights remain unchanged.
- Existing history consumers continue reading the terminal `mutation` field.
- One retry is sufficient for V1 and bounds live cost.
- Automated tests use injected clients and make no network calls.

## Architectural Decisions
- Match forbidden identifiers as complete underscore-aware tokens instead of
  substrings; exact hidden identifiers remain blocked.
- Add evidence diagnostics to existing evaluator check details and feedback
  rather than introducing a second evaluator.
- Preserve the two-field reflection response contract and strengthen only its
  instructions and retry input context.
- Add optional `revision_feedback` to `ReflectionBundle` for retry guidance.
- Keep `GEPAGeneration.mutation` as the terminal attempt for backward
  compatibility and add ordered `mutation_attempts` for auditability.
- Retry only model-output/validation failures, not transport errors.

## Step-by-Step Tasks
1. Add failing validator tests for `get_mfa_status` and exact hidden identifiers.
2. Implement exact-token identifier matching.
3. Add failing evaluator tests for narrow auth windows and natural reset wording.
4. Add evidence-call diagnostics and broaden reset-success recognition.
5. Strengthen reflection instructions around tool order, time windows, concrete
   record IDs, safe actions, and customer responses.
6. Add failing driver tests for one guided mutation retry and audited attempts.
7. Implement bounded retry configuration, revision feedback, CLI option, and
   backward-compatible history serialization.
8. Update documentation, run all verification, and complete structured review.

## Risks
- Looser identifier checks could permit actual record memorization.
- Feedback could overstate why a tool output omitted a record.
- Retry history could break release-history loading.
- Natural-language matching could admit ambiguous reset claims.

## Verification Strategy
- `PYTHONPATH=src python3 -m unittest tests.test_gepa_reflection -v`
- `PYTHONPATH=src python3 -m unittest tests.test_evaluator -v`
- `PYTHONPATH=src python3 -m unittest tests.test_gepa_driver -v`
- `PYTHONPATH=src python3 -m unittest tests.test_release_gate -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m compileall -q src tests`
- Offline fake-client smoke test: first mutation invalid, second valid, child runs once.

## Results
- Exact hidden identifiers remain rejected while embedded public tool names are accepted.
- Missing-evidence feedback now distinguishes absent calls from narrow or incorrect arguments.
- Reflection requires an operational evidence/action workflow and receives validation feedback once.
- Every mutation proposal is audited in `mutation_attempts`; `mutation` remains compatible.
- `136` repository tests passed; compilation and GEPA CLI help smoke checks passed.

## Structured Review
- Minimal change: reused the evaluator, reflection bundle, and existing mutation result types.
- Boundaries: feedback remains optimizer-only; no hidden-truth container reaches the agent.
- Safety: evaluator weights and conservative child acceptance are unchanged.
- Cost: retry count is validated and bounded; reflection transport failures are never retried.
- Compatibility: field ordering preserves positional config use and the release-history loader passes.
- Remaining scope: checkpoint resume and multi-child search remain intentionally deferred.
