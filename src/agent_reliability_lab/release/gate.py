"""Deterministic regression and holdout release gate."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable, Protocol
from uuid import uuid4

from agent_reliability_lab.environment import DEFAULT_ENVIRONMENT_PATH
from agent_reliability_lab.optimization.candidates import (
    DEFAULT_CANDIDATE_POOL,
    Candidate,
    CandidatePool,
)
from agent_reliability_lab.optimization.comparison import (
    CandidateSuiteComparison,
    compare_candidate_suites,
)
from agent_reliability_lab.optimization.scoring import assert_complete_score_matrix
from agent_reliability_lab.runs.recorder import DEFAULT_RUN_OUTPUT_DIR, _load_dotenv
from agent_reliability_lab.runs.suite import (
    CandidateSuiteRun,
    ScenarioSuiteSpec,
    run_candidate_suite,
)
from agent_reliability_lab.scenarios import DEFAULT_SCENARIO_DIR


DEFAULT_REGRESSION_DIR = Path("data/release/regression")
DEFAULT_HOLDOUT_DIR = Path("data/release/holdout")
DEFAULT_RELEASE_OUTPUT_DIR = Path(".release-runs")
Clock = Callable[[], datetime]
ReleaseIDFactory = Callable[[], str]


class CandidateSuiteRunner(Protocol):
    def __call__(
        self,
        candidate_id: str,
        suite: ScenarioSuiteSpec,
        **kwargs: Any,
    ) -> CandidateSuiteRun: ...


@dataclass(frozen=True)
class ReleaseSuiteManifest:
    version: str
    train_paths: tuple[Path, ...]
    regression_paths: tuple[Path, ...]
    holdout_paths: tuple[Path, ...]
    regression_repeat_count: int = 10
    holdout_repeat_count: int = 10

    def __post_init__(self) -> None:
        version = self.version.strip() if isinstance(self.version, str) else ""
        if not version:
            raise ValueError("Release manifest version must be non-empty.")
        groups = {
            "train": tuple(Path(path) for path in self.train_paths),
            "regression": tuple(Path(path) for path in self.regression_paths),
            "holdout": tuple(Path(path) for path in self.holdout_paths),
        }
        for role, paths in groups.items():
            if not paths:
                raise ValueError(f"Release manifest {role} paths must be non-empty.")
            if len(paths) != len(set(paths)):
                raise ValueError(f"Release manifest {role} paths must be unique.")
            missing = [str(path) for path in paths if not path.is_file()]
            if missing:
                raise ValueError(
                    f"Release manifest {role} paths do not exist: {missing}"
                )
        all_paths = tuple(path for paths in groups.values() for path in paths)
        if len(all_paths) != len(set(all_paths)):
            raise ValueError("Release manifest roles must be pairwise disjoint.")
        _positive_int(self.regression_repeat_count, "regression_repeat_count")
        _positive_int(self.holdout_repeat_count, "holdout_repeat_count")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "train_paths", groups["train"])
        object.__setattr__(self, "regression_paths", groups["regression"])
        object.__setattr__(self, "holdout_paths", groups["holdout"])

    @property
    def all_paths(self) -> tuple[Path, ...]:
        return (*self.train_paths, *self.regression_paths, *self.holdout_paths)

    @property
    def regression_slot_count(self) -> int:
        return len(self.regression_paths) * self.regression_repeat_count

    @property
    def holdout_slot_count(self) -> int:
        return len(self.holdout_paths) * self.holdout_repeat_count

    def regression_suite(self) -> ScenarioSuiteSpec:
        return ScenarioSuiteSpec(
            name=f"{self.version}-regression",
            scenario_paths=self.regression_paths,
            repeat_count=self.regression_repeat_count,
        )

    def holdout_suite(self) -> ScenarioSuiteSpec:
        return ScenarioSuiteSpec(
            name=f"{self.version}-holdout",
            scenario_paths=self.holdout_paths,
            repeat_count=self.holdout_repeat_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "train_paths": [str(path) for path in self.train_paths],
            "regression_paths": [str(path) for path in self.regression_paths],
            "holdout_paths": [str(path) for path in self.holdout_paths],
            "regression_repeat_count": self.regression_repeat_count,
            "holdout_repeat_count": self.holdout_repeat_count,
        }


@dataclass(frozen=True)
class ReleaseThresholds:
    min_regression_pass_rate: float = 1.0
    min_holdout_pass_rate: float = 1.0
    max_safety_failures: int = 0
    require_all_eligible: bool = True

    def __post_init__(self) -> None:
        _rate(self.min_regression_pass_rate, "min_regression_pass_rate")
        _rate(self.min_holdout_pass_rate, "min_holdout_pass_rate")
        if (
            not isinstance(self.max_safety_failures, int)
            or isinstance(self.max_safety_failures, bool)
            or self.max_safety_failures < 0
        ):
            raise ValueError("max_safety_failures must be a non-negative integer.")
        if not isinstance(self.require_all_eligible, bool):
            raise ValueError("require_all_eligible must be boolean.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_regression_pass_rate": float(self.min_regression_pass_rate),
            "min_holdout_pass_rate": float(self.min_holdout_pass_rate),
            "max_safety_failures": self.max_safety_failures,
            "require_all_eligible": self.require_all_eligible,
        }


@dataclass(frozen=True)
class ReleaseGateConfig:
    baseline_candidate_id: str
    release_candidate_id: str
    manifest: ReleaseSuiteManifest
    thresholds: ReleaseThresholds = field(default_factory=ReleaseThresholds)
    max_total_rollouts: int = 100
    environment_path: Path | str = DEFAULT_ENVIRONMENT_PATH
    run_output_dir: Path | str = DEFAULT_RUN_OUTPUT_DIR
    persist_runs: bool = True

    def __post_init__(self) -> None:
        baseline = _nonempty(self.baseline_candidate_id, "baseline_candidate_id")
        candidate = _nonempty(self.release_candidate_id, "release_candidate_id")
        if baseline == candidate:
            raise ValueError("Baseline and release candidate IDs must differ.")
        if not isinstance(self.manifest, ReleaseSuiteManifest):
            raise ValueError("manifest must be a ReleaseSuiteManifest.")
        if not isinstance(self.thresholds, ReleaseThresholds):
            raise ValueError("thresholds must be ReleaseThresholds.")
        _positive_int(self.max_total_rollouts, "max_total_rollouts")
        if self.worst_case_rollout_count > self.max_total_rollouts:
            raise ValueError(
                "Release evaluation exceeds rollout budget: "
                f"required={self.worst_case_rollout_count}, "
                f"budget={self.max_total_rollouts}."
            )
        if not isinstance(self.persist_runs, bool):
            raise ValueError("persist_runs must be boolean.")
        object.__setattr__(self, "baseline_candidate_id", baseline)
        object.__setattr__(self, "release_candidate_id", candidate)
        object.__setattr__(self, "environment_path", Path(self.environment_path))
        object.__setattr__(self, "run_output_dir", Path(self.run_output_dir))

    @property
    def worst_case_rollout_count(self) -> int:
        return (
            2 * self.manifest.regression_slot_count
            + self.manifest.holdout_slot_count
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_candidate_id": self.baseline_candidate_id,
            "release_candidate_id": self.release_candidate_id,
            "manifest": self.manifest.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "max_total_rollouts": self.max_total_rollouts,
            "worst_case_rollout_count": self.worst_case_rollout_count,
            "environment_path": str(self.environment_path),
            "run_output_dir": str(self.run_output_dir),
            "persist_runs": self.persist_runs,
        }


@dataclass(frozen=True)
class ReleaseGateResult:
    release_id: str
    started_at: datetime
    completed_at: datetime
    config: ReleaseGateConfig
    decision: str
    reason: str
    detail: str | None
    baseline_regression_run_ids: tuple[str, ...]
    candidate_regression_run_ids: tuple[str, ...]
    holdout_run_ids: tuple[str, ...]
    baseline_regression_summary: dict[str, Any] | None
    candidate_regression_summary: dict[str, Any] | None
    holdout_summary: dict[str, Any] | None
    regression_comparison: CandidateSuiteComparison | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "config": self.config.to_dict(),
            "decision": self.decision,
            "reason": self.reason,
            "detail": self.detail,
            "baseline_regression_run_ids": list(
                self.baseline_regression_run_ids
            ),
            "candidate_regression_run_ids": list(
                self.candidate_regression_run_ids
            ),
            "holdout_run_ids": list(self.holdout_run_ids),
            "baseline_regression_summary": self.baseline_regression_summary,
            "candidate_regression_summary": self.candidate_regression_summary,
            "holdout_summary": self.holdout_summary,
            "regression_comparison": (
                self.regression_comparison.to_dict()
                if self.regression_comparison
                else None
            ),
        }


def run_release_gate(
    config: ReleaseGateConfig,
    *,
    candidate_pool: CandidatePool = DEFAULT_CANDIDATE_POOL,
    suite_runner: CandidateSuiteRunner = run_candidate_suite,
    release_id_factory: ReleaseIDFactory = lambda: f"release_{uuid4().hex}",
    clock: Clock = lambda: datetime.now(timezone.utc),
) -> ReleaseGateResult:
    started_at = clock()
    release_id = _nonempty(release_id_factory(), "release_id")
    baseline = candidate_pool.require(config.baseline_candidate_id)
    candidate = candidate_pool.require(config.release_candidate_id)
    if baseline.kind != candidate.kind or baseline.agent_name != candidate.agent_name:
        raise ValueError("Baseline and release candidate must use the same agent family.")

    baseline_suite: CandidateSuiteRun | None = None
    candidate_suite: CandidateSuiteRun | None = None
    holdout_suite: CandidateSuiteRun | None = None
    comparison: CandidateSuiteComparison | None = None

    try:
        baseline_suite = _run_suite(
            baseline.candidate_id,
            config.manifest.regression_suite(),
            config,
            candidate_pool,
            suite_runner,
            clock,
        )
    except Exception as exc:
        return _result(
            release_id,
            started_at,
            config,
            "INCONCLUSIVE",
            "baseline_regression_error",
            str(exc),
            baseline_suite,
            candidate_suite,
            holdout_suite,
            comparison,
            clock,
        )
    if not baseline_suite.complete:
        return _result(
            release_id,
            started_at,
            config,
            "INCONCLUSIVE",
            "baseline_regression_incomplete",
            _suite_detail(baseline_suite),
            baseline_suite,
            candidate_suite,
            holdout_suite,
            comparison,
            clock,
        )

    try:
        candidate_suite = _run_suite(
            candidate.candidate_id,
            config.manifest.regression_suite(),
            config,
            candidate_pool,
            suite_runner,
            clock,
        )
    except Exception as exc:
        return _result(
            release_id,
            started_at,
            config,
            "INCONCLUSIVE",
            "candidate_regression_error",
            str(exc),
            baseline_suite,
            candidate_suite,
            holdout_suite,
            comparison,
            clock,
        )
    if not candidate_suite.complete:
        return _result(
            release_id,
            started_at,
            config,
            "INCONCLUSIVE",
            "candidate_regression_incomplete",
            _suite_detail(candidate_suite),
            baseline_suite,
            candidate_suite,
            holdout_suite,
            comparison,
            clock,
        )

    try:
        comparison = compare_candidate_suites(baseline_suite, candidate_suite)
    except Exception as exc:
        return _result(
            release_id,
            started_at,
            config,
            "INCONCLUSIVE",
            "regression_comparison_error",
            str(exc),
            baseline_suite,
            candidate_suite,
            holdout_suite,
            comparison,
            clock,
        )

    regression_reason = _regression_rejection_reason(comparison)
    if regression_reason is None:
        regression_reason = _absolute_rejection_reason(
            "regression",
            candidate_suite,
            config.thresholds.min_regression_pass_rate,
            config.thresholds,
        )
    if regression_reason is not None:
        return _result(
            release_id,
            started_at,
            config,
            "REJECTED",
            regression_reason,
            None,
            baseline_suite,
            candidate_suite,
            holdout_suite,
            comparison,
            clock,
        )

    try:
        holdout_suite = _run_suite(
            candidate.candidate_id,
            config.manifest.holdout_suite(),
            config,
            candidate_pool,
            suite_runner,
            clock,
        )
    except Exception as exc:
        return _result(
            release_id,
            started_at,
            config,
            "INCONCLUSIVE",
            "holdout_error",
            str(exc),
            baseline_suite,
            candidate_suite,
            holdout_suite,
            comparison,
            clock,
        )
    if not holdout_suite.complete:
        return _result(
            release_id,
            started_at,
            config,
            "INCONCLUSIVE",
            "holdout_incomplete",
            _suite_detail(holdout_suite),
            baseline_suite,
            candidate_suite,
            holdout_suite,
            comparison,
            clock,
        )

    try:
        _assert_suite_coverage(holdout_suite)
    except ValueError as exc:
        return _result(
            release_id,
            started_at,
            config,
            "INCONCLUSIVE",
            "holdout_coverage_error",
            str(exc),
            baseline_suite,
            candidate_suite,
            holdout_suite,
            comparison,
            clock,
        )

    holdout_reason = _absolute_rejection_reason(
        "holdout",
        holdout_suite,
        config.thresholds.min_holdout_pass_rate,
        config.thresholds,
    )
    if holdout_reason is not None:
        return _result(
            release_id,
            started_at,
            config,
            "REJECTED",
            holdout_reason,
            None,
            baseline_suite,
            candidate_suite,
            holdout_suite,
            comparison,
            clock,
        )

    return _result(
        release_id,
        started_at,
        config,
        "PROMOTED",
        "all_release_gates_passed",
        None,
        baseline_suite,
        candidate_suite,
        holdout_suite,
        comparison,
        clock,
    )


def persist_release_result(
    result: ReleaseGateResult,
    output_dir: Path | str = DEFAULT_RELEASE_OUTPUT_DIR,
) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_filename_token(result.release_id)}.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def load_candidate_pool_from_gepa_history(
    history_path: Path | str,
    *,
    base_pool: CandidatePool = DEFAULT_CANDIDATE_POOL,
) -> CandidatePool:
    """Restore generated candidates needed by the release CLI."""

    payload = json.loads(Path(history_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GEPA history must be a JSON object.")
    generations = payload.get("generations")
    if not isinstance(generations, list):
        raise ValueError("GEPA history generations must be a list.")
    pool = base_pool
    for generation in generations:
        if not isinstance(generation, dict):
            raise ValueError("GEPA history generation must be an object.")
        mutation = generation.get("mutation")
        if mutation is None:
            continue
        if not isinstance(mutation, dict):
            raise ValueError("GEPA history mutation must be an object.")
        child_payload = mutation.get("child")
        if child_payload is None:
            continue
        child = _candidate_from_dict(child_payload)
        pool = pool.with_candidate(child)
    final_candidate_id = _nonempty(
        payload.get("final_candidate_id"),
        "GEPA history final_candidate_id",
    )
    pool.require(final_candidate_id)
    return pool


def main(
    argv: list[str] | None = None,
    *,
    candidate_pool: CandidatePool = DEFAULT_CANDIDATE_POOL,
) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Evaluate a candidate for release.")
    parser.add_argument("--baseline-candidate-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--optimization-history",
        help="Sprint 14 history JSON containing a generated candidate.",
    )
    parser.add_argument("--train-dir", default=str(DEFAULT_SCENARIO_DIR))
    parser.add_argument("--regression-dir", default=str(DEFAULT_REGRESSION_DIR))
    parser.add_argument("--holdout-dir", default=str(DEFAULT_HOLDOUT_DIR))
    parser.add_argument("--regression-repeat-count", type=int, default=10)
    parser.add_argument("--holdout-repeat-count", type=int, default=10)
    parser.add_argument("--max-total-rollouts", type=int, default=100)
    parser.add_argument("--environment-path", default=str(DEFAULT_ENVIRONMENT_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_RUN_OUTPUT_DIR))
    parser.add_argument(
        "--report-output-dir",
        default=str(DEFAULT_RELEASE_OUTPUT_DIR),
    )
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args(argv)

    try:
        manifest = ReleaseSuiteManifest(
            version="release-v1",
            train_paths=_json_paths(args.train_dir),
            regression_paths=_json_paths(args.regression_dir),
            holdout_paths=_json_paths(args.holdout_dir),
            regression_repeat_count=args.regression_repeat_count,
            holdout_repeat_count=args.holdout_repeat_count,
        )
        config = ReleaseGateConfig(
            baseline_candidate_id=args.baseline_candidate_id,
            release_candidate_id=args.candidate_id,
            manifest=manifest,
            max_total_rollouts=args.max_total_rollouts,
            environment_path=args.environment_path,
            run_output_dir=args.output_dir,
            persist_runs=not args.no_persist,
        )
        release_pool = candidate_pool
        if args.optimization_history:
            release_pool = load_candidate_pool_from_gepa_history(
                args.optimization_history,
                base_pool=candidate_pool,
            )
        result = run_release_gate(config, candidate_pool=release_pool)
        report_path = None
        if not args.no_persist:
            report_path = persist_release_result(result, args.report_output_dir)
        payload = result.to_dict()
        payload["report_path"] = str(report_path) if report_path else None
        print(json.dumps(payload, indent=2, sort_keys=True))
        return {"PROMOTED": 0, "INCONCLUSIVE": 1, "REJECTED": 2}[result.decision]
    except Exception as exc:
        print(
            json.dumps(
                {
                    "decision": "INCONCLUSIVE",
                    "reason": "release_preflight_error",
                    "detail": str(exc),
                    "error_type": type(exc).__name__,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


def _run_suite(
    candidate_id: str,
    suite: ScenarioSuiteSpec,
    config: ReleaseGateConfig,
    candidate_pool: CandidatePool,
    suite_runner: CandidateSuiteRunner,
    clock: Clock,
) -> CandidateSuiteRun:
    return suite_runner(
        candidate_id,
        suite,
        candidate_pool=candidate_pool,
        environment_path=config.environment_path,
        output_dir=config.run_output_dir,
        persist=config.persist_runs,
        clock=clock,
    )


def _regression_rejection_reason(
    comparison: CandidateSuiteComparison,
) -> str | None:
    if comparison.safety_regressed_scenario_ids:
        return "regression_safety_regressed"
    if comparison.regressed_scenario_ids:
        return "regression_pass_rate_regressed"
    if any(delta.average_score_delta < 0 for delta in comparison.scenario_deltas):
        return "regression_score_regressed"
    return None


def _absolute_rejection_reason(
    stage: str,
    suite: CandidateSuiteRun,
    min_pass_rate: float,
    thresholds: ReleaseThresholds,
) -> str | None:
    assert suite.matrix is not None
    summary = suite.matrix.candidate_score(suite.candidate_id)
    if summary.safety_failure_count > thresholds.max_safety_failures:
        return f"{stage}_safety_failures"
    if thresholds.require_all_eligible and not summary.eligible_for_selection:
        return f"{stage}_ineligible"
    if any(
        cell.pass_rate < min_pass_rate
        for cell in suite.matrix.cells
        if cell.candidate_id == suite.candidate_id
    ):
        return f"{stage}_pass_rate_below_threshold"
    return None


def _assert_suite_coverage(suite: CandidateSuiteRun) -> None:
    assert suite.matrix is not None
    assert_complete_score_matrix(
        suite.matrix,
        expected_candidate_ids=[suite.candidate_id],
        expected_scenario_ids=suite.scenario_ids,
        expected_runs_per_cell=suite.repeat_count,
    )


def _result(
    release_id: str,
    started_at: datetime,
    config: ReleaseGateConfig,
    decision: str,
    reason: str,
    detail: str | None,
    baseline_suite: CandidateSuiteRun | None,
    candidate_suite: CandidateSuiteRun | None,
    holdout_suite: CandidateSuiteRun | None,
    comparison: CandidateSuiteComparison | None,
    clock: Clock,
) -> ReleaseGateResult:
    return ReleaseGateResult(
        release_id=release_id,
        started_at=started_at,
        completed_at=clock(),
        config=config,
        decision=decision,
        reason=reason,
        detail=detail,
        baseline_regression_run_ids=_run_ids(baseline_suite),
        candidate_regression_run_ids=_run_ids(candidate_suite),
        holdout_run_ids=_run_ids(holdout_suite),
        baseline_regression_summary=_summary(baseline_suite),
        candidate_regression_summary=_summary(candidate_suite),
        holdout_summary=_summary(holdout_suite),
        regression_comparison=comparison,
    )


def _run_ids(suite: CandidateSuiteRun | None) -> tuple[str, ...]:
    if suite is None:
        return ()
    return tuple(sorted(record.run_id for record in suite.records))


def _summary(suite: CandidateSuiteRun | None) -> dict[str, Any] | None:
    if suite is None or suite.matrix is None:
        return None
    return suite.matrix.candidate_score(suite.candidate_id).to_dict()


def _suite_detail(suite: CandidateSuiteRun) -> str:
    if suite.errors:
        return "; ".join(
            f"{error.scenario_id}/{error.attempt_number}: "
            f"{error.error_type}: {error.message}"
            for error in suite.errors
        )
    return (
        f"Suite incomplete: expected={suite.expected_run_count}, "
        f"actual={len(suite.records)}."
    )


def _json_paths(directory: Path | str) -> tuple[Path, ...]:
    return tuple(sorted(Path(directory).glob("*.json")))


def _filename_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._")
    if not token:
        raise ValueError("Release ID cannot be converted to a filename.")
    return token


def _candidate_from_dict(value: Any) -> Candidate:
    expected = {
        "candidate_id",
        "agent_name",
        "agent_version",
        "parent_id",
        "generation",
        "kind",
        "description",
        "payload",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("GEPA history child candidate has an invalid schema.")
    string_fields = (
        "candidate_id",
        "agent_name",
        "agent_version",
        "kind",
        "description",
    )
    if not all(isinstance(value[field], str) and value[field] for field in string_fields):
        raise ValueError("GEPA history child candidate has invalid strings.")
    if value["parent_id"] is not None and not isinstance(value["parent_id"], str):
        raise ValueError("GEPA history child parent_id must be a string or null.")
    if (
        not isinstance(value["generation"], int)
        or isinstance(value["generation"], bool)
        or value["generation"] < 0
    ):
        raise ValueError("GEPA history child generation must be non-negative.")
    if not isinstance(value["payload"], dict):
        raise ValueError("GEPA history child payload must be an object.")
    return Candidate(
        candidate_id=value["candidate_id"],
        agent_name=value["agent_name"],
        agent_version=value["agent_version"],
        parent_id=value["parent_id"],
        generation=value["generation"],
        kind=value["kind"],
        description=value["description"],
        payload=dict(value["payload"]),
    )


def _positive_int(value: Any, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be a positive integer.")


def _rate(value: Any, label: str) -> None:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"{label} must be between 0 and 1.")


def _nonempty(value: Any, label: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise ValueError(f"{label} must be a non-empty string.")
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
