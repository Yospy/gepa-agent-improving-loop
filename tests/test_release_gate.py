from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.optimization import (  # noqa: E402
    DEFAULT_CANDIDATE_POOL,
    Candidate,
)
from agent_reliability_lab.optimization.scoring import build_score_matrix  # noqa: E402
from agent_reliability_lab.release import (  # noqa: E402
    ReleaseGateConfig,
    ReleaseSuiteManifest,
    load_candidate_pool_from_gepa_history,
    persist_release_result,
    run_release_gate,
)
from agent_reliability_lab.release.gate import main  # noqa: E402
from agent_reliability_lab.runs import CandidateSuiteRun, RunRecord  # noqa: E402
from agent_reliability_lab.scenarios import DEFAULT_SCENARIO_DIR  # noqa: E402


FIXED_NOW = datetime(2026, 7, 11, 10, 0, 0, tzinfo=timezone.utc)
BASELINE_ID = "cand_openai_degraded_v1"
CHILD_ID = "cand_release_child"
TRAIN_PATHS = tuple(sorted(DEFAULT_SCENARIO_DIR.glob("*.json")))
REGRESSION_PATH = ROOT / "data/release/regression/northwind_lockout_v1.json"
HOLDOUT_PATH = ROOT / "data/release/holdout/northwind_mfa_v1.json"


class MappingSuiteRunner:
    def __init__(self, results):
        self.results = results
        self.calls: list[tuple[str, str]] = []

    def __call__(self, candidate_id, suite, **kwargs):
        key = (candidate_id, suite.name)
        self.calls.append(key)
        value = self.results[key]
        if isinstance(value, Exception):
            raise value
        return value


class ReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(BASELINE_ID)
        self.child = Candidate(
            candidate_id=CHILD_ID,
            agent_name=parent.agent_name,
            agent_version="openai-release-child-v1",
            parent_id=parent.candidate_id,
            generation=1,
            kind=parent.kind,
            description="Release candidate.",
            payload={"system_instruction": "Inspect evidence and policy."},
        )
        self.pool = DEFAULT_CANDIDATE_POOL.with_candidate(self.child)
        self.manifest = _manifest()
        self.config = ReleaseGateConfig(
            baseline_candidate_id=BASELINE_ID,
            release_candidate_id=CHILD_ID,
            manifest=self.manifest,
            max_total_rollouts=6,
            persist_runs=False,
        )

    def test_complete_non_regressing_regression_and_holdout_promotes(self) -> None:
        runner = MappingSuiteRunner(
            {
                (BASELINE_ID, "release-v1-regression"): _suite(
                    BASELINE_ID, "release-v1-regression", [(True, 1.0, [])] * 2
                ),
                (CHILD_ID, "release-v1-regression"): _suite(
                    CHILD_ID, "release-v1-regression", [(True, 1.0, [])] * 2
                ),
                (CHILD_ID, "release-v1-holdout"): _suite(
                    CHILD_ID, "release-v1-holdout", [(True, 1.0, [])] * 2
                ),
            }
        )

        result = run_release_gate(
            self.config,
            candidate_pool=self.pool,
            suite_runner=runner,
            release_id_factory=lambda: "release_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.decision, "PROMOTED")
        self.assertEqual(result.reason, "all_release_gates_passed")
        self.assertEqual(len(runner.calls), 3)
        self.assertIsNotNone(result.regression_comparison)
        self.assertEqual(len(result.holdout_run_ids), 2)

    def test_regression_rejection_prevents_holdout_execution(self) -> None:
        runner = MappingSuiteRunner(
            {
                (BASELINE_ID, "release-v1-regression"): _suite(
                    BASELINE_ID, "release-v1-regression", [(True, 1.0, [])] * 2
                ),
                (CHILD_ID, "release-v1-regression"): _suite(
                    CHILD_ID,
                    "release-v1-regression",
                    [(True, 1.0, []), (False, 0.5, ["wrong_root_cause"])],
                ),
            }
        )

        result = run_release_gate(
            self.config,
            candidate_pool=self.pool,
            suite_runner=runner,
            release_id_factory=lambda: "release_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.decision, "REJECTED")
        self.assertEqual(result.reason, "regression_pass_rate_regressed")
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(result.holdout_run_ids, ())

    def test_safety_regression_rejects_before_holdout(self) -> None:
        runner = MappingSuiteRunner(
            {
                (BASELINE_ID, "release-v1-regression"): _suite(
                    BASELINE_ID,
                    "release-v1-regression",
                    [(False, 0.5, ["poor_final_response"])] * 2,
                ),
                (CHILD_ID, "release-v1-regression"): _suite(
                    CHILD_ID,
                    "release-v1-regression",
                    [(False, 0.7, ["policy_violation"])] * 2,
                ),
            }
        )

        result = run_release_gate(
            self.config,
            candidate_pool=self.pool,
            suite_runner=runner,
            release_id_factory=lambda: "release_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.decision, "REJECTED")
        self.assertEqual(result.reason, "regression_safety_regressed")
        self.assertEqual(len(runner.calls), 2)

    def test_holdout_failure_rejects_after_regression_passes(self) -> None:
        runner = MappingSuiteRunner(
            {
                (BASELINE_ID, "release-v1-regression"): _suite(
                    BASELINE_ID, "release-v1-regression", [(True, 1.0, [])] * 2
                ),
                (CHILD_ID, "release-v1-regression"): _suite(
                    CHILD_ID, "release-v1-regression", [(True, 1.0, [])] * 2
                ),
                (CHILD_ID, "release-v1-holdout"): _suite(
                    CHILD_ID,
                    "release-v1-holdout",
                    [(True, 1.0, []), (False, 0.7, ["poor_final_response"])],
                ),
            }
        )

        result = run_release_gate(
            self.config,
            candidate_pool=self.pool,
            suite_runner=runner,
            release_id_factory=lambda: "release_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.decision, "REJECTED")
        self.assertEqual(result.reason, "holdout_pass_rate_below_threshold")
        self.assertEqual(len(runner.calls), 3)

    def test_incomplete_or_exceptional_execution_is_inconclusive(self) -> None:
        incomplete = CandidateSuiteRun(
            suite_name="release-v1-regression",
            candidate_id=CHILD_ID,
            scenario_ids=("release_regression",),
            repeat_count=2,
            expected_run_count=2,
            records=(),
            errors=(),
            matrix=None,
        )
        cases = (
            (
                MappingSuiteRunner(
                    {
                        (BASELINE_ID, "release-v1-regression"): _suite(
                            BASELINE_ID,
                            "release-v1-regression",
                            [(True, 1.0, [])] * 2,
                        ),
                        (CHILD_ID, "release-v1-regression"): incomplete,
                    }
                ),
                "candidate_regression_incomplete",
            ),
            (
                MappingSuiteRunner(
                    {
                        (BASELINE_ID, "release-v1-regression"): RuntimeError(
                            "API offline"
                        )
                    }
                ),
                "baseline_regression_error",
            ),
        )

        for runner, reason in cases:
            with self.subTest(reason=reason):
                result = run_release_gate(
                    self.config,
                    candidate_pool=self.pool,
                    suite_runner=runner,
                    release_id_factory=lambda: "release_fixed",
                    clock=lambda: FIXED_NOW,
                )
                self.assertEqual(result.decision, "INCONCLUSIVE")
                self.assertEqual(result.reason, reason)

    def test_sparse_holdout_coverage_is_inconclusive(self) -> None:
        malformed = _suite(
            CHILD_ID,
            "release-v1-holdout",
            [(True, 1.0, []), (True, 1.0, [])],
        )
        malformed = CandidateSuiteRun(
            suite_name=malformed.suite_name,
            candidate_id=malformed.candidate_id,
            scenario_ids=("expected_a", "expected_b"),
            repeat_count=1,
            expected_run_count=2,
            records=malformed.records,
            errors=(),
            matrix=malformed.matrix,
        )
        runner = MappingSuiteRunner(
            {
                (BASELINE_ID, "release-v1-regression"): _suite(
                    BASELINE_ID, "release-v1-regression", [(True, 1.0, [])] * 2
                ),
                (CHILD_ID, "release-v1-regression"): _suite(
                    CHILD_ID, "release-v1-regression", [(True, 1.0, [])] * 2
                ),
                (CHILD_ID, "release-v1-holdout"): malformed,
            }
        )

        result = run_release_gate(
            self.config,
            candidate_pool=self.pool,
            suite_runner=runner,
            release_id_factory=lambda: "release_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertEqual(result.decision, "INCONCLUSIVE")
        self.assertEqual(result.reason, "holdout_coverage_error")

    def test_report_persistence_is_exclusive_and_compact(self) -> None:
        runner = _promoting_runner()
        result = run_release_gate(
            self.config,
            candidate_pool=self.pool,
            suite_runner=runner,
            release_id_factory=lambda: "release_fixed",
            clock=lambda: FIXED_NOW,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = persist_release_result(result, temp_dir)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["decision"], "PROMOTED")
            self.assertNotIn("feedback_text", json.dumps(payload))
            with self.assertRaises(FileExistsError):
                persist_release_result(result, temp_dir)

    def test_cli_prints_result_without_persistence(self) -> None:
        result = run_release_gate(
            self.config,
            candidate_pool=self.pool,
            suite_runner=_promoting_runner(),
            release_id_factory=lambda: "release_fixed",
            clock=lambda: FIXED_NOW,
        )
        stdout = io.StringIO()

        with patch(
            "agent_reliability_lab.release.gate.run_release_gate",
            return_value=result,
        ) as run_gate:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--baseline-candidate-id",
                        BASELINE_ID,
                        "--candidate-id",
                        CHILD_ID,
                        "--regression-repeat-count",
                        "2",
                        "--holdout-repeat-count",
                        "2",
                        "--max-total-rollouts",
                        "6",
                        "--no-persist",
                    ],
                    candidate_pool=self.pool,
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["decision"], "PROMOTED")
        self.assertIsNone(payload["report_path"])
        self.assertFalse(run_gate.call_args.args[0].persist_runs)

    def test_module_cli_executes_config_preflight_without_definition_error(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_reliability_lab.release.gate",
                "--baseline-candidate-id",
                "cand_baseline_v1",
                "--candidate-id",
                "cand_missing_auth_logs_v1",
                "--regression-repeat-count",
                "1",
                "--holdout-repeat-count",
                "1",
                "--max-total-rollouts",
                "2",
                "--no-persist",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertEqual(payload["decision"], "INCONCLUSIVE")
        self.assertEqual(payload["reason"], "release_preflight_error")
        self.assertIn("exceeds rollout budget", payload["detail"])
        self.assertNotIn("NameError", completed.stdout)

    def test_gepa_history_loader_restores_generated_candidate_lineage(self) -> None:
        history = {
            "final_candidate_id": CHILD_ID,
            "generations": [
                {
                    "mutation": {
                        "child": self.child.to_dict(),
                    }
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            path.write_text(json.dumps(history), encoding="utf-8")

            pool = load_candidate_pool_from_gepa_history(path)

        loaded = pool.require(CHILD_ID)
        self.assertEqual(loaded.parent_id, BASELINE_ID)
        self.assertEqual(
            loaded.payload["system_instruction"],
            "Inspect evidence and policy.",
        )


def _manifest() -> ReleaseSuiteManifest:
    return ReleaseSuiteManifest(
        version="release-v1",
        train_paths=TRAIN_PATHS,
        regression_paths=(REGRESSION_PATH,),
        holdout_paths=(HOLDOUT_PATH,),
        regression_repeat_count=2,
        holdout_repeat_count=2,
    )


def _promoting_runner() -> MappingSuiteRunner:
    return MappingSuiteRunner(
        {
            (BASELINE_ID, "release-v1-regression"): _suite(
                BASELINE_ID, "release-v1-regression", [(True, 1.0, [])] * 2
            ),
            (CHILD_ID, "release-v1-regression"): _suite(
                CHILD_ID, "release-v1-regression", [(True, 1.0, [])] * 2
            ),
            (CHILD_ID, "release-v1-holdout"): _suite(
                CHILD_ID, "release-v1-holdout", [(True, 1.0, [])] * 2
            ),
        }
    )


def _suite(candidate_id, suite_name, outcomes) -> CandidateSuiteRun:
    scenario_id = (
        "release_regression" if suite_name.endswith("regression") else "release_holdout"
    )
    records = tuple(
        _record(
            candidate_id,
            scenario_id,
            index,
            passed=passed,
            score=score,
            tags=tags,
        )
        for index, (passed, score, tags) in enumerate(outcomes, start=1)
    )
    return CandidateSuiteRun(
        suite_name=suite_name,
        candidate_id=candidate_id,
        scenario_ids=(scenario_id,),
        repeat_count=len(records),
        expected_run_count=len(records),
        records=records,
        errors=(),
        matrix=build_score_matrix(records),
    )


def _record(candidate_id, scenario_id, index, *, passed, score, tags) -> RunRecord:
    candidate = (
        DEFAULT_CANDIDATE_POOL.require(BASELINE_ID)
        if candidate_id == BASELINE_ID
        else Candidate(
            candidate_id=CHILD_ID,
            agent_name="openai_support_agent",
            agent_version="openai-release-child-v1",
            parent_id=BASELINE_ID,
            generation=1,
            kind="openai_policy",
            description="Release candidate.",
            payload={"system_instruction": "Inspect evidence and policy."},
        )
    )
    eligible = not any(
        tag
        in {
            "policy_violation",
            "wrong_user",
            "wrong_root_cause",
            "missing_evidence",
        }
        for tag in tags
    )
    return RunRecord(
        run_id=f"run_{candidate_id}_{scenario_id}_{index}",
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
        final_response="response",
        evaluation={
            "passed": passed,
            "score": score,
            "failure_tags": list(tags),
            "fatal_tags": [] if eligible else list(tags),
            "nonfatal_tags": list(tags) if eligible else [],
            "eligible_for_selection": eligible,
            "checks": [],
            "notes": [],
            "feedback_text": "private evaluator feedback",
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
