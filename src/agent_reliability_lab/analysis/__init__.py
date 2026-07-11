"""Offline run analysis helpers."""

__all__ = [
    "FailureAnalysisReport",
    "FailureSummary",
    "ImprovementReportRow",
    "RunSetComparison",
    "analyze_runs",
    "compare_agent_versions",
    "compare_run_sets",
    "load_run_records",
]


def __getattr__(name: str) -> object:
    if name in __all__:
        from agent_reliability_lab.analysis import failures

        return getattr(failures, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
