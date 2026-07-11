"""Deterministic Pareto frontier and parent selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agent_reliability_lab.optimization.scoring import (
    CandidateScoreSummary,
    ScoreMatrix,
)


@dataclass(frozen=True)
class SelectionWeights:
    average_score: float = 0.7
    pass_rate: float = 0.3
    safety_penalty: float = 1.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class ParentSelection:
    selected_candidate_id: str
    frontier_candidate_ids: list[str]
    eligible_candidate_ids: list[str]
    weighted_scores: dict[str, float]
    weights: SelectionWeights
    max_safety_failures: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_candidate_id": self.selected_candidate_id,
            "frontier_candidate_ids": list(self.frontier_candidate_ids),
            "eligible_candidate_ids": list(self.eligible_candidate_ids),
            "weighted_scores": dict(self.weighted_scores),
            "weights": self.weights.to_dict(),
            "max_safety_failures": self.max_safety_failures,
        }


def pareto_frontier(matrix: ScoreMatrix) -> list[CandidateScoreSummary]:
    """Return non-dominated candidate summaries.

    Dominance maximizes pass rate and average score while minimizing safety
    failures.
    """

    return _frontier_from_candidates(matrix.candidate_scores)


def _frontier_from_candidates(
    candidates: list[CandidateScoreSummary],
) -> list[CandidateScoreSummary]:
    frontier: list[CandidateScoreSummary] = []
    for candidate in candidates:
        if not any(
            _dominates(other, candidate)
            for other in candidates
            if other.candidate_id != candidate.candidate_id
        ):
            frontier.append(candidate)
    return sorted(frontier, key=lambda item: item.candidate_id)


def select_parent_candidate(
    matrix: ScoreMatrix,
    *,
    weights: SelectionWeights = SelectionWeights(),
    max_safety_failures: int = 0,
) -> ParentSelection:
    eligible_candidates = [
        candidate
        for candidate in matrix.candidate_scores
        if candidate.eligible_for_selection
        and candidate.safety_failure_count <= max_safety_failures
    ]
    frontier = _frontier_from_candidates(eligible_candidates)
    eligible = [
        candidate
        for candidate in frontier
        if candidate.eligible_for_selection
        and candidate.safety_failure_count <= max_safety_failures
    ]
    if not eligible:
        raise ValueError(
            "No Pareto-frontier candidates satisfy the safety failure constraint."
        )

    weighted_scores = {
        candidate.candidate_id: _weighted_score(candidate, weights)
        for candidate in eligible
    }
    selected = sorted(
        eligible,
        key=lambda candidate: (
            -weighted_scores[candidate.candidate_id],
            candidate.candidate_id,
        ),
    )[0]
    return ParentSelection(
        selected_candidate_id=selected.candidate_id,
        frontier_candidate_ids=[candidate.candidate_id for candidate in frontier],
        eligible_candidate_ids=[candidate.candidate_id for candidate in eligible],
        weighted_scores=weighted_scores,
        weights=weights,
        max_safety_failures=max_safety_failures,
    )


def _dominates(
    challenger: CandidateScoreSummary,
    candidate: CandidateScoreSummary,
) -> bool:
    no_worse = (
        challenger.pass_rate >= candidate.pass_rate
        and challenger.average_score >= candidate.average_score
        and challenger.safety_failure_count <= candidate.safety_failure_count
    )
    strictly_better = (
        challenger.pass_rate > candidate.pass_rate
        or challenger.average_score > candidate.average_score
        or challenger.safety_failure_count < candidate.safety_failure_count
    )
    return no_worse and strictly_better


def _weighted_score(
    candidate: CandidateScoreSummary,
    weights: SelectionWeights,
) -> float:
    score = (
        candidate.average_score * weights.average_score
        + candidate.pass_rate * weights.pass_rate
        - candidate.safety_failure_count * weights.safety_penalty
    )
    return round(score, 4)
