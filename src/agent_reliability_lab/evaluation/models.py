"""Evaluation result records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from agent_reliability_lab.environment.models import EnvironmentState, to_jsonable
from agent_reliability_lab.scenarios.models import Scenario


FATAL_FAILURE_TAGS = frozenset(
    {
        "policy_violation",
        "wrong_user",
        "hallucinated_password_reset_failure",
        "wrong_root_cause",
        "missing_evidence",
        "final_state_mismatch",
    }
)


@dataclass(frozen=True)
class AgentAttempt:
    scenario: Scenario
    initial_state: EnvironmentState
    final_state: EnvironmentState
    tool_calls: list[Any]
    final_response: str


@dataclass(frozen=True)
class EvaluationCheck:
    name: str
    passed: bool
    failure_tag: str | None
    message: str
    weight: float = 1.0
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _evaluation_jsonable(self)


@dataclass(frozen=True)
class EvaluationResult:
    passed: bool
    score: float
    failure_tags: list[str]
    fatal_tags: list[str]
    nonfatal_tags: list[str]
    eligible_for_selection: bool
    checks: list[EvaluationCheck]
    notes: list[str]
    feedback_text: str
    trace_excerpt: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return internal evaluator-only details for run records."""
        return _evaluation_jsonable(self)

    def to_agent_visible_dict(self) -> dict[str, Any]:
        """Return a minimal projection that does not expose hidden truth details."""
        return {
            "passed": self.passed,
            "score": self.score,
        }


def _evaluation_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            key: _evaluation_jsonable(item)
            for key, item in asdict(value).items()
            if item is not None
        }
    if isinstance(value, list):
        return [_evaluation_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _evaluation_jsonable(item) for key, item in value.items()}
    return to_jsonable(value)
