"""Load and validate local scenario fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from agent_reliability_lab.environment.models import EnvironmentState
from agent_reliability_lab.environment.store import DEFAULT_ENVIRONMENT_PATH, load_seed_state
from agent_reliability_lab.scenarios.models import Scenario
from agent_reliability_lab.scenarios.validation import assert_valid_scenario


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCENARIO_DIR = REPO_ROOT / "data" / "scenarios"
DEFAULT_SCENARIO_PATH = DEFAULT_SCENARIO_DIR / "login_lockout_v1.json"


def load_scenario(
    path: Path | str = DEFAULT_SCENARIO_PATH,
    *,
    environment_state: EnvironmentState | None = None,
) -> Scenario:
    scenario_path = Path(path)
    with scenario_path.open("r", encoding="utf-8") as handle:
        raw_data = json.load(handle)

    scenario = Scenario.from_dict(raw_data)
    state = environment_state or load_seed_state(DEFAULT_ENVIRONMENT_PATH)
    assert_valid_scenario(scenario, state)
    return scenario


def load_scenario_suite(
    directory: Path | str = DEFAULT_SCENARIO_DIR,
    *,
    environment_state: EnvironmentState | None = None,
) -> list[Scenario]:
    scenario_dir = Path(directory)
    state = environment_state or load_seed_state(DEFAULT_ENVIRONMENT_PATH)
    return [
        load_scenario(path, environment_state=state)
        for path in sorted(scenario_dir.glob("*.json"))
    ]
