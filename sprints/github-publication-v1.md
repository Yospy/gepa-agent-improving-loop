# GitHub Publication V1

## Scope
- Add a repository README that explains the project, setup, verification, and core workflows.
- Review tracked content for secrets and generated artifacts.
- Create the initial commit on `main` and publish it to `Yospy/gepa-agent-improving-loop`.
- Set a concise GitHub repository description.

## Assumptions
- The complete current source, tests, fixtures, plans, and project context belong in the initial commit.
- The repository should be public and use `main` as its default branch.
- Ignored `.env`, virtual environments, and generated run directories must remain local.

## Architectural Decisions
- Keep the distribution name `agent-reliability-lab`; use `gepa-agent-improving-loop` as the repository identity.
- Make the README the concise public entry point and retain `docs/environment-v1.md` as the detailed technical reference.
- Publish directly to `main` because this is a new repository with no existing history.

## Tasks
1. Add publication plan and activate this sprint.
2. Create and review the README.
3. Run secret/artifact checks and the complete offline verification suite.
4. Review the staged diff and create the initial commit.
5. Create or connect the GitHub repository, push `main`, and update its description.
6. Verify remote metadata and document results.

## Risks
- Accidentally publishing credentials or generated local artifacts.
- Creating a remote with unexpected visibility or existing content.
- Documentation commands drifting from the implemented CLI.

## Verification Strategy
- Confirm ignored sensitive/generated paths with `git status --ignored`.
- Scan tracked candidates for common secret patterns before staging.
- Run `PYTHONPATH=src python3 -m unittest discover -s tests`.
- Run `python3 -m compileall -q src tests`.
- Review `git diff --cached --stat` and the staged file list.
- Verify the pushed branch and GitHub metadata with `gh repo view`.
