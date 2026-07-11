"""Pure per-scenario comparison for complete candidate suite runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agent_reliability_lab.optimization.scoring import (
    assert_complete_score_matrix,
)
from agent_reliability_lab.runs.suite import CandidateSuiteRun


@dataclass(frozen=True)
class ScenarioScoreDelta:
    scenario_id: str
    parent_run_count: int
    child_run_count: int
    parent_pass_rate: float
    child_pass_rate: float
    pass_rate_delta: float
    parent_average_score: float
    child_average_score: float
    average_score_delta: float
    parent_safety_failure_count: int
    child_safety_failure_count: int
    safety_failure_delta: int
    pass_regressed: bool
    safety_regressed: bool
    improved: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateSuiteComparison:
    suite_name: str
    parent_candidate_id: str
    child_candidate_id: str
    repeat_count: int
    scenario_deltas: tuple[ScenarioScoreDelta, ...]
    regressed_scenario_ids: tuple[str, ...]
    improved_scenario_ids: tuple[str, ...]
    safety_regressed_scenario_ids: tuple[str, ...]

    def scenario_delta(self, scenario_id: str) -> ScenarioScoreDelta:
        for delta in self.scenario_deltas:
            if delta.scenario_id == scenario_id:
                return delta
        raise KeyError(f"No scenario comparison for {scenario_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "parent_candidate_id": self.parent_candidate_id,
            "child_candidate_id": self.child_candidate_id,
            "repeat_count": self.repeat_count,
            "scenario_deltas": [
                delta.to_dict() for delta in self.scenario_deltas
            ],
            "regressed_scenario_ids": list(self.regressed_scenario_ids),
            "improved_scenario_ids": list(self.improved_scenario_ids),
            "safety_regressed_scenario_ids": list(
                self.safety_regressed_scenario_ids
            ),
        }


def compare_candidate_suites(
    parent: CandidateSuiteRun,
    child: CandidateSuiteRun,
) -> CandidateSuiteComparison:
    """Compare two complete, coverage-matched candidate suite runs."""

    scenario_ids = _assert_comparable(parent, child)
    assert parent.matrix is not None
    assert child.matrix is not None

    scenario_deltas = tuple(
        _scenario_delta(
            scenario_id,
            parent.matrix.cell(parent.candidate_id, scenario_id),
            child.matrix.cell(child.candidate_id, scenario_id),
        )
        for scenario_id in scenario_ids
    )
    return CandidateSuiteComparison(
        suite_name=parent.suite_name,
        parent_candidate_id=parent.candidate_id,
        child_candidate_id=child.candidate_id,
        repeat_count=parent.repeat_count,
        scenario_deltas=scenario_deltas,
        regressed_scenario_ids=tuple(
            delta.scenario_id for delta in scenario_deltas if delta.pass_regressed
        ),
        improved_scenario_ids=tuple(
            delta.scenario_id for delta in scenario_deltas if delta.improved
        ),
        safety_regressed_scenario_ids=tuple(
            delta.scenario_id
            for delta in scenario_deltas
            if delta.safety_regressed
        ),
    )


def _assert_comparable(
    parent: CandidateSuiteRun,
    child: CandidateSuiteRun,
) -> tuple[str, ...]:
    if not parent.complete or not child.complete:
        raise ValueError("Candidate suite comparison requires complete suites.")
    if parent.candidate_id == child.candidate_id:
        raise ValueError("Parent and child candidate IDs must differ.")
    if parent.suite_name != child.suite_name:
        raise ValueError("Parent and child suite names must match.")
    if parent.repeat_count != child.repeat_count:
        raise ValueError("Parent and child repeat counts must match.")

    parent_scenarios = tuple(sorted(parent.scenario_ids))
    child_scenarios = tuple(sorted(child.scenario_ids))
    if parent_scenarios != child_scenarios:
        raise ValueError("Parent and child scenario IDs must match.")

    assert parent.matrix is not None
    assert child.matrix is not None
    assert_complete_score_matrix(
        parent.matrix,
        expected_candidate_ids=[parent.candidate_id],
        expected_scenario_ids=parent_scenarios,
        expected_runs_per_cell=parent.repeat_count,
    )
    assert_complete_score_matrix(
        child.matrix,
        expected_candidate_ids=[child.candidate_id],
        expected_scenario_ids=child_scenarios,
        expected_runs_per_cell=child.repeat_count,
    )
    return parent_scenarios


def _scenario_delta(scenario_id: str, parent: Any, child: Any) -> ScenarioScoreDelta:
    pass_rate_delta = round(child.pass_rate - parent.pass_rate, 4)
    average_score_delta = round(child.average_score - parent.average_score, 4)
    safety_failure_delta = child.safety_failure_count - parent.safety_failure_count
    return ScenarioScoreDelta(
        scenario_id=scenario_id,
        parent_run_count=parent.run_count,
        child_run_count=child.run_count,
        parent_pass_rate=parent.pass_rate,
        child_pass_rate=child.pass_rate,
        pass_rate_delta=pass_rate_delta,
        parent_average_score=parent.average_score,
        child_average_score=child.average_score,
        average_score_delta=average_score_delta,
        parent_safety_failure_count=parent.safety_failure_count,
        child_safety_failure_count=child.safety_failure_count,
        safety_failure_delta=safety_failure_delta,
        pass_regressed=pass_rate_delta < 0,
        safety_regressed=safety_failure_delta > 0,
        improved=(
            pass_rate_delta > 0
            or (pass_rate_delta == 0 and average_score_delta > 0)
        ),
    )
