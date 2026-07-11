# GitHub Publication V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prepare the existing agent reliability lab for public GitHub use and publish its initial `main` branch.

**Architecture:** Add a concise README over the existing detailed environment documentation, keep local secrets and generated output excluded, and preserve the complete project history as one intentional initial commit. Use local Git for review and publication, then GitHub CLI for repository creation and metadata verification.

**Tech Stack:** Python 3.11, unittest, Git, GitHub CLI, Markdown.

---

### Task 1: Add the public repository entry point

**Files:**
- Create: `README.md`
- Create: `sprints/github-publication-v1.md`
- Create: `docs/plans/2026-07-11-github-publication-v1.md`
- Modify: `tasks/todo.md`

1. Write the README with purpose, capabilities, setup, verification, and core CLI examples.
2. Confirm every documented command maps to an implemented module.
3. Review the README for public-facing clarity and absence of local credentials.

### Task 2: Verify the publication contents

**Files:**
- Review: `.gitignore`
- Review: all untracked source, data, docs, and tests

1. Confirm `.env`, `.venv`, caches, and generated run directories are ignored.
2. Scan publishable files for common credential patterns and private key material.
3. Run `PYTHONPATH=src python3 -m unittest discover -s tests`; expect all tests to pass.
4. Run `python3 -m compileall -q src tests`; expect exit code 0.

### Task 3: Commit and publish

**Files:**
- Stage: the complete reviewed project tree

1. Stage the reviewed project contents and inspect the staged file list and diff summary.
2. Commit with message `Initial commit` on `main`.
3. Create or connect `https://github.com/Yospy/gepa-agent-improving-loop.git` as `origin`.
4. Push `main` with upstream tracking.
5. Set the GitHub description to: `A reproducible lab for evaluating and improving AI agent policies with GEPA-style prompt evolution, deterministic scenarios, and release gates.`
6. Verify visibility, default branch, description, and remote tracking.
