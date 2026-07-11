"""Run orchestration and persistence."""

from agent_reliability_lab.runs.models import RunRecord

__all__ = [
    "CandidateSuiteRun",
    "DEFAULT_RUN_OUTPUT_DIR",
    "NON_COMPARABLE_AGENT_FAILURES",
    "RunRecord",
    "RunRecorder",
    "ScenarioSuiteSpec",
    "SuiteRunError",
    "run_baseline_scenario",
    "run_candidate_suite",
    "run_candidate_scenario",
]


def __getattr__(name: str) -> object:
    if name in {
        "DEFAULT_RUN_OUTPUT_DIR",
        "RunRecorder",
        "run_baseline_scenario",
        "run_candidate_scenario",
    }:
        from agent_reliability_lab.runs import recorder

        return getattr(recorder, name)
    if name in {
        "CandidateSuiteRun",
        "NON_COMPARABLE_AGENT_FAILURES",
        "ScenarioSuiteSpec",
        "SuiteRunError",
        "run_candidate_suite",
    }:
        from agent_reliability_lab.runs import suite

        return getattr(suite, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
