"""Load and reset the local support environment."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from agent_reliability_lab.environment.models import EnvironmentState
from agent_reliability_lab.environment.validation import assert_valid_environment


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENVIRONMENT_PATH = REPO_ROOT / "data" / "environment" / "support_env_v1.json"


def load_seed_state(path: Path | str = DEFAULT_ENVIRONMENT_PATH) -> EnvironmentState:
    seed_path = Path(path)
    with seed_path.open("r", encoding="utf-8") as handle:
        raw_data = json.load(handle)

    state = EnvironmentState.from_dict(raw_data)
    assert_valid_environment(state)
    return state


class EnvironmentStore:
    """Mutable working copy backed by a validated immutable seed snapshot."""

    def __init__(self, seed_state: EnvironmentState) -> None:
        assert_valid_environment(seed_state)
        self._seed_state = deepcopy(seed_state)
        self._state = deepcopy(seed_state)

    @classmethod
    def from_seed(
        cls, path: Path | str = DEFAULT_ENVIRONMENT_PATH
    ) -> "EnvironmentStore":
        return cls(load_seed_state(path))

    @property
    def state(self) -> EnvironmentState:
        return self._state

    def snapshot(self) -> EnvironmentState:
        return deepcopy(self._state)

    def reset(self) -> EnvironmentState:
        self._state = deepcopy(self._seed_state)
        return self.snapshot()

    def state_hash(self) -> str:
        payload = json.dumps(
            self._state.to_seed_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()
