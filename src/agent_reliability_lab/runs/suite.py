"""Repeated candidate-suite execution over the existing single-run path."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Protocol

from agent_reliability_lab.environment import (
    DEFAULT_ENVIRONMENT_PATH,
    EnvironmentStore,
)
from agent_reliability_lab.optimization.candidates import (
    DEFAULT_CANDIDATE_POOL,
    CandidatePool,
)
from agent_reliability_lab.optimization.scoring import (
    ScoreMatrix,
    assert_complete_score_matrix,
    build_score_matrix,
)
from agent_reliability_lab.runs.models import RunRecord
from agent_reliability_lab.runs.recorder import (
    DEFAULT_RUN_OUTPUT_DIR,
    _load_dotenv,
    run_candidate_scenario,
)
from agent_reliability_lab.scenarios import DEFAULT_SCENARIO_DIR, load_scenario


NON_COMPARABLE_AGENT_FAILURES = frozenset(
    {
        "api_error",
        "response_error",
        "response_incomplete",
        "response_not_completed",
        "missing_response_id",
    }
)

Clock = Callable[[], datetime]


class CandidateScenarioRunner(Protocol):
    def __call__(self, candidate_id: str, **kwargs: Any) -> RunRecord: ...


@dataclass(frozen=True)
class ScenarioSuiteSpec:
    name: str
    scenario_paths: tuple[Path, ...]
    repeat_count: int = 1

    def __post_init__(self) -> None:
        name = self.name.strip() if isinstance(self.name, str) else ""
        paths = tuple(Path(path) for path in self.scenario_paths)
        if not name:
            raise ValueError("Scenario suite name must be non-empty.")
        if not paths:
            raise ValueError("Scenario suite must contain at least one path.")
        if len(paths) != len(set(paths)):
            raise ValueError("Scenario suite paths must be unique.")
        if (
            not isinstance(self.repeat_count, int)
            or isinstance(self.repeat_count, bool)
            or self.repeat_count < 1
        ):
            raise ValueError("Scenario suite repeat_count must be a positive integer.")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "scenario_paths", paths)


@dataclass(frozen=True)
class SuiteRunError:
    scenario_id: str
    attempt_number: int
    error_type: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateSuiteRun:
    suite_name: str
    candidate_id: str
    scenario_ids: tuple[str, ...]
    repeat_count: int
    expected_run_count: int
    records: tuple[RunRecord, ...]
    errors: tuple[SuiteRunError, ...]
    matrix: ScoreMatrix | None

    @property
    def complete(self) -> bool:
        return (
            not self.errors
            and len(self.records) == self.expected_run_count
            and self.matrix is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "candidate_id": self.candidate_id,
            "scenario_ids": list(self.scenario_ids),
            "repeat_count": self.repeat_count,
            "expected_run_count": self.expected_run_count,
            "actual_run_count": len(self.records),
            "complete": self.complete,
            "run_ids": [record.run_id for record in self.records],
            "errors": [error.to_dict() for error in self.errors],
            "score_matrix": self.matrix.to_dict() if self.matrix is not None else None,
        }


def run_candidate_suite(
    candidate_id: str,
    suite: ScenarioSuiteSpec,
    *,
    candidate_pool: CandidatePool = DEFAULT_CANDIDATE_POOL,
    environment_path: Path | str = DEFAULT_ENVIRONMENT_PATH,
    output_dir: Path | str = DEFAULT_RUN_OUTPUT_DIR,
    persist: bool = True,
    clock: Clock | None = None,
    scenario_runner: CandidateScenarioRunner = run_candidate_scenario,
) -> CandidateSuiteRun:
    """Run a candidate over every configured scenario and repeat slot."""

    candidate_pool.require(candidate_id)
    scenarios = _validated_scenarios(suite, environment_path)
    scenario_ids = tuple(scenario_id for _, scenario_id in scenarios)
    expected_run_count = len(scenarios) * suite.repeat_count
    records: list[RunRecord] = []
    errors: list[SuiteRunError] = []

    for scenario_path, scenario_id in scenarios:
        for attempt_number in range(1, suite.repeat_count + 1):
            try:
                record = scenario_runner(
                    candidate_id,
                    scenario_path=scenario_path,
                    environment_path=environment_path,
                    output_dir=output_dir,
                    candidate_pool=candidate_pool,
                    clock=clock,
                    persist=persist,
                )
            except Exception as exc:
                errors.append(
                    SuiteRunError(
                        scenario_id=scenario_id,
                        attempt_number=attempt_number,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
                continue

            records.append(record)
            mismatch = _record_mismatch(record, candidate_id, scenario_id)
            if mismatch is not None:
                errors.append(
                    SuiteRunError(
                        scenario_id=scenario_id,
                        attempt_number=attempt_number,
                        error_type="record_mismatch",
                        message=mismatch,
                    )
                )
                continue
            if record.agent_failure_reason in NON_COMPARABLE_AGENT_FAILURES:
                errors.append(
                    SuiteRunError(
                        scenario_id=scenario_id,
                        attempt_number=attempt_number,
                        error_type="agent_failure",
                        message=(
                            "Non-comparable agent failure: "
                            f"{record.agent_failure_reason}"
                        ),
                    )
                )

    matrix = None
    if not errors and len(records) == expected_run_count:
        matrix = build_score_matrix(records, candidate_pool=candidate_pool)
        assert_complete_score_matrix(
            matrix,
            expected_candidate_ids=[candidate_id],
            expected_scenario_ids=scenario_ids,
            expected_runs_per_cell=suite.repeat_count,
        )

    return CandidateSuiteRun(
        suite_name=suite.name,
        candidate_id=candidate_id,
        scenario_ids=scenario_ids,
        repeat_count=suite.repeat_count,
        expected_run_count=expected_run_count,
        records=tuple(records),
        errors=tuple(errors),
        matrix=matrix,
    )


def _validated_scenarios(
    suite: ScenarioSuiteSpec,
    environment_path: Path | str,
) -> list[tuple[Path, str]]:
    state = EnvironmentStore.from_seed(environment_path).snapshot()
    scenarios = [
        (path, load_scenario(path, environment_state=state).metadata.scenario_id)
        for path in sorted(suite.scenario_paths)
    ]
    scenario_ids = [scenario_id for _, scenario_id in scenarios]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("Scenario suite scenario IDs must be unique.")
    return scenarios


def _record_mismatch(
    record: RunRecord,
    candidate_id: str,
    scenario_id: str,
) -> str | None:
    if record.candidate_id != candidate_id:
        return (
            "Suite runner returned candidate_id "
            f"{record.candidate_id!r}; expected {candidate_id!r}."
        )
    if record.scenario_id != scenario_id:
        return (
            "Suite runner returned scenario_id "
            f"{record.scenario_id!r}; expected {scenario_id!r}."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(
        description="Run one candidate over a repeated scenario suite."
    )
    parser.add_argument(
        "--candidate-id",
        required=True,
        help="Registered candidate ID to evaluate.",
    )
    parser.add_argument(
        "--scenario-dir",
        default=str(DEFAULT_SCENARIO_DIR),
        help="Directory containing scenario JSON fixtures.",
    )
    parser.add_argument(
        "--repeat-count",
        type=int,
        default=1,
        help="Number of independent rollouts per scenario.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_RUN_OUTPUT_DIR),
        help="Directory where individual run records are written.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Run and print the suite summary without writing run records.",
    )
    args = parser.parse_args(argv)

    scenario_dir = Path(args.scenario_dir)
    suite_name = scenario_dir.name or "scenario_suite"
    try:
        suite = ScenarioSuiteSpec(
            name=suite_name,
            scenario_paths=tuple(sorted(scenario_dir.glob("*.json"))),
            repeat_count=args.repeat_count,
        )
        result = run_candidate_suite(
            args.candidate_id,
            suite,
            output_dir=args.output_dir,
            persist=not args.no_persist,
        )
    except (OSError, KeyError, ValueError) as exc:
        print(
            json.dumps(
                _cli_error_summary(
                    suite_name=suite_name,
                    candidate_id=args.candidate_id,
                    repeat_count=args.repeat_count,
                    error=exc,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.complete else 1


def _cli_error_summary(
    *,
    suite_name: str,
    candidate_id: str,
    repeat_count: int,
    error: Exception,
) -> dict[str, Any]:
    return {
        "suite_name": suite_name,
        "candidate_id": candidate_id,
        "scenario_ids": [],
        "repeat_count": repeat_count,
        "expected_run_count": 0,
        "actual_run_count": 0,
        "complete": False,
        "run_ids": [],
        "errors": [
            SuiteRunError(
                scenario_id="<suite_preflight>",
                attempt_number=0,
                error_type=type(error).__name__,
                message=str(error),
            ).to_dict()
        ],
        "score_matrix": None,
    }


if __name__ == "__main__":
    raise SystemExit(main())
