from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.optimization.candidates import (  # noqa: E402
    DEFAULT_CANDIDATE_POOL,
    Candidate,
    CandidatePool,
)
from agent_reliability_lab.optimization.comparison import (  # noqa: E402
    compare_candidate_suites,
)
from agent_reliability_lab.optimization.gepa import (  # noqa: E402
    GEPAConfig,
    decide_candidate_acceptance,
    main,
    persist_gepa_result,
    run_gepa_optimization,
)
from agent_reliability_lab.optimization.scoring import build_score_matrix  # noqa: E402
from agent_reliability_lab.evaluation import FATAL_FAILURE_TAGS  # noqa: E402
from agent_reliability_lab.runs import (  # noqa: E402
    CandidateSuiteRun,
    RunRecord,
    ScenarioSuiteSpec,
)
from agent_reliability_lab.scenarios import DEFAULT_SCENARIO_PATH  # noqa: E402


FIXED_NOW = datetime(2026, 7, 10, 10, 0, 0, tzinfo=timezone.utc)
PARENT_ID = "cand_openai_degraded_v1"
TEST_SUITE = ScenarioSuiteSpec(
    name="training",
    scenario_paths=(DEFAULT_SCENARIO_PATH,),
)


class QueueReflectionClient:
    def __init__(self, instructions: list[str]):
        self.instructions = list(instructions)
        self.calls = 0
        self.bundles = []

    def reflect(self, bundle):
        self.calls += 1
        self.bundles.append(bundle)
        if not self.instructions:
            raise AssertionError("reflection queue is empty")
        instruction = self.instructions.pop(0)
        return json.dumps(
            {
                "analysis": f"Improve generation {self.calls}.",
                "system_instruction": instruction,
            }
        )


class ScoreByInstructionSuiteRunner:
    def __init__(self, outcomes: dict[str, tuple[bool, float, list[str]]]):
        self.outcomes = outcomes
        self.calls: list[str] = []

    def __call__(self, candidate_id, suite, **kwargs):
        pool = kwargs["candidate_pool"]
        candidate = pool.require(candidate_id)
        instruction = candidate.payload["system_instruction"]
        passed, score, tags = self.outcomes[instruction]
        self.calls.append(candidate_id)
        return _suite_result(
            candidate,
            passed=passed,
            score=score,
            tags=tags,
            candidate_pool=pool,
        )


class GEPAAcceptanceTests(unittest.TestCase):
    def test_accepts_only_non_regressing_measurable_improvement(self) -> None:
        accepted = _comparison(
            parent=(False, 0.4, []),
            child=(False, 0.7, []),
        )
        unchanged = _comparison(
            parent=(False, 0.4, []),
            child=(False, 0.4, []),
        )

        self.assertTrue(decide_candidate_acceptance(accepted).accepted)
        self.assertEqual(
            decide_candidate_acceptance(accepted).reason,
            "accepted_improvement",
        )
        self.assertFalse(decide_candidate_acceptance(unchanged).accepted)
        self.assertEqual(
            decide_candidate_acceptance(unchanged).reason,
            "no_improvement",
        )

    def test_rejects_pass_score_and_safety_regressions(self) -> None:
        cases = [
            (
                _comparison(parent=(True, 1.0, []), child=(False, 0.9, [])),
                "pass_regression",
            ),
            (
                _comparison(parent=(False, 0.8, []), child=(False, 0.7, [])),
                "score_regression",
            ),
            (
                _comparison(
                    parent=(False, 0.4, []),
                    child=(False, 0.7, ["policy_violation"]),
                ),
                "safety_regression",
            ),
        ]

        for comparison, reason in cases:
            with self.subTest(reason=reason):
                decision = decide_candidate_acceptance(comparison)
                self.assertFalse(decision.accepted)
                self.assertEqual(decision.reason, reason)

    def test_rejects_fatal_eligibility_regression_before_score(self) -> None:
        comparison = _comparison(
            parent=(False, 0.8, ["poor_final_response"]),
            child=(False, 0.9, ["missing_evidence"]),
        )

        decision = decide_candidate_acceptance(comparison)

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "fatal_regression")

    def test_tolerates_score_regression_up_to_point_zero_five(self) -> None:
        tolerated = _comparison(
            parent=(False, 0.8, ["policy_violation"]),
            child=(False, 0.75, ["poor_final_response"]),
        )
        beyond_tolerance = _comparison(
            parent=(False, 0.8, ["policy_violation"]),
            child=(False, 0.749, ["poor_final_response"]),
        )

        self.assertTrue(decide_candidate_acceptance(tolerated).accepted)
        rejected = decide_candidate_acceptance(beyond_tolerance)
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.reason, "score_regression")


class GEPADriverTests(unittest.TestCase):
    def test_config_rejects_invalid_bounds(self) -> None:
        for kwargs in (
            {"initial_candidate_id": "", "max_generations": 1},
            {"initial_candidate_id": PARENT_ID, "max_generations": 0},
            {"initial_candidate_id": PARENT_ID, "max_generations": True},
            {"initial_candidate_id": PARENT_ID, "max_mutation_attempts": 0},
            {"initial_candidate_id": PARENT_ID, "max_mutation_attempts": True},
            {"initial_candidate_id": PARENT_ID, "children_per_generation": 0},
            {"initial_candidate_id": PARENT_ID, "children_per_generation": True},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    GEPAConfig(suite=TEST_SUITE, **kwargs)

    def test_driver_accepts_children_and_reuses_child_suite_as_next_parent(self) -> None:
        parent_instruction = _parent().payload["system_instruction"]
        reflection = QueueReflectionClient(
            ["Better instruction one.", "Perfect instruction two."]
        )
        suite_runner = ScoreByInstructionSuiteRunner(
            {
                parent_instruction: (False, 0.4, ["poor_final_response"]),
                "Better instruction one.": (
                    False,
                    0.7,
                    ["poor_final_response"],
                ),
                "Perfect instruction two.": (True, 1.0, []),
            }
        )
        mutation_ids = iter(("mutation_one", "mutation_two"))

        result = run_gepa_optimization(
            GEPAConfig(
                initial_candidate_id=PARENT_ID,
                suite=TEST_SUITE,
                max_generations=3,
                persist_runs=False,
            ),
            reflection_client=reflection,
            suite_runner=suite_runner,
            mutation_id_factory=lambda: next(mutation_ids),
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.stop_reason, "perfect_child")
        self.assertEqual(len(result.generations), 2)
        self.assertTrue(result.generations[0].decision.accepted)
        self.assertTrue(result.generations[1].decision.accepted)
        first_child_id = result.generations[0].child_candidate_id
        self.assertEqual(result.generations[1].parent_candidate_id, first_child_id)
        self.assertEqual(result.final_candidate_id, result.generations[1].child_candidate_id)
        self.assertEqual(len(suite_runner.calls), 3)
        self.assertEqual(suite_runner.calls.count(first_child_id), 1)
        self.assertEqual(reflection.calls, 2)

    def test_driver_stops_before_reflection_when_parent_is_perfect(self) -> None:
        instruction = _parent().payload["system_instruction"]
        suite_runner = ScoreByInstructionSuiteRunner(
            {instruction: (True, 1.0, [])}
        )
        reflection = QueueReflectionClient([])

        result = run_gepa_optimization(
            GEPAConfig(PARENT_ID, TEST_SUITE, persist_runs=False),
            reflection_client=reflection,
            suite_runner=suite_runner,
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.stop_reason, "perfect_parent")
        self.assertEqual(result.final_candidate_id, PARENT_ID)
        self.assertEqual(result.generations, ())
        self.assertEqual(reflection.calls, 0)

    def test_driver_stops_on_incomplete_parent_suite(self) -> None:
        def incomplete_runner(candidate_id, suite, **kwargs):
            return CandidateSuiteRun(
                suite_name=suite.name,
                candidate_id=candidate_id,
                scenario_ids=("scenario_a",),
                repeat_count=suite.repeat_count,
                expected_run_count=1,
                records=(),
                errors=(),
                matrix=None,
            )

        result = run_gepa_optimization(
            GEPAConfig(PARENT_ID, TEST_SUITE, persist_runs=False),
            reflection_client=QueueReflectionClient([]),
            suite_runner=incomplete_runner,
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.stop_reason, "parent_suite_incomplete")
        self.assertEqual(result.generations, ())

    def test_invalid_mutation_stops_without_running_child(self) -> None:
        parent_instruction = _parent().payload["system_instruction"]
        suite_runner = ScoreByInstructionSuiteRunner(
            {parent_instruction: (False, 0.4, ["poor_final_response"])}
        )

        result = run_gepa_optimization(
            GEPAConfig(
                PARENT_ID,
                TEST_SUITE,
                max_mutation_attempts=1,
                persist_runs=False,
            ),
            reflection_client=QueueReflectionClient([parent_instruction]),
            suite_runner=suite_runner,
            mutation_id_factory=lambda: "mutation_fixed",
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.stop_reason, "mutation_failed")
        self.assertEqual(len(result.generations), 1)
        self.assertEqual(
            result.generations[0].mutation.error.error_type,
            "unchanged_instruction",
        )
        self.assertIsNone(result.generations[0].child_candidate_id)
        self.assertEqual(len(suite_runner.calls), 1)

    def test_driver_retries_one_invalid_mutation_with_audited_feedback(self) -> None:
        parent_instruction = _parent().payload["system_instruction"]
        reflection = QueueReflectionClient(
            [parent_instruction, "Corrected instruction."]
        )
        suite_runner = ScoreByInstructionSuiteRunner(
            {
                parent_instruction: (False, 0.4, ["poor_final_response"]),
                "Corrected instruction.": (False, 0.7, ["poor_final_response"]),
            }
        )
        mutation_ids = iter(("mutation_invalid", "mutation_corrected"))

        result = run_gepa_optimization(
            GEPAConfig(
                PARENT_ID,
                TEST_SUITE,
                max_generations=1,
                max_mutation_attempts=2,
                persist_runs=False,
            ),
            reflection_client=reflection,
            suite_runner=suite_runner,
            mutation_id_factory=lambda: next(mutation_ids),
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        generation = result.generations[0]
        self.assertEqual(result.stop_reason, "generation_limit_reached")
        self.assertTrue(generation.decision.accepted)
        self.assertEqual(len(generation.mutation_attempts), 2)
        self.assertEqual(
            generation.mutation_attempts[0].error.error_type,
            "unchanged_instruction",
        )
        self.assertTrue(generation.mutation_attempts[1].succeeded)
        self.assertIs(generation.mutation, generation.mutation_attempts[-1])
        self.assertIn(
            "unchanged_instruction",
            reflection.bundles[1].revision_feedback,
        )
        self.assertEqual(len(suite_runner.calls), 2)
        serialized = generation.to_dict()
        self.assertEqual(len(serialized["mutation_attempts"]), 2)

    def test_driver_does_not_retry_reflection_transport_failure(self) -> None:
        parent_instruction = _parent().payload["system_instruction"]
        reflection = QueueReflectionClient([])
        suite_runner = ScoreByInstructionSuiteRunner(
            {parent_instruction: (False, 0.4, ["poor_final_response"])}
        )

        result = run_gepa_optimization(
            GEPAConfig(PARENT_ID, TEST_SUITE, persist_runs=False),
            reflection_client=reflection,
            suite_runner=suite_runner,
            mutation_id_factory=lambda: "mutation_fixed",
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.stop_reason, "mutation_failed")
        self.assertEqual(reflection.calls, 1)
        self.assertEqual(len(result.generations[0].mutation_attempts), 1)
        self.assertEqual(
            result.generations[0].mutation.error.error_type,
            "reflection_error",
        )

    def test_rejected_child_is_recorded_and_stops(self) -> None:
        parent_instruction = _parent().payload["system_instruction"]
        suite_runner = ScoreByInstructionSuiteRunner(
            {
                parent_instruction: (False, 0.7, ["poor_final_response"]),
                "Worse instruction.": (False, 0.5, ["poor_final_response"]),
            }
        )

        result = run_gepa_optimization(
            GEPAConfig(PARENT_ID, TEST_SUITE, persist_runs=False),
            reflection_client=QueueReflectionClient(["Worse instruction."]),
            suite_runner=suite_runner,
            mutation_id_factory=lambda: "mutation_fixed",
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.stop_reason, "child_rejected")
        self.assertEqual(result.final_candidate_id, PARENT_ID)
        self.assertEqual(result.generations[0].decision.reason, "score_regression")

    def test_driver_evaluates_second_child_after_first_is_rejected(self) -> None:
        parent_instruction = _parent().payload["system_instruction"]
        reflection = QueueReflectionClient(
            ["Worse instruction.", "Better instruction."]
        )
        suite_runner = ScoreByInstructionSuiteRunner(
            {
                parent_instruction: (False, 0.7, ["poor_final_response"]),
                "Worse instruction.": (False, 0.5, ["poor_final_response"]),
                "Better instruction.": (False, 0.9, ["poor_final_response"]),
            }
        )
        mutation_ids = iter(("mutation_worse", "mutation_better"))

        result = run_gepa_optimization(
            GEPAConfig(
                PARENT_ID,
                TEST_SUITE,
                children_per_generation=2,
                persist_runs=False,
            ),
            reflection_client=reflection,
            suite_runner=suite_runner,
            mutation_id_factory=lambda: next(mutation_ids),
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        generation = result.generations[0]
        self.assertEqual(result.stop_reason, "generation_limit_reached")
        self.assertEqual(reflection.calls, 2)
        self.assertEqual(len(suite_runner.calls), 3)
        self.assertEqual(len(generation.child_trials), 2)
        self.assertFalse(generation.child_trials[0].decision.accepted)
        self.assertTrue(generation.child_trials[1].decision.accepted)
        self.assertEqual(
            generation.child_candidate_id,
            generation.child_trials[1].child_candidate_id,
        )
        self.assertTrue(generation.decision.accepted)
        self.assertIn("score_regression", reflection.bundles[1].revision_feedback)

    def test_driver_exhausts_all_children_when_all_are_rejected(self) -> None:
        parent_instruction = _parent().payload["system_instruction"]
        reflection = QueueReflectionClient(
            ["Worst instruction.", "Less bad instruction."]
        )
        suite_runner = ScoreByInstructionSuiteRunner(
            {
                parent_instruction: (False, 0.8, ["poor_final_response"]),
                "Worst instruction.": (False, 0.5, ["poor_final_response"]),
                "Less bad instruction.": (
                    False,
                    0.7,
                    ["poor_final_response"],
                ),
            }
        )
        mutation_ids = iter(("mutation_worst", "mutation_less_bad"))

        result = run_gepa_optimization(
            GEPAConfig(
                PARENT_ID,
                TEST_SUITE,
                children_per_generation=2,
                persist_runs=False,
            ),
            reflection_client=reflection,
            suite_runner=suite_runner,
            mutation_id_factory=lambda: next(mutation_ids),
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        generation = result.generations[0]
        self.assertEqual(result.stop_reason, "child_rejected")
        self.assertEqual(result.final_candidate_id, PARENT_ID)
        self.assertEqual(reflection.calls, 2)
        self.assertEqual(len(suite_runner.calls), 3)
        self.assertEqual(len(generation.child_trials), 2)
        self.assertTrue(
            all(not trial.decision.accepted for trial in generation.child_trials)
        )
        self.assertEqual(
            generation.child_candidate_id,
            generation.child_trials[1].child_candidate_id,
        )
        serialized = generation.to_dict()
        self.assertEqual(len(serialized["child_trials"]), 2)
        self.assertEqual(
            serialized["child_candidate_id"],
            serialized["child_trials"][1]["child_candidate_id"],
        )

    def test_driver_selects_best_acceptable_child_deterministically(self) -> None:
        parent_instruction = _parent().payload["system_instruction"]
        suite_runner = ScoreByInstructionSuiteRunner(
            {
                parent_instruction: (False, 0.4, ["poor_final_response"]),
                "Good instruction.": (False, 0.7, ["poor_final_response"]),
                "Best instruction.": (False, 0.9, ["poor_final_response"]),
            }
        )
        mutation_ids = iter(("mutation_good", "mutation_best"))

        result = run_gepa_optimization(
            GEPAConfig(
                PARENT_ID,
                TEST_SUITE,
                children_per_generation=2,
                persist_runs=False,
            ),
            reflection_client=QueueReflectionClient(
                ["Good instruction.", "Best instruction."]
            ),
            suite_runner=suite_runner,
            mutation_id_factory=lambda: next(mutation_ids),
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        generation = result.generations[0]
        self.assertTrue(generation.decision.accepted)
        self.assertEqual(
            generation.child_candidate_id,
            generation.child_trials[1].child_candidate_id,
        )

    def test_generation_limit_is_enforced(self) -> None:
        parent_instruction = _parent().payload["system_instruction"]
        suite_runner = ScoreByInstructionSuiteRunner(
            {
                parent_instruction: (False, 0.4, ["poor_final_response"]),
                "Better instruction.": (False, 0.7, ["poor_final_response"]),
            }
        )

        result = run_gepa_optimization(
            GEPAConfig(
                PARENT_ID,
                TEST_SUITE,
                max_generations=1,
                persist_runs=False,
            ),
            reflection_client=QueueReflectionClient(["Better instruction."]),
            suite_runner=suite_runner,
            mutation_id_factory=lambda: "mutation_fixed",
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.stop_reason, "generation_limit_reached")
        self.assertEqual(len(result.generations), 1)
        self.assertTrue(result.generations[0].decision.accepted)

    def test_history_persistence_is_exclusive(self) -> None:
        instruction = _parent().payload["system_instruction"]
        result = run_gepa_optimization(
            GEPAConfig(PARENT_ID, TEST_SUITE, persist_runs=False),
            reflection_client=QueueReflectionClient([]),
            suite_runner=ScoreByInstructionSuiteRunner(
                {instruction: (True, 1.0, [])}
            ),
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = persist_gepa_result(result, temp_dir)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["optimization_id"], "optimization_fixed")
            with self.assertRaises(FileExistsError):
                persist_gepa_result(result, temp_dir)

    def test_cli_prints_compact_result_and_skips_history_when_requested(self) -> None:
        instruction = _parent().payload["system_instruction"]
        result = run_gepa_optimization(
            GEPAConfig(PARENT_ID, TEST_SUITE, persist_runs=False),
            reflection_client=QueueReflectionClient([]),
            suite_runner=ScoreByInstructionSuiteRunner(
                {instruction: (True, 1.0, [])}
            ),
            optimization_id_factory=lambda: "optimization_fixed",
            clock=lambda: FIXED_NOW,
        )
        stdout = io.StringIO()

        with patch(
            "agent_reliability_lab.optimization.gepa.run_gepa_optimization",
            return_value=result,
        ) as run_optimizer:
            with patch(
                "agent_reliability_lab.optimization.gepa.OpenAIReflectionClient"
            ):
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "--candidate-id",
                            PARENT_ID,
                            "--scenario-dir",
                            str(DEFAULT_SCENARIO_PATH.parent),
                            "--max-generations",
                            "2",
                            "--max-mutation-attempts",
                            "3",
                            "--children-per-generation",
                            "2",
                            "--no-persist",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["optimization_id"], "optimization_fixed")
        self.assertEqual(payload["stop_reason"], "perfect_parent")
        self.assertIsNone(payload["history_path"])
        self.assertFalse(run_optimizer.call_args.args[0].persist_runs)
        self.assertEqual(run_optimizer.call_args.args[0].max_mutation_attempts, 3)
        self.assertEqual(run_optimizer.call_args.args[0].children_per_generation, 2)


def _parent() -> Candidate:
    return DEFAULT_CANDIDATE_POOL.require(PARENT_ID)


def _comparison(
    *,
    parent: tuple[bool, float, list[str]],
    child: tuple[bool, float, list[str]],
):
    parent_candidate = _parent()
    child_candidate = Candidate(
        candidate_id="cand_child",
        agent_name=parent_candidate.agent_name,
        agent_version="openai-child-v1",
        parent_id=parent_candidate.candidate_id,
        generation=1,
        kind="openai_policy",
        description="Child.",
        payload={"system_instruction": "Child instruction."},
    )
    return compare_candidate_suites(
        _suite_result(
            parent_candidate,
            passed=parent[0],
            score=parent[1],
            tags=parent[2],
        ),
        _suite_result(
            child_candidate,
            passed=child[0],
            score=child[1],
            tags=child[2],
        ),
    )


def _suite_result(
    candidate: Candidate,
    *,
    passed: bool,
    score: float,
    tags: list[str],
    candidate_pool: CandidatePool | None = None,
) -> CandidateSuiteRun:
    record = _record(candidate, passed=passed, score=score, tags=tags)
    pool = candidate_pool or (
        CandidatePool((candidate,))
        if candidate.parent_id is None
        else CandidatePool((_parent(), candidate))
    )
    matrix = build_score_matrix([record], candidate_pool=pool)
    return CandidateSuiteRun(
        suite_name="training",
        candidate_id=candidate.candidate_id,
        scenario_ids=("scenario_a",),
        repeat_count=1,
        expected_run_count=1,
        records=(record,),
        errors=(),
        matrix=matrix,
    )


def _record(
    candidate: Candidate,
    *,
    passed: bool,
    score: float,
    tags: list[str],
) -> RunRecord:
    return RunRecord(
        run_id=f"run_{candidate.candidate_id}",
        scenario_id="scenario_a",
        scenario_version="1.0.0",
        environment_id="support_env_v1",
        agent_name=candidate.agent_name,
        agent_version=candidate.agent_version,
        started_at=FIXED_NOW,
        completed_at=FIXED_NOW,
        initial_state_hash="initial",
        final_state_hash="final",
        state_diff={},
        agent_visible_scenario={},
        tool_calls=[],
        final_response="response",
        evaluation={
            "passed": passed,
            "score": score,
            "failure_tags": list(tags),
            "fatal_tags": [tag for tag in tags if tag in FATAL_FAILURE_TAGS],
            "nonfatal_tags": [
                tag for tag in tags if tag not in FATAL_FAILURE_TAGS
            ],
            "eligible_for_selection": not any(
                tag in FATAL_FAILURE_TAGS for tag in tags
            ),
            "checks": [],
            "notes": [],
            "feedback_text": "deterministic feedback",
            "trace_excerpt": [],
        },
        agent_visible_evaluation={"passed": passed, "score": score},
        candidate_id=candidate.candidate_id,
        parent_candidate_id=candidate.parent_id,
        candidate_generation=candidate.generation,
        candidate_kind=candidate.kind,
    )


if __name__ == "__main__":
    unittest.main()
