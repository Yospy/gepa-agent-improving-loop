"""Release evaluation and promotion gates."""

__all__ = [
    "DEFAULT_RELEASE_OUTPUT_DIR",
    "ReleaseGateConfig",
    "ReleaseGateResult",
    "ReleaseSuiteManifest",
    "ReleaseThresholds",
    "load_candidate_pool_from_gepa_history",
    "persist_release_result",
    "run_release_gate",
]


def __getattr__(name: str) -> object:
    if name in set(__all__):
        from agent_reliability_lab.release import gate

        return getattr(gate, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
