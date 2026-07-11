"""Bounded GEPA reflection, evaluation, and acceptance driver."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable, Protocol
from uuid import uuid4

from agent_reliability_lab.agents.openai_runner import DEFAULT_OPENAI_MODEL
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
from agent_reliability_lab.optimization.reflection import (
    MutationIDFactory,
    MutationResult,
    OpenAIReflectionClient,
    ReflectionClient,
    build_reflection_bundle,
    reflect_and_create_child,
)
from agent_reliability_lab.runs.recorder import (
    DEFAULT_RUN_OUTPUT_DIR,
    _load_dotenv,
)
from agent_reliability_lab.runs.suite import (
    CandidateSuiteRun,
    ScenarioSuiteSpec,
    run_candidate_suite,
)
from agent_reliability_lab.scenarios import DEFAULT_SCENARIO_DIR


DEFAULT_GEPA_OUTPUT_DIR = Path(".gepa-runs")
Clock = Callable[[], datetime]
OptimizationIDFactory = Callable[[], str]


class CandidateSuiteRunner(Protocol):
    def __call__(
        self,
        candidate_id: str,
        suite: ScenarioSuiteSpec,
        **kwargs: Any,
    ) -> CandidateSuiteRun: ...


@dataclass(frozen=True)
class GEPAConfig:
    initial_candidate_id: str
    suite: ScenarioSuiteSpec
    max_generations: int = 1
    environment_path: Path | str = DEFAULT_ENVIRONMENT_PATH
    run_output_dir: Path | str = DEFAULT_RUN_OUTPUT_DIR
    persist_runs: bool = True

    def __post_init__(self) -> None:
        candidate_id = (
            self.initial_candidate_id.strip()
            if isinstance(self.initial_candidate_id, str)
            else ""
        )
        if not candidate_id:
            raise ValueError("Initial candidate ID must be non-empty.")
        if (
            not isinstance(self.max_generations, int)
            or isinstance(self.max_generations, bool)
            or self.max_generations < 1
        ):
            raise ValueError("max_generations must be a positive integer.")
        if not isinstance(self.persist_runs, bool):
            raise ValueError("persist_runs must be boolean.")
        object.__setattr__(self, "initial_candidate_id", candidate_id)
        object.__setattr__(self, "environment_path", Path(self.environment_path))
        object.__setattr__(self, "run_output_dir", Path(self.run_output_dir))

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_candidate_id": self.initial_candidate_id,
            "suite": {
                "name": self.suite.name,
                "scenario_paths": [str(path) for path in self.suite.scenario_paths],
                "repeat_count": self.suite.repeat_count,
            },
            "max_generations": self.max_generations,
            "environment_path": str(self.environment_path),
            "run_output_dir": str(self.run_output_dir),
            "persist_runs": self.persist_runs,
        }


@dataclass(frozen=True)
class AcceptanceDecision:
    accepted: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OptimizationError:
    error_type: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class GEPAGeneration:
    generation_number: int
    parent_candidate_id: str
    parent_run_ids: tuple[str, ...]
    mutation: MutationResult | None
    child_candidate_id: str | None
    child_run_ids: tuple[str, ...]
    comparison: CandidateSuiteComparison | None
    decision: AcceptanceDecision | None
    error: OptimizationError | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation_number": self.generation_number,
            "parent_candidate_id": self.parent_candidate_id,
            "parent_run_ids": list(self.parent_run_ids),
            "mutation": self.mutation.to_dict() if self.mutation else None,
            "child_candidate_id": self.child_candidate_id,
            "child_run_ids": list(self.child_run_ids),
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "decision": self.decision.to_dict() if self.decision else None,
            "error": self.error.to_dict() if self.error else None,
        }


@dataclass(frozen=True)
class GEPAOptimizationResult:
    optimization_id: str
    started_at: datetime
    completed_at: datetime
    config: GEPAConfig
    initial_candidate_id: str
    final_candidate_id: str
    initial_parent_run_ids: tuple[str, ...]
    generations: tuple[GEPAGeneration, ...]
    stop_reason: str
    stop_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "optimization_id": self.optimization_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "config": self.config.to_dict(),
            "initial_candidate_id": self.initial_candidate_id,
            "final_candidate_id": self.final_candidate_id,
            "initial_parent_run_ids": list(self.initial_parent_run_ids),
            "generation_count": len(self.generations),
            "generations": [item.to_dict() for item in self.generations],
            "stop_reason": self.stop_reason,
            "stop_detail": self.stop_detail,
        }


def decide_candidate_acceptance(
    comparison: CandidateSuiteComparison,
) -> AcceptanceDecision:
    if comparison.safety_regressed_scenario_ids:
        return AcceptanceDecision(False, "safety_regression")
    if comparison.regressed_scenario_ids:
        return AcceptanceDecision(False, "pass_regression")
    if any(delta.average_score_delta < 0 for delta in comparison.scenario_deltas):
        return AcceptanceDecision(False, "score_regression")
    if not comparison.improved_scenario_ids:
        return AcceptanceDecision(False, "no_improvement")
    return AcceptanceDecision(True, "accepted_improvement")


def run_gepa_optimization(
    config: GEPAConfig,
    *,
    reflection_client: ReflectionClient,
    candidate_pool: CandidatePool = DEFAULT_CANDIDATE_POOL,
    suite_runner: CandidateSuiteRunner = run_candidate_suite,
    mutation_id_factory: MutationIDFactory = lambda: f"mutation_{uuid4().hex}",
    optimization_id_factory: OptimizationIDFactory = lambda: f"gepa_{uuid4().hex}",
    clock: Clock = lambda: datetime.now(timezone.utc),
) -> GEPAOptimizationResult:
    started_at = clock()
    optimization_id = _required_identifier(
        optimization_id_factory(),
        "Optimization ID",
    )
    current_pool = candidate_pool
    current_parent = current_pool.require(config.initial_candidate_id)
    _assert_mutable_candidate(current_parent)
    generations: list[GEPAGeneration] = []

    try:
        parent_suite = _run_suite(
            current_parent.candidate_id,
            config,
            current_pool,
            suite_runner,
            clock,
        )
    except Exception as exc:
        return _finish(
            optimization_id,
            started_at,
            config,
            current_parent.candidate_id,
            (),
            generations,
            "parent_suite_error",
            str(exc),
            clock,
        )

    initial_parent_run_ids = _run_ids(parent_suite)
    if not parent_suite.complete:
        return _finish(
            optimization_id,
            started_at,
            config,
            current_parent.candidate_id,
            initial_parent_run_ids,
            generations,
            "parent_suite_incomplete",
            _suite_error_detail(parent_suite),
            clock,
        )
    if _suite_is_perfect(parent_suite):
        return _finish(
            optimization_id,
            started_at,
            config,
            current_parent.candidate_id,
            initial_parent_run_ids,
            generations,
            "perfect_parent",
            None,
            clock,
        )

    for generation_number in range(1, config.max_generations + 1):
        parent_run_ids = _run_ids(parent_suite)
        try:
            bundle = build_reflection_bundle(current_parent, parent_suite)
        except Exception as exc:
            generations.append(
                _failed_generation(
                    generation_number,
                    current_parent.candidate_id,
                    parent_run_ids,
                    "reflection_input_error",
                    str(exc),
                )
            )
            return _finish(
                optimization_id,
                started_at,
                config,
                current_parent.candidate_id,
                initial_parent_run_ids,
                generations,
                "reflection_input_error",
                str(exc),
                clock,
            )

        mutation = reflect_and_create_child(
            current_parent,
            bundle,
            reflection_client,
            mutation_id_factory=mutation_id_factory,
            clock=clock,
        )
        if not mutation.succeeded:
            generations.append(
                GEPAGeneration(
                    generation_number=generation_number,
                    parent_candidate_id=current_parent.candidate_id,
                    parent_run_ids=parent_run_ids,
                    mutation=mutation,
                    child_candidate_id=None,
                    child_run_ids=(),
                    comparison=None,
                    decision=None,
                )
            )
            return _finish(
                optimization_id,
                started_at,
                config,
                current_parent.candidate_id,
                initial_parent_run_ids,
                generations,
                "mutation_failed",
                mutation.error.message if mutation.error else None,
                clock,
            )

        assert mutation.child is not None
        child = mutation.child
        try:
            child_pool = current_pool.with_candidate(child)
        except Exception as exc:
            generations.append(
                GEPAGeneration(
                    generation_number=generation_number,
                    parent_candidate_id=current_parent.candidate_id,
                    parent_run_ids=parent_run_ids,
                    mutation=mutation,
                    child_candidate_id=child.candidate_id,
                    child_run_ids=(),
                    comparison=None,
                    decision=None,
                    error=OptimizationError("candidate_registration_error", str(exc)),
                )
            )
            return _finish(
                optimization_id,
                started_at,
                config,
                current_parent.candidate_id,
                initial_parent_run_ids,
                generations,
                "candidate_registration_error",
                str(exc),
                clock,
            )

        try:
            child_suite = _run_suite(
                child.candidate_id,
                config,
                child_pool,
                suite_runner,
                clock,
            )
        except Exception as exc:
            generations.append(
                GEPAGeneration(
                    generation_number=generation_number,
                    parent_candidate_id=current_parent.candidate_id,
                    parent_run_ids=parent_run_ids,
                    mutation=mutation,
                    child_candidate_id=child.candidate_id,
                    child_run_ids=(),
                    comparison=None,
                    decision=None,
                    error=OptimizationError("child_suite_error", str(exc)),
                )
            )
            return _finish(
                optimization_id,
                started_at,
                config,
                current_parent.candidate_id,
                initial_parent_run_ids,
                generations,
                "child_suite_error",
                str(exc),
                clock,
            )

        child_run_ids = _run_ids(child_suite)
        if not child_suite.complete:
            generations.append(
                GEPAGeneration(
                    generation_number=generation_number,
                    parent_candidate_id=current_parent.candidate_id,
                    parent_run_ids=parent_run_ids,
                    mutation=mutation,
                    child_candidate_id=child.candidate_id,
                    child_run_ids=child_run_ids,
                    comparison=None,
                    decision=None,
                    error=OptimizationError(
                        "child_suite_incomplete",
                        _suite_error_detail(child_suite),
                    ),
                )
            )
            return _finish(
                optimization_id,
                started_at,
                config,
                current_parent.candidate_id,
                initial_parent_run_ids,
                generations,
                "child_suite_incomplete",
                _suite_error_detail(child_suite),
                clock,
            )

        try:
            comparison = compare_candidate_suites(parent_suite, child_suite)
        except Exception as exc:
            generations.append(
                GEPAGeneration(
                    generation_number=generation_number,
                    parent_candidate_id=current_parent.candidate_id,
                    parent_run_ids=parent_run_ids,
                    mutation=mutation,
                    child_candidate_id=child.candidate_id,
                    child_run_ids=child_run_ids,
                    comparison=None,
                    decision=None,
                    error=OptimizationError("comparison_error", str(exc)),
                )
            )
            return _finish(
                optimization_id,
                started_at,
                config,
                current_parent.candidate_id,
                initial_parent_run_ids,
                generations,
                "comparison_error",
                str(exc),
                clock,
            )

        decision = decide_candidate_acceptance(comparison)
        generations.append(
            GEPAGeneration(
                generation_number=generation_number,
                parent_candidate_id=current_parent.candidate_id,
                parent_run_ids=parent_run_ids,
                mutation=mutation,
                child_candidate_id=child.candidate_id,
                child_run_ids=child_run_ids,
                comparison=comparison,
                decision=decision,
            )
        )
        if not decision.accepted:
            return _finish(
                optimization_id,
                started_at,
                config,
                current_parent.candidate_id,
                initial_parent_run_ids,
                generations,
                "child_rejected",
                decision.reason,
                clock,
            )

        current_pool = child_pool
        current_parent = child
        parent_suite = child_suite
        if _suite_is_perfect(child_suite):
            return _finish(
                optimization_id,
                started_at,
                config,
                current_parent.candidate_id,
                initial_parent_run_ids,
                generations,
                "perfect_child",
                None,
                clock,
            )

    return _finish(
        optimization_id,
        started_at,
        config,
        current_parent.candidate_id,
        initial_parent_run_ids,
        generations,
        "generation_limit_reached",
        None,
        clock,
    )


def persist_gepa_result(
    result: GEPAOptimizationResult,
    output_dir: Path | str = DEFAULT_GEPA_OUTPUT_DIR,
) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{_filename_token(result.optimization_id)}.json"
    path = directory / filename
    with path.open("x", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(
        description="Run a bounded GEPA prompt-optimization loop."
    )
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--scenario-dir", default=str(DEFAULT_SCENARIO_DIR))
    parser.add_argument("--repeat-count", type=int, default=1)
    parser.add_argument("--max-generations", type=int, default=1)
    parser.add_argument("--model", default=DEFAULT_OPENAI_MODEL)
    parser.add_argument("--environment-path", default=str(DEFAULT_ENVIRONMENT_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_RUN_OUTPUT_DIR))
    parser.add_argument(
        "--history-output-dir",
        default=str(DEFAULT_GEPA_OUTPUT_DIR),
    )
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args(argv)

    try:
        scenario_dir = Path(args.scenario_dir)
        suite = ScenarioSuiteSpec(
            name=scenario_dir.name or "training",
            scenario_paths=tuple(sorted(scenario_dir.glob("*.json"))),
            repeat_count=args.repeat_count,
        )
        config = GEPAConfig(
            initial_candidate_id=args.candidate_id,
            suite=suite,
            max_generations=args.max_generations,
            environment_path=args.environment_path,
            run_output_dir=args.output_dir,
            persist_runs=not args.no_persist,
        )
        result = run_gepa_optimization(
            config,
            reflection_client=OpenAIReflectionClient(model=args.model),
        )
        history_path = None
        if not args.no_persist:
            history_path = persist_gepa_result(result, args.history_output_dir)
        payload = result.to_dict()
        payload["history_path"] = str(history_path) if history_path else None
        print(json.dumps(payload, indent=2, sort_keys=True))
        normal_stops = {
            "perfect_parent",
            "perfect_child",
            "child_rejected",
            "generation_limit_reached",
        }
        return 0 if result.stop_reason in normal_stops else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "complete": False,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


def _run_suite(
    candidate_id: str,
    config: GEPAConfig,
    candidate_pool: CandidatePool,
    suite_runner: CandidateSuiteRunner,
    clock: Clock,
) -> CandidateSuiteRun:
    return suite_runner(
        candidate_id,
        config.suite,
        candidate_pool=candidate_pool,
        environment_path=config.environment_path,
        output_dir=config.run_output_dir,
        persist=config.persist_runs,
        clock=clock,
    )


def _suite_is_perfect(suite: CandidateSuiteRun) -> bool:
    if not suite.complete or suite.matrix is None:
        return False
    summary = suite.matrix.candidate_score(suite.candidate_id)
    return (
        summary.run_count > 0
        and summary.passed_count == summary.run_count
        and summary.safety_failure_count == 0
        and summary.eligible_for_selection
    )


def _run_ids(suite: CandidateSuiteRun) -> tuple[str, ...]:
    return tuple(sorted(record.run_id for record in suite.records))


def _suite_error_detail(suite: CandidateSuiteRun) -> str:
    if suite.errors:
        return "; ".join(
            f"{error.scenario_id}/{error.attempt_number}: "
            f"{error.error_type}: {error.message}"
            for error in suite.errors
        )
    return (
        f"Suite was incomplete: expected={suite.expected_run_count}, "
        f"actual={len(suite.records)}."
    )


def _assert_mutable_candidate(candidate: Candidate) -> None:
    instruction = candidate.payload.get("system_instruction")
    if (
        candidate.kind != "openai_policy"
        or not isinstance(instruction, str)
        or not instruction.strip()
    ):
        raise ValueError(
            "GEPA optimization requires an openai_policy candidate with a system_instruction."
        )


def _finish(
    optimization_id: str,
    started_at: datetime,
    config: GEPAConfig,
    final_candidate_id: str,
    initial_parent_run_ids: tuple[str, ...],
    generations: list[GEPAGeneration],
    stop_reason: str,
    stop_detail: str | None,
    clock: Clock,
) -> GEPAOptimizationResult:
    return GEPAOptimizationResult(
        optimization_id=optimization_id,
        started_at=started_at,
        completed_at=clock(),
        config=config,
        initial_candidate_id=config.initial_candidate_id,
        final_candidate_id=final_candidate_id,
        initial_parent_run_ids=initial_parent_run_ids,
        generations=tuple(generations),
        stop_reason=stop_reason,
        stop_detail=stop_detail,
    )


def _failed_generation(
    generation_number: int,
    parent_candidate_id: str,
    parent_run_ids: tuple[str, ...],
    error_type: str,
    message: str,
) -> GEPAGeneration:
    return GEPAGeneration(
        generation_number=generation_number,
        parent_candidate_id=parent_candidate_id,
        parent_run_ids=parent_run_ids,
        mutation=None,
        child_candidate_id=None,
        child_run_ids=(),
        comparison=None,
        decision=None,
        error=OptimizationError(error_type, message),
    )


def _required_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def _filename_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._")
    if not token:
        raise ValueError("Optimization ID cannot be converted to a filename.")
    return token


if __name__ == "__main__":
    raise SystemExit(main())
