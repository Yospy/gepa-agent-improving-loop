"""Serializable run records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent_reliability_lab.environment.models import to_jsonable


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    scenario_id: str
    scenario_version: str
    environment_id: str
    agent_name: str
    agent_version: str
    started_at: datetime
    completed_at: datetime
    initial_state_hash: str
    final_state_hash: str
    state_diff: dict[str, Any]
    agent_visible_scenario: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    final_response: str
    evaluation: dict[str, Any]
    agent_visible_evaluation: dict[str, Any]
    candidate_id: str | None = None
    parent_candidate_id: str | None = None
    candidate_generation: int | None = None
    candidate_kind: str | None = None
    agent_trace: list[dict[str, Any]] | None = None
    agent_failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)

    def to_agent_visible_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "final_response": self.final_response,
            "evaluation": dict(self.agent_visible_evaluation),
        }
