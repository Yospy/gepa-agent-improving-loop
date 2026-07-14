# Project Results Publication V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Publish the completed agent/evaluator reliability work with an accurate public project description and measured iteration result.

**Architecture:** Update the README as the public entry point, retaining detailed system documentation under `docs/`. Report the initial and latest live-suite checkpoints with sample sizes and a concise caveat so the metric remains reproducible and honest.

**Tech Stack:** Markdown, Python 3.11, unittest, Git, GitHub CLI.

---

### Task 1: Publish the project identity and result

**Files:**
- Modify: `README.md`
- Modify: `tasks/todo.md`

1. Replace the repository slug heading with the approved project name.
2. Use the approved description with GEPA optimisation wording.
3. Add initial and latest pass rate, average score, safety result, and run counts.
4. State that the checkpoints span policy and evaluator hardening and do not represent an accepted-child-only uplift.

### Task 2: Verify the complete change set

**Files:**
- Review: all modified and untracked project files

1. Run the full unittest suite; expect all tests to pass.
2. Run compileall; expect exit code 0.
3. Run `git diff --check`; expect no whitespace errors.
4. Scan intended publishable files for credential patterns and generated artifacts.
5. Review the complete diff for scope, boundaries, side effects, and sprint alignment.

### Task 3: Publish a draft pull request

**Files:**
- Stage: only reviewed source, tests, docs, plans, and sprint files

1. Create branch `codex/gepa-reliability-results`.
2. Stage the reviewed paths explicitly and inspect the staged diff.
3. Commit with a concise reliability-results message.
4. Push the branch to `origin`.
5. Set the approved GitHub repository description.
6. Open a draft PR to `main` and verify its metadata.
