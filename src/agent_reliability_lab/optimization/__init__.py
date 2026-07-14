"""Candidate optimization primitives."""

from agent_reliability_lab.optimization.candidates import (
    BASELINE_CANDIDATE_ID,
    DEFAULT_CANDIDATE_POOL,
    Candidate,
    CandidatePool,
)
from agent_reliability_lab.optimization.scoring import (
    SAFETY_FAILURE_TAGS,
    CandidateScoreSummary,
    ScoreMatrix,
    ScoreMatrixCell,
    assert_complete_score_matrix,
    build_score_matrix,
)
from agent_reliability_lab.optimization.selection import (
    ParentSelection,
    SelectionWeights,
    pareto_frontier,
    select_parent_candidate,
)

__all__ = [
    "BASELINE_CANDIDATE_ID",
    "DEFAULT_CANDIDATE_POOL",
    "SAFETY_FAILURE_TAGS",
    "Candidate",
    "CandidatePool",
    "CandidateScoreSummary",
    "CandidateSuiteComparison",
    "AcceptanceDecision",
    "DEFAULT_GEPA_OUTPUT_DIR",
    "GEPAConfig",
    "GEPAChildTrial",
    "GEPAGeneration",
    "GEPAOptimizationResult",
    "MutationError",
    "MutationProposal",
    "MutationResult",
    "OpenAIReflectionClient",
    "ParentSelection",
    "ReflectionBundle",
    "ReflectionClient",
    "ReflectionExample",
    "ScenarioScoreDelta",
    "ScoreMatrix",
    "ScoreMatrixCell",
    "SelectionWeights",
    "assert_complete_score_matrix",
    "build_score_matrix",
    "compare_candidate_suites",
    "build_reflection_bundle",
    "create_child_candidate",
    "decide_candidate_acceptance",
    "format_reflection_input",
    "pareto_frontier",
    "parse_mutation_proposal",
    "persist_gepa_result",
    "reflect_and_create_child",
    "run_gepa_optimization",
    "select_parent_candidate",
]


def __getattr__(name: str) -> object:
    if name in {
        "CandidateSuiteComparison",
        "ScenarioScoreDelta",
        "compare_candidate_suites",
    }:
        from agent_reliability_lab.optimization import comparison

        return getattr(comparison, name)
    if name in {
        "MutationError",
        "MutationProposal",
        "MutationResult",
        "OpenAIReflectionClient",
        "ReflectionBundle",
        "ReflectionClient",
        "ReflectionExample",
        "build_reflection_bundle",
        "create_child_candidate",
        "format_reflection_input",
        "parse_mutation_proposal",
        "reflect_and_create_child",
    }:
        from agent_reliability_lab.optimization import reflection

        return getattr(reflection, name)
    if name in {
        "AcceptanceDecision",
        "DEFAULT_GEPA_OUTPUT_DIR",
        "GEPAConfig",
        "GEPAChildTrial",
        "GEPAGeneration",
        "GEPAOptimizationResult",
        "decide_candidate_acceptance",
        "persist_gepa_result",
        "run_gepa_optimization",
    }:
        from agent_reliability_lab.optimization import gepa

        return getattr(gepa, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
