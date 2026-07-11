"""Score-matrix aggregation for candidate run records."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from agent_reliability_lab.evaluation import FATAL_FAILURE_TAGS
from agent_reliability_lab.optimization.candidates import (
    DEFAULT_CANDIDATE_POOL,
    CandidatePool,
)


SAFETY_FAILURE_TAGS = frozenset({"policy_violation", "wrong_user"})


@dataclass(frozen=True)
class ScoreMatrixCell:
    candidate_id: str
    scenario_id: str
    run_count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    average_score: float
    failure_counts: dict[str, int]
    fatal_failure_counts: dict[str, int]
    safety_failure_count: int
    eligible_run_count: int
    eligible_for_selection: bool
    run_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateScoreSummary:
    candidate_id: str
    run_count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    average_score: float
    failure_counts: dict[str, int]
    fatal_failure_counts: dict[str, int]
    safety_failure_count: int
    eligible_run_count: int
    eligible_for_selection: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreMatrix:
    candidate_ids: list[str]
    scenario_ids: list[str]
    cells: list[ScoreMatrixCell]
    candidate_scores: list[CandidateScoreSummary]

    def cell(self, candidate_id: str, scenario_id: str) -> ScoreMatrixCell:
        for item in self.cells:
            if item.candidate_id == candidate_id and item.scenario_id == scenario_id:
                return item
        raise KeyError(f"No score cell for {candidate_id!r} x {scenario_id!r}")

    def candidate_score(self, candidate_id: str) -> CandidateScoreSummary:
        for item in self.candidate_scores:
            if item.candidate_id == candidate_id:
                return item
        raise KeyError(f"No score summary for {candidate_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_ids": list(self.candidate_ids),
            "scenario_ids": list(self.scenario_ids),
            "cells": [cell.to_dict() for cell in self.cells],
            "candidate_scores": [
                score.to_dict() for score in self.candidate_scores
            ],
        }


def build_score_matrix(
    records: Iterable[Any],
    *,
    candidate_pool: CandidatePool = DEFAULT_CANDIDATE_POOL,
) -> ScoreMatrix:
    """Aggregate run records into candidate-by-scenario score cells."""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        payload = _record_payload(record)
        candidate_id = _candidate_id(payload, candidate_pool)
        scenario_id = _required_string(payload, "scenario_id")
        grouped[(candidate_id, scenario_id)].append(payload)

    cells = [
        _build_cell(candidate_id, scenario_id, grouped[(candidate_id, scenario_id)])
        for candidate_id, scenario_id in sorted(grouped)
    ]
    candidate_ids = sorted({cell.candidate_id for cell in cells})
    scenario_ids = sorted({cell.scenario_id for cell in cells})
    candidate_scores = [
        _build_candidate_summary(
            candidate_id,
            [
                record
                for (group_candidate_id, _), records_for_cell in grouped.items()
                if group_candidate_id == candidate_id
                for record in records_for_cell
            ],
        )
        for candidate_id in candidate_ids
    ]
    return ScoreMatrix(
        candidate_ids=candidate_ids,
        scenario_ids=scenario_ids,
        cells=cells,
        candidate_scores=candidate_scores,
    )


def assert_complete_score_matrix(
    matrix: ScoreMatrix,
    *,
    expected_candidate_ids: Iterable[str],
    expected_scenario_ids: Iterable[str],
    expected_runs_per_cell: int,
) -> None:
    """Fail unless a matrix exactly covers the expected rectangular suite."""

    candidate_ids = _unique_expected_ids(
        expected_candidate_ids,
        label="candidate",
    )
    scenario_ids = _unique_expected_ids(
        expected_scenario_ids,
        label="scenario",
    )
    if (
        not isinstance(expected_runs_per_cell, int)
        or isinstance(expected_runs_per_cell, bool)
        or expected_runs_per_cell < 1
    ):
        raise ValueError("expected_runs_per_cell must be a positive integer.")

    if set(matrix.candidate_ids) != set(candidate_ids):
        raise ValueError(
            "Score matrix candidate coverage mismatch; "
            f"expected={sorted(candidate_ids)}, actual={sorted(matrix.candidate_ids)}"
        )
    if set(matrix.scenario_ids) != set(scenario_ids):
        raise ValueError(
            "Score matrix scenario coverage mismatch; "
            f"expected={sorted(scenario_ids)}, actual={sorted(matrix.scenario_ids)}"
        )

    cell_counts = Counter(
        (cell.candidate_id, cell.scenario_id) for cell in matrix.cells
    )
    expected_cells = {
        (candidate_id, scenario_id)
        for candidate_id in candidate_ids
        for scenario_id in scenario_ids
    }
    actual_cells = set(cell_counts)
    if actual_cells != expected_cells:
        missing = sorted(expected_cells - actual_cells)
        extra = sorted(actual_cells - expected_cells)
        raise ValueError(
            "Score matrix cell coverage mismatch; "
            f"missing={missing}, extra={extra}"
        )
    duplicate_cells = sorted(
        cell for cell, count in cell_counts.items() if count != 1
    )
    if duplicate_cells:
        raise ValueError(f"Score matrix contains duplicate cells: {duplicate_cells}")

    wrong_counts = {
        (cell.candidate_id, cell.scenario_id): cell.run_count
        for cell in matrix.cells
        if cell.run_count != expected_runs_per_cell
    }
    if wrong_counts:
        raise ValueError(
            "Score matrix run-count mismatch; "
            f"expected={expected_runs_per_cell}, actual={wrong_counts}"
        )


def _unique_expected_ids(values: Iterable[str], *, label: str) -> tuple[str, ...]:
    items = tuple(values)
    if not items or not all(isinstance(item, str) and item for item in items):
        raise ValueError(f"Expected {label} IDs must be non-empty strings.")
    if len(items) != len(set(items)):
        raise ValueError(f"Expected {label} IDs must be unique.")
    return items


def _build_cell(
    candidate_id: str,
    scenario_id: str,
    records: list[dict[str, Any]],
) -> ScoreMatrixCell:
    passed_count = sum(1 for record in records if _passed(record))
    scores = [_score(record) for record in records]
    failure_counts = _failure_counts(records)
    fatal_counts = _fatal_failure_counts(failure_counts)
    eligible_run_count = sum(1 for record in records if _eligible_for_selection(record))
    return ScoreMatrixCell(
        candidate_id=candidate_id,
        scenario_id=scenario_id,
        run_count=len(records),
        passed_count=passed_count,
        failed_count=len(records) - passed_count,
        pass_rate=_ratio(passed_count, len(records)),
        average_score=_average(scores),
        failure_counts=failure_counts,
        fatal_failure_counts=fatal_counts,
        safety_failure_count=_safety_failure_count(failure_counts),
        eligible_run_count=eligible_run_count,
        eligible_for_selection=eligible_run_count == len(records),
        run_ids=sorted(_required_string(record, "run_id") for record in records),
    )


def _build_candidate_summary(
    candidate_id: str,
    records: list[dict[str, Any]],
) -> CandidateScoreSummary:
    passed_count = sum(1 for record in records if _passed(record))
    scores = [_score(record) for record in records]
    failure_counts = _failure_counts(records)
    fatal_counts = _fatal_failure_counts(failure_counts)
    eligible_run_count = sum(1 for record in records if _eligible_for_selection(record))
    return CandidateScoreSummary(
        candidate_id=candidate_id,
        run_count=len(records),
        passed_count=passed_count,
        failed_count=len(records) - passed_count,
        pass_rate=_ratio(passed_count, len(records)),
        average_score=_average(scores),
        failure_counts=failure_counts,
        fatal_failure_counts=fatal_counts,
        safety_failure_count=_safety_failure_count(failure_counts),
        eligible_run_count=eligible_run_count,
        eligible_for_selection=eligible_run_count == len(records),
    )


def _record_payload(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    to_dict = getattr(record, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, dict):
            return payload
    raise TypeError(f"Unsupported run record type: {type(record).__name__}")


def _candidate_id(record: dict[str, Any], candidate_pool: CandidatePool) -> str:
    candidate_id = record.get("candidate_id")
    if isinstance(candidate_id, str) and candidate_id:
        return candidate_id

    agent_version = _required_string(record, "agent_version")
    candidate = candidate_pool.find_by_agent_version(agent_version)
    if candidate is not None:
        return candidate.candidate_id
    return agent_version


def _evaluation(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("evaluation")
    if not isinstance(value, dict):
        raise ValueError(f"Run record has invalid evaluation: {record!r}")
    return value


def _passed(record: dict[str, Any]) -> bool:
    return bool(_evaluation(record).get("passed", False))


def _score(record: dict[str, Any]) -> float:
    score = _evaluation(record).get("score", 0.0)
    if not isinstance(score, int | float):
        raise ValueError(f"Run record has non-numeric score: {record!r}")
    return float(score)


def _failure_tags(record: dict[str, Any]) -> list[str]:
    tags = _evaluation(record).get("failure_tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError(f"Run record has invalid failure_tags: {record!r}")
    return tags


def _failure_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        counts.update(_failure_tags(record))
    return {tag: counts[tag] for tag in sorted(counts)}


def _fatal_failure_counts(failure_counts: dict[str, int]) -> dict[str, int]:
    return {
        tag: failure_counts[tag]
        for tag in sorted(failure_counts)
        if tag in FATAL_FAILURE_TAGS
    }


def _safety_failure_count(failure_counts: dict[str, int]) -> int:
    return sum(
        count
        for tag, count in failure_counts.items()
        if tag in SAFETY_FAILURE_TAGS
    )


def _eligible_for_selection(record: dict[str, Any]) -> bool:
    evaluation = _evaluation(record)
    explicit = evaluation.get("eligible_for_selection")
    if isinstance(explicit, bool):
        return explicit
    return not any(tag in FATAL_FAILURE_TAGS for tag in _failure_tags(record))


def _required_string(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Run record missing string key: {key}")
    return value


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0
