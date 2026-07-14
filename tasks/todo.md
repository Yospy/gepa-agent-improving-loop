# Todo

## Active Sprint
`sprints/gpt-5-5-model-upgrade-v1.md`

## GPT-5.5 Model Upgrade V1 (Sprint 20)
- [x] Add a regression test for the shared model default.
- [x] Upgrade the support agent and GEPA teacher default to GPT-5.5.
- [x] Update the active live-run documentation.
- [x] Run targeted, full, compile, CLI, and diff verification.
- [x] Complete structured review and document results.
- [x] Commit, push, and update the draft PR.

## Project Results Publication V1 (Sprint 19)
- [x] Add the approved project name and description.
- [x] Add reproducible initial and latest live-agent metrics.
- [x] Review the complete implementation and documentation diff.
- [x] Run full, compile, diff, and publication-safety verification.
- [x] Commit and push the intended change set.
- [x] Update repository metadata and open a draft PR.

## Evaluator + GEPA Reliability V1 (Sprint 18)
- [x] Correct evaluator paraphrase and exact-identifier semantics.
- [x] Separate completed-action confirmation from safe-next-step quality.
- [x] Align reflection with runtime invariants and mutable behavior.
- [x] Add fatal-eligibility comparison and conservative score tolerance.
- [x] Add bounded multi-child GEPA exploration and history.
- [x] Run targeted, full, compile, and controlled live verification.
- [x] Complete structured diff and side-effect review.

## OpenAI Agent Baseline Tuning V1 (Sprint 17)
- [x] Diagnose the failed live four-scenario baseline.
- [x] Compare the weak policy with the deterministic reference workflow.
- [x] Implement an evidence-first live policy.
- [x] Run only the live agent against all four scenarios and reach 4/4.
- [x] Nerf one non-safety instruction detail.
- [x] Rerun only the live four-scenario suite and record the outcome.
- [x] Complete diff, side-effect, edge-case, and sprint-intent review.

## GEPA Quality Hardening V1 (Sprint 16)
- [x] Correct identifier validation without weakening hidden-ID protection.
- [x] Add actionable evidence-call diagnostics.
- [x] Recognize natural reset-success wording.
- [x] Strengthen reflection workflow instructions.
- [x] Add one guided, audited mutation retry.
- [x] Preserve history compatibility and update CLI/docs.
- [x] Run targeted/full/compile verification and structured review.

## GitHub Publication V1
- [x] Add the sprint and executable publication plan.
- [x] Add a public-facing README.
- [x] Audit secrets and generated artifacts.
- [x] Run full tests and compile verification.
- [x] Review and create the initial commit.
- [x] Publish `main` and update GitHub repository metadata.

## Integration Smoke Hardening V1
- [x] Add real all-scenario baseline regression coverage.
- [x] Generalize deterministic baseline diagnosis and action behavior.
- [x] Add real release module-entry subprocess coverage.
- [x] Restore valid release CLI definition ordering.
- [x] Run targeted, full, compile, and CLI smoke verification.
- [x] Complete structured self-review and document results.

## Phase 15: GEPA Release Gate V1
- [x] Add fresh regression and sealed holdout scenarios.
- [x] Add validated train/regression/holdout manifest contracts.
- [x] Add explicit thresholds and preflight rollout budget.
- [x] Add three-state regression and holdout release orchestration.
- [x] Add immutable report persistence and JSON CLI.
- [x] Add exports and documentation.
- [x] Run targeted verification, full verification, and structured self-review.

## Phase 14: GEPA Optimization Loop V1
- [x] Add immutable candidate-pool extension and reflection contracts.
- [x] Build deterministic optimizer-only reflection bundles.
- [x] Add strict reflection parsing, mutation validation, and child lineage.
- [x] Add deterministic parent/child acceptance policy.
- [x] Add bounded multi-generation GEPA driver and history models.
- [x] Add collision-safe history persistence and JSON CLI.
- [x] Add exports and documentation.
- [x] Run targeted verification, full verification, and structured self-review.

## Phase 13: GEPA Evaluation Orchestrator V1
- [x] Make repeated run IDs and persistence collision-safe.
- [x] Persist internal agent failure provenance.
- [x] Add explicit scenario-suite specification and repeated candidate runner.
- [x] Capture rollout errors and block incomplete suite comparison.
- [x] Enforce complete candidate-by-scenario matrix coverage.
- [x] Add deterministic per-scenario parent/child comparison.
- [x] Add suite CLI, exports, and documentation.
- [x] Run targeted verification, full verification, and structured self-review.

## Phase 12: Scenario Suite V1
- [x] Extend environment seed with new scenario-bound records.
- [x] Add wrong-user, verified-unlock, and MFA scenario fixtures.
- [x] Add scenario-suite loader.
- [x] Generalize scenario validation beyond primary ticket.
- [x] Generalize evaluator for scenario-specific checks.
- [x] Add scenario/evaluator tests for the suite.
- [x] Document scenario suite and GEPA matrix purpose.
- [x] Run verification and self-review.

## Phase 11.5: Review Cleanup
- [x] Auto-load `.env` in the recorder CLI entry point via `python-dotenv`.
- [x] Remove dead `evidence` field from `BaselineAgentResult`/`OpenAIAgentResult`.
- [x] Fix `_run_candidate_agent` return-type drift with a shared `AgentRunResult` protocol.
- [x] Run verification.

## Phase 11: OpenAI Agent Policy Interface
- [x] Add typed OpenAI agent union states.
- [x] Add fixed strict OpenAI tool schemas and dispatcher.
- [x] Add injectable Responses client and while-loop runner.
- [x] Add degraded OpenAI policy candidate.
- [x] Wire OpenAI candidate into run recorder.
- [x] Add fake-client tests for loop, final answer, and failures.
- [x] Document live-run boundary and GEPA mutation surface.
- [x] Run verification, subagent review, and self-review.

## Phase 10.5: Reward Contract V1
- [x] Add fatal/nonfatal evaluator tag split.
- [x] Add selection eligibility flag.
- [x] Add deterministic feedback text formatter.
- [x] Add tool trace excerpt for optimizer feedback.
- [x] Keep agent-visible projection hidden-truth-safe.
- [x] Update score matrix and selection to consume eligibility.
- [x] Add reward-contract and anti-hacking-focused tests.
- [x] Run verification, subagent review, and self-review.

## Phase 9-10: Candidate Pool + Selection
- [x] Define local candidate pool and baseline candidate metadata.
- [x] Add deterministic synthetic candidate variants.
- [x] Add generic candidate scenario runner.
- [x] Persist candidate lineage metadata in run records.
- [x] Build candidate-by-scenario score matrix.
- [x] Add Pareto frontier and weighted parent selection.
- [x] Document commands and optimizer boundary.
- [x] Run verification and self-review.

## Phase 3: Scenarios
- [x] Define strict scenario and hidden-truth dataclasses.
- [x] Add first login-lockout scenario fixture.
- [x] Keep agent-visible scenario projection hidden-truth-free.
- [x] Validate scenario bindings and required evidence against environment state.
- [x] Add scenario tests.
- [x] Run full verification and review side effects.

## Phase 4: Evaluator
- [x] Define evaluator result and attempt models.
- [x] Implement deterministic evaluator checks.
- [x] Add evaluator tests for pass/fail cases.
- [x] Document evaluator behavior.
- [x] Run verification and self-review.
- [x] Run subagent code review and address findings.

## Phase 5-6: Baseline Agent + Run Recorder
- [x] Define deterministic baseline support agent.
- [x] Implement first full baseline scenario run.
- [x] Define run record model and JSON persistence.
- [x] Add baseline/run-recorder tests.
- [x] Document run command and output boundary.
- [x] Run verification and self-review.

## Phase 7-8: Failure Analysis + Improvement Reports
- [x] Load historical run records from `.runs/`.
- [x] Summarize failed runs by evaluator `failure_tags`.
- [x] Emit deterministic improvement report rows.
- [x] Compare two run sets or agent versions.
- [x] Add CLI command for local failure analysis.
- [x] Add synthetic failed-record tests plus current passing baseline record.
- [x] Document analysis command and output boundary.
- [x] Run verification and self-review.
