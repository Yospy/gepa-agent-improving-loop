# Improving Agent using GEPA

A reproducible lab for evaluating and improving AI agent instructions/prompts with GEPA optimisation through prompt evolution, deterministic scenarios, and release gates.

The project provides a bounded, testable loop for support-agent reliability:

```text
scenario -> agent run -> deterministic evaluation -> reflection and mutation
         -> candidate comparison -> release regression and holdout gates
```

## Latest GEPA optimization result

On 2026-07-15, MiniMax M3 was evaluated across eight V2 hard-evidence
support cases while GLM-5.2 served as the GEPA reflection teacher. Each
scenario was run once per candidate.

| Candidate stage | Pass rate | Average task score | Decision |
| --- | ---: | ---: | --- |
| Initial parent | 25% (2/8) | 0.8875 | Baseline |
| Generation 1 | 75% (6/8) | 0.9500 | Accepted improvement |
| Generation 2 | 87.5% (7/8) | 0.9813 | Accepted improvement |
| Generation 3 | 100% (8/8) | 1.0000 | Perfect child |

Across three accepted GEPA iterations, the observed pass rate increased by
**75 percentage points**, from 25% to 100%, and the average task score increased
by **0.1125**, from 0.8875 to 1.0000. No accepted generation introduced a pass,
safety, or fatal regression.

The optimizer improved the instruction in three focused steps: it broadened
evidence time windows and strengthened escalation evidence, added compound-policy
handling for compromise cases, and required explicit failure language for the
remaining password-reset case. The run stopped with `perfect_child` after the
third generation.

These are observed optimization-suite results from one attempt per scenario.
Scores and pass rates can vary by model and run; repeated regression and sealed
holdout evaluation remain required before release promotion.

## What it includes

- Realistic support and authentication scenarios with hidden evaluator truth
- Offline deterministic baseline agents and injectable model-policy runners
- Structured run recording, failure analysis, and candidate score comparison
- A bounded GEPA-style system-instruction optimization loop
- Conservative regression and sealed-holdout release gates
- Collision-safe JSON persistence for runs, optimization histories, and releases

## Requirements

- Python 3.11+
- A Fireworks API key only for live candidate or GEPA reflection runs

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

For live OSS-model runs, put this configuration in the repo-root `.env`:

```dotenv
FIREWORKS_API_KEY=your_key
# Optional overrides:
FIREWORKS_AGENT_MODEL=accounts/fireworks/models/minimax-m3
FIREWORKS_TEACHER_MODEL=accounts/fireworks/models/glm-5p2
```

The evaluated support agent defaults to MiniMax M3. The GEPA reflection teacher
defaults to GLM-5.2. The installed OpenAI Python SDK is used only as a compatible
client for Fireworks' `/inference/v1/chat/completions` endpoint. MiniMax uses
`max_tokens=64000`; GLM uses `max_tokens=131072`; both use `top_k=40`,
`presence_penalty=0`, and `frequency_penalty=0`.

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

Scenario-visible input is separated from evaluator-only truth. Automated tests do not make model or network calls, and live clients sit behind injectable interfaces. Historical `openai_policy` candidate IDs remain unchanged for stored-record compatibility even though live traffic now uses Fireworks. Local `.env` files, virtual environments, and generated run artifacts are excluded from Git.
