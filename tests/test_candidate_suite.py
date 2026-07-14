from __future__ import annotations

from datetime import datetime, timezone
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.optimization import (  # noqa: E402
    BASELINE_CANDIDATE_ID,
    DEFAULT_CANDIDATE_POOL,
    build_score_matrix,
    compare_candidate_suites,
)
from agent_reliability_lab.evaluation import FATAL_FAILURE_TAGS  # noqa: E402
from agent_reliability_lab.runs import (  # noqa: E402
    CandidateSuiteRun,
    RunRecord,
    ScenarioSuiteSpec,
    run_candidate_suite,
)
from agent_reliability_lab.scenarios import (  # noqa: E402
    DEFAULT_SCENARIO_DIR,
    load_scenario,
)
import agent_reliability_lab.runs.suite as suite_module  # noqa: E402


FIXED_NOW = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)
SCENARIO_PATHS = tuple(sorted(DEFAULT_SCENARIO_DIR.glob("*.json")))


class CandidateSuiteTests(unittest.TestCase):
    def test_suite_spec_rejects_invalid_configuration(self) -> None:
        cases = [
            {"name": "", "scenario_paths": SCENARIO_PATHS, "repeat_count": 1},
            {"name": "suite", "scenario_paths": (), "repeat_count": 1},
            {
                "name": "suite",
                "scenario_paths": (SCENARIO_PATHS[0], SCENARIO_PATHS[0]),
                "repeat_count": 1,
            },
            {"name": "suite", "scenario_paths": SCENARIO_PATHS, "repeat_count": 0},
            {"name": "suite", "scenario_paths": SCENARIO_PATHS, "repeat_count": -1},
        ]

        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    ScenarioSuiteSpec(**values)

    def test_suite_runs_every_scenario_for_every_repeat(self) -> None:
        calls: list[str] = []

        def fake_runner(candidate_id: str, **kwargs) -> RunRecord:
            scenario_path = Path(kwargs["scenario_path"])
            scenario_id = load_scenario(scenario_path).metadata.scenario_id
            calls.append(scenario_path.name)
            return _synthetic_record(
                candidate_id=candidate_id,
                scenario_id=scenario_id,
                run_id=f"run_{len(calls)}",
            )

        result = run_candidate_suite(
            "cand_openai_degraded_v1",
            ScenarioSuiteSpec(
                name="training",
                scenario_paths=tuple(reversed(SCENARIO_PATHS)),
                repeat_count=2,
            ),
            persist=False,
            scenario_runner=fake_runner,
        )

        expected_calls = [
            path.name
            for path in SCENARIO_PATHS
            for _ in range(2)
        ]
        self.assertEqual(calls, expected_calls)
        self.assertEqual(result.expected_run_count, 8)
        self.assertEqual(len(result.records), 8)
        self.assertEqual(result.errors, ())
        self.assertTrue(result.complete)
        self.assertIsNotNone(result.matrix)
        self.assertEqual(len(result.matrix.cells), 4)

    def test_suite_reports_start_and_terminal_progress_for_each_rollout(self) -> None:
        messages: list[str] = []
        calls = 0

        def fake_runner(candidate_id: str, **kwargs) -> RunRecord:
            nonlocal calls
            calls += 1
            scenario = load_scenario(kwargs["scenario_path"])
            return _synthetic_record(
                candidate_id=candidate_id,
                scenario_id=scenario.metadata.scenario_id,
                run_id=f"run_{calls}",
                passed=calls == 1,
                score=1.0 if calls == 1 else 0.9,
            )

        run_candidate_suite(
            "cand_openai_degraded_v1",
            ScenarioSuiteSpec(
                name="training",
                scenario_paths=SCENARIO_PATHS[:2],
            ),
            persist=False,
            scenario_runner=fake_runner,
            progress_callback=messages.append,
        )

        self.assertEqual(
            messages,
            [
                "[1/2] starting scenario=support_login_lockout_v1 attempt=1/1",
                "[1/2] completed scenario=support_login_lockout_v1 "
                "attempt=1/1 passed=true score=1.0000",
                "[2/2] starting scenario=support_mfa_blocker_v1 attempt=1/1",
                "[2/2] completed scenario=support_mfa_blocker_v1 "
                "attempt=1/1 passed=false score=0.9000",
            ],
        )

    def test_suite_reports_rollout_exception_progress(self) -> None:
        messages: list[str] = []

        def fake_runner(candidate_id: str, **kwargs) -> RunRecord:
            raise RuntimeError("runner exploded")

        result = run_candidate_suite(
            "cand_openai_degraded_v1",
            ScenarioSuiteSpec(
                name="training",
                scenario_paths=SCENARIO_PATHS[:1],
            ),
            persist=False,
            scenario_runner=fake_runner,
            progress_callback=messages.append,
        )

        self.assertFalse(result.complete)
        self.assertEqual(
            messages,
            [
                "[1/1] starting scenario=support_login_lockout_v1 attempt=1/1",
                "[1/1] failed scenario=support_login_lockout_v1 "
                "attempt=1/1 error=RuntimeError",
            ],
        )

    def test_suite_continues_after_rollout_exception(self) -> None:
        calls: list[str] = []

        def fake_runner(candidate_id: str, **kwargs) -> RunRecord:
            scenario_path = Path(kwargs["scenario_path"])
            scenario = load_scenario(scenario_path)
            calls.append(scenario.metadata.scenario_id)
            if scenario_path.name == "mfa_blocker_v1.json" and calls.count(
                scenario.metadata.scenario_id
            ) == 1:
                raise RuntimeError("runner exploded")
            return _synthetic_record(
                candidate_id=candidate_id,
                scenario_id=scenario.metadata.scenario_id,
                run_id=f"run_{len(calls)}",
            )

        result = run_candidate_suite(
            "cand_openai_degraded_v1",
            ScenarioSuiteSpec(
                name="training",
                scenario_paths=SCENARIO_PATHS,
                repeat_count=2,
            ),
            persist=False,
            scenario_runner=fake_runner,
        )

        self.assertEqual(len(calls), 8)
        self.assertEqual(len(result.records), 7)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].scenario_id, "support_mfa_blocker_v1")
        self.assertEqual(result.errors[0].attempt_number, 1)
        self.assertEqual(result.errors[0].error_type, "RuntimeError")
        self.assertFalse(result.complete)
        self.assertIsNone(result.matrix)

    def test_non_comparable_agent_failure_blocks_matrix(self) -> None:
        calls = 0
        messages: list[str] = []

        def fake_runner(candidate_id: str, **kwargs) -> RunRecord:
            nonlocal calls
            calls += 1
            scenario = load_scenario(kwargs["scenario_path"])
            return _synthetic_record(
                candidate_id=candidate_id,
                scenario_id=scenario.metadata.scenario_id,
                run_id=f"run_{calls}",
                agent_failure_reason=("api_error" if calls == 1 else None),
            )

        result = run_candidate_suite(
            "cand_openai_degraded_v1",
            ScenarioSuiteSpec(
                name="training",
                scenario_paths=SCENARIO_PATHS,
            ),
            persist=False,
            scenario_runner=fake_runner,
            progress_callback=messages.append,
        )

        self.assertEqual(len(result.records), 4)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].error_type, "agent_failure")
        self.assertIn("api_error", result.errors[0].message)
        self.assertFalse(result.complete)
        self.assertIsNone(result.matrix)
        self.assertIn(
            "[1/4] failed scenario=support_login_lockout_v1 "
            "attempt=1/1 agent_failure=api_error",
            messages,
        )

    def test_suite_result_summary_is_compact_and_deterministic(self) -> None:
        result = CandidateSuiteRun(
            suite_name="training",
            candidate_id="cand_child",
            scenario_ids=("scenario_a",),
            repeat_count=1,
            expected_run_count=1,
            records=(),
            errors=(),
            matrix=None,
        )

        self.assertEqual(
            result.to_dict(),
            {
                "suite_name": "training",
                "candidate_id": "cand_child",
                "scenario_ids": ["scenario_a"],
                "repeat_count": 1,
                "expected_run_count": 1,
                "actual_run_count": 0,
                "complete": False,
                "run_ids": [],
                "errors": [],
                "score_matrix": None,
            },
        )

    def test_cli_prints_complete_suite_summary(self) -> None:
        result = _suite_result(
            BASELINE_CANDIDATE_ID,
            {"scenario_a": [(True, 1.0, [])]},
            suite_name="scenarios",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        def fake_suite(*args, **kwargs):
            kwargs["progress_callback"](
                "[1/1] starting scenario=scenario_a attempt=1/1"
            )
            return result

        with patch.object(
            suite_module,
            "run_candidate_suite",
            side_effect=fake_suite,
        ) as run_suite:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = suite_module.main(
                    [
                        "--candidate-id",
                        BASELINE_CANDIDATE_ID,
                        "--scenario-dir",
                        str(DEFAULT_SCENARIO_DIR),
                        "--repeat-count",
                        "2",
                        "--output-dir",
                        ".test-runs",
                        "--no-persist",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["complete"])
        self.assertEqual(payload["candidate_id"], BASELINE_CANDIDATE_ID)
        self.assertEqual(payload["expected_run_count"], 1)
        self.assertEqual(payload["actual_run_count"], 1)
        self.assertEqual(payload["errors"], [])
        self.assertIsNotNone(payload["score_matrix"])
        called_candidate_id, called_spec = run_suite.call_args.args
        self.assertEqual(called_candidate_id, BASELINE_CANDIDATE_ID)
        self.assertEqual(called_spec.repeat_count, 2)
        self.assertEqual(len(called_spec.scenario_paths), 4)
        self.assertFalse(run_suite.call_args.kwargs["persist"])
        self.assertEqual(run_suite.call_args.kwargs["output_dir"], ".test-runs")
        self.assertEqual(
            stderr.getvalue(),
            "[1/1] starting scenario=scenario_a attempt=1/1\n",
        )

    def test_cli_prints_json_for_preflight_failure(self) -> None:
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            with redirect_stdout(stdout):
                exit_code = suite_module.main(
                    [
                        "--candidate-id",
                        BASELINE_CANDIDATE_ID,
                        "--scenario-dir",
                        temp_dir,
                        "--no-persist",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["complete"])
        self.assertEqual(payload["candidate_id"], BASELINE_CANDIDATE_ID)
        self.assertEqual(payload["expected_run_count"], 0)
        self.assertEqual(payload["actual_run_count"], 0)
        self.assertEqual(payload["score_matrix"], None)
        self.assertEqual(payload["errors"][0]["scenario_id"], "<suite_preflight>")
        self.assertEqual(payload["errors"][0]["attempt_number"], 0)
        self.assertEqual(payload["errors"][0]["error_type"], "ValueError")


class CandidateSuiteComparisonTests(unittest.TestCase):
    def test_comparison_reports_pass_rate_improvement(self) -> None:
        parent = _suite_result(
            BASELINE_CANDIDATE_ID,
            {
                "scenario_a": [(False, 0.5, [])],
                "scenario_b": [(True, 1.0, [])],
            },
        )
        child = _suite_result(
            "cand_missing_auth_logs_v1",
            {
                "scenario_a": [(True, 0.9, [])],
                "scenario_b": [(True, 1.0, [])],
            },
        )

        comparison = compare_candidate_suites(parent, child)

        scenario_a = comparison.scenario_delta("scenario_a")
        self.assertEqual(scenario_a.pass_rate_delta, 1.0)
        self.assertTrue(scenario_a.improved)
        self.assertFalse(scenario_a.pass_regressed)
        self.assertEqual(comparison.improved_scenario_ids, ("scenario_a",))
        self.assertEqual(comparison.regressed_scenario_ids, ())

    def test_equal_pass_rate_with_higher_score_is_improvement(self) -> None:
        parent = _suite_result(
            BASELINE_CANDIDATE_ID,
            {"scenario_a": [(False, 0.4, ["poor_final_response"])]},
        )
        child = _suite_result(
            "cand_missing_auth_logs_v1",
            {"scenario_a": [(False, 0.7, ["poor_final_response"])]},
        )

        comparison = compare_candidate_suites(parent, child)
        delta = comparison.scenario_delta("scenario_a")

        self.assertEqual(delta.pass_rate_delta, 0.0)
        self.assertEqual(delta.average_score_delta, 0.3)
        self.assertTrue(delta.improved)

    def test_comparison_flags_pass_and_safety_regressions(self) -> None:
        parent = _suite_result(
            BASELINE_CANDIDATE_ID,
            {
                "scenario_pass": [(True, 1.0, [])],
                "scenario_safety": [(False, 0.5, ["poor_final_response"])],
            },
        )
        child = _suite_result(
            "cand_missing_auth_logs_v1",
            {
                "scenario_pass": [(False, 0.4, ["wrong_root_cause"])],
                "scenario_safety": [(False, 0.5, ["policy_violation"])],
            },
        )

        comparison = compare_candidate_suites(parent, child)

        self.assertEqual(comparison.regressed_scenario_ids, ("scenario_pass",))
        self.assertEqual(
            comparison.safety_regressed_scenario_ids,
            ("scenario_safety",),
        )
        self.assertTrue(
            comparison.scenario_delta("scenario_pass").pass_regressed
        )
        self.assertTrue(
            comparison.scenario_delta("scenario_safety").safety_regressed
        )

    def test_comparison_reports_fatal_eligibility_regression(self) -> None:
        parent = _suite_result(
            BASELINE_CANDIDATE_ID,
            {
                "scenario_a": [
                    (False, 0.8, ["poor_final_response"]),
                    (False, 0.8, ["poor_final_response"]),
                ]
            },
        )
        child = _suite_result(
            "cand_missing_auth_logs_v1",
            {
                "scenario_a": [
                    (False, 0.8, ["poor_final_response"]),
                    (False, 0.8, ["missing_evidence"]),
                ]
            },
        )

        comparison = compare_candidate_suites(parent, child)
        delta = comparison.scenario_delta("scenario_a")

        self.assertEqual(delta.parent_eligible_run_count, 2)
        self.assertEqual(delta.child_eligible_run_count, 1)
        self.assertEqual(delta.eligible_run_count_delta, -1)
        self.assertEqual(delta.parent_fatal_failure_count, 0)
        self.assertEqual(delta.child_fatal_failure_count, 1)
        self.assertEqual(delta.fatal_failure_delta, 1)
        self.assertTrue(delta.fatal_regressed)
        self.assertEqual(
            comparison.fatal_regressed_scenario_ids,
            ("scenario_a",),
        )
        serialized = comparison.to_dict()
        self.assertEqual(
            serialized["fatal_regressed_scenario_ids"],
            ["scenario_a"],
        )
        self.assertEqual(
            serialized["scenario_deltas"][0]["eligible_run_count_delta"],
            -1,
        )

    def test_comparison_rejects_incompatible_suites(self) -> None:
        parent = _suite_result(
            BASELINE_CANDIDATE_ID,
            {"scenario_a": [(True, 1.0, [])]},
        )
        child = _suite_result(
            "cand_missing_auth_logs_v1",
            {"scenario_a": [(True, 1.0, [])]},
        )
        incomplete = CandidateSuiteRun(
            suite_name="training",
            candidate_id="cand_incomplete",
            scenario_ids=("scenario_a",),
            repeat_count=1,
            expected_run_count=1,
            records=(),
            errors=(),
            matrix=None,
        )
        different_name = CandidateSuiteRun(
            suite_name="other",
            candidate_id=child.candidate_id,
            scenario_ids=child.scenario_ids,
            repeat_count=child.repeat_count,
            expected_run_count=child.expected_run_count,
            records=child.records,
            errors=child.errors,
            matrix=child.matrix,
        )
        different_scenario = _suite_result(
            "cand_missing_auth_logs_v1",
            {"scenario_b": [(True, 1.0, [])]},
        )
        different_repeats = _suite_result(
            "cand_missing_auth_logs_v1",
            {"scenario_a": [(True, 1.0, []), (True, 1.0, [])]},
        )

        for left, right in (
            (parent, incomplete),
            (parent, parent),
            (parent, different_name),
            (parent, different_scenario),
            (parent, different_repeats),
        ):
            with self.subTest(right=right):
                with self.assertRaises(ValueError):
                    compare_candidate_suites(left, right)


def _synthetic_record(
    *,
    candidate_id: str,
    scenario_id: str,
    run_id: str,
    passed: bool = True,
    score: float = 1.0,
    failure_tags: list[str] | None = None,
    agent_failure_reason: str | None = None,
) -> RunRecord:
    candidate = DEFAULT_CANDIDATE_POOL.require(candidate_id)
    tags = list(failure_tags or [])
    evaluation = {
        "passed": passed,
        "score": score,
        "failure_tags": tags,
        "fatal_tags": [tag for tag in tags if tag in FATAL_FAILURE_TAGS],
        "nonfatal_tags": [tag for tag in tags if tag not in FATAL_FAILURE_TAGS],
        "eligible_for_selection": not any(
            tag in FATAL_FAILURE_TAGS for tag in tags
        ),
        "checks": [],
        "notes": [],
        "feedback_text": "deterministic feedback",
        "trace_excerpt": [],
    }
    return RunRecord(
        run_id=run_id,
        scenario_id=scenario_id,
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
        final_response="done",
        evaluation=evaluation,
        agent_visible_evaluation={"passed": passed, "score": score},
        candidate_id=candidate_id,
        parent_candidate_id=candidate.parent_id,
        candidate_generation=candidate.generation,
        candidate_kind=candidate.kind,
        agent_failure_reason=agent_failure_reason,
    )


def _suite_result(
    candidate_id: str,
    outcomes: dict[str, list[tuple[bool, float, list[str]]]],
    *,
    suite_name: str = "training",
) -> CandidateSuiteRun:
    scenario_ids = tuple(sorted(outcomes))
    repeat_counts = {len(items) for items in outcomes.values()}
    if len(repeat_counts) != 1:
        raise ValueError("Synthetic suite outcomes must have equal repeats.")
    repeat_count = repeat_counts.pop()
    records = tuple(
        _synthetic_record(
            candidate_id=candidate_id,
            scenario_id=scenario_id,
            run_id=f"run_{candidate_id}_{scenario_id}_{attempt_number}",
            passed=passed,
            score=score,
            failure_tags=tags,
        )
        for scenario_id in scenario_ids
        for attempt_number, (passed, score, tags) in enumerate(
            outcomes[scenario_id],
            start=1,
        )
    )
    matrix = build_score_matrix(records)
    return CandidateSuiteRun(
        suite_name=suite_name,
        candidate_id=candidate_id,
        scenario_ids=scenario_ids,
        repeat_count=repeat_count,
        expected_run_count=len(records),
        records=records,
        errors=(),
        matrix=matrix,
    )


if __name__ == "__main__":
    unittest.main()
