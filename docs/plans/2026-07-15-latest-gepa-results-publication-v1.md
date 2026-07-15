# Latest GEPA Results Publication V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Publish the verified eight-case GEPA result together with the implementation that produced it.

**Architecture:** Treat the persisted GEPA history as the metric source of truth, while keeping pass rate, average score, and release certification distinct. Update only the public README narrative, then verify and publish the complete accumulated implementation on a dedicated branch.

**Tech Stack:** Python 3.11, MiniMax M3, GLM-5.2, Fireworks Chat Completions, unittest, Git, GitHub CLI.

---

### Task 1: Update the public result

**Files:**
- Modify: `README.md`
- Modify: `tasks/todo.md`

1. Replace the stale result table with baseline, generation 1, generation 2, and perfect generation 3 metrics.
2. State the exact pass-rate and average-score improvements.
3. Record model roles and the three general optimizer findings.
4. State that the result used one attempt per scenario and still requires regression/holdout release evaluation.

### Task 2: Verify the complete change set

**Files:**
- Review: all modified and untracked project files

1. Recompute metrics from `.gepa-runs/gepa_8af0ed0d79794feba56d8ae9415b4df5.json`.
2. Run the complete offline tests and compilation.
3. Smoke-test the GEPA and release CLIs.
4. Review the diff, side effects, credential patterns, and generated-artifact exclusions.
5. Record results in the active sprint.

### Task 3: Publish a draft PR

**Files:**
- Stage: the reviewed implementation, tests, fixtures, documentation, sprint, plan, and todo files

1. Create `codex/fireworks-gepa-perfect-run` from the current reviewed checkout.
2. Stage explicit intended paths and inspect the staged diff.
3. Commit with a terse summary.
4. Push the branch to `origin`.
5. Open a draft PR against `main` with metrics, findings, risks, and verification.
