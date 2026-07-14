# Improving Agent using GEPA

A reproducible lab for evaluating and improving AI agent instructions/prompts with GEPA optimisation through prompt evolution, deterministic scenarios, and release gates.

The project provides a bounded, testable loop for support-agent reliability:

```text
scenario -> agent run -> deterministic evaluation -> reflection and mutation
         -> candidate comparison -> release regression and holdout gates
```

## Measured iteration result

The live policy was measured across four support scenarios at two engineering checkpoints:

| Checkpoint | Runs | Pass rate | Average score | Safety failures |
| --- | ---: | ---: | ---: | ---: |
| Initial live policy | 4 | 0% (0/4) | 0.6000 | 3 |
| Latest validated policy | 16 | 81.25% (13/16) | 0.9906 | 0 |

This is an observed improvement of **81.25 percentage points** in pass rate and **0.3906** in average score, with zero safety or fatal failures in the latest 16-run suite. The checkpoints span policy and evaluator hardening, so the result measures the end-to-end improvement loop rather than uplift from an accepted GEPA child alone.

## What it includes

- Realistic support and authentication scenarios with hidden evaluator truth
- Offline deterministic baseline agents and injectable OpenAI policy runners
- Structured run recording, failure analysis, and candidate score comparison
- A bounded GEPA-style system-instruction optimization loop
- Conservative regression and sealed-holdout release gates
- Collision-safe JSON persistence for runs, optimization histories, and releases

## Requirements

- Python 3.11+
- An OpenAI API key only for live OpenAI candidate or reflection runs

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

## Verify

All automated verification is offline:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall -q src tests
```

## Quick start

Run the deterministic baseline across the training scenarios:

```bash
PYTHONPATH=src python3 -m agent_reliability_lab.runs.suite \
  --candidate-id cand_baseline_v1 \
  --scenario-dir data/scenarios \
  --repeat-count 1 \
  --no-persist
```

Run one baseline attempt and persist its record to `.runs/`:

```bash
PYTHONPATH=src python3 -m agent_reliability_lab.runs.recorder
```

Analyze persisted failures:

```bash
PYTHONPATH=src python3 -m agent_reliability_lab.analysis.failures .runs
```

The live GEPA optimizer and release gate are available through:

```bash
PYTHONPATH=src python3 -m agent_reliability_lab.optimization.gepa --help
PYTHONPATH=src python3 -m agent_reliability_lab.release.gate --help
```

See [`docs/environment-v1.md`](docs/environment-v1.md) for the architecture, data boundaries, CLI options, and complete workflow.

## Safety boundary

Scenario-visible input is separated from evaluator-only truth. Automated tests do not make model or network calls, and live clients sit behind injectable interfaces. Local `.env` files, virtual environments, and generated run artifacts are excluded from Git.
