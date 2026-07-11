from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.analysis import (  # noqa: E402
    analyze_runs,
    compare_agent_versions,
    compare_run_sets,
    load_run_records,
)
from agent_reliability_lab.analysis import failures  # noqa: E402
from agent_reliability_lab.runs import run_baseline_scenario  # noqa: E402


FIXED_NOW = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)


class FailureAnalysisTests(unittest.TestCase):
    def test_analyzes_synthetic_failures_and_current_baseline(self) -> None:
        baseline = run_baseline_scenario(
            clock=lambda: FIXED_NOW,
            persist=False,
        ).to_dict()
        failed_evidence = _synthetic_record(
            run_id="run_failed_missing_evidence",
            agent_version="candidate-v1",
            passed=False,
            score=0.7,
            failure_tags=[
                "missing_evidence",
                "poor_final_response",
                "wrong_root_cause",
            ],
        )
        failed_policy = _synthetic_record(
            run_id="run_failed_policy",
            agent_version="candidate-v1",
            passed=False,
            score=0.6,
            failure_tags=[
                "policy_violation",
                "stale_policy_used",
                "wrong_user",
            ],
        )

        report = analyze_runs([baseline, failed_evidence, failed_policy])

        self.assertEqual(report.run_count, 3)
        self.assertEqual(report.passed_count, 1)
        self.assertEqual(report.failed_count, 2)
        summaries = {
            summary.failure: summary
            for summary in report.failure_summaries
        }
        self.assertEqual(summaries["missing_evidence"].count, 1)
        self.assertEqual(summaries["wrong_root_cause"].count, 1)
        self.assertEqual(summaries["policy_violation"].count, 1)
        self.assertEqual(summaries["wrong_user"].count, 1)
        self.assertEqual(summaries["stale_policy"].count, 1)
        self.assertEqual(summaries["poor_final_response"].count, 1)

        rows = {row.run_id: row for row in report.improvement_reports}
        self.assertTrue(rows[baseline["run_id"]].passed)
        self.assertEqual(rows[baseline["run_id"]].suggested_improvement_targets, [])
        self.assertFalse(rows["run_failed_missing_evidence"].passed)
        self.assertEqual(
            rows["run_failed_missing_evidence"].failure_tags,
            [
                "missing_evidence",
                "poor_final_response",
                "wrong_root_cause",
            ],
        )
        self.assertEqual(
            rows["run_failed_missing_evidence"].agent_version,
            "candidate-v1",
        )
        self.assertEqual(
            rows["run_failed_missing_evidence"].scenario_id,
            "support_login_lockout_v1",
        )
        self.assertGreater(
            len(rows["run_failed_missing_evidence"].suggested_improvement_targets),
            0,
        )

    def test_loads_run_records_from_directory_and_cli_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            _write_run(
                temp_path / "passing.json",
                run_baseline_scenario(
                    clock=lambda: FIXED_NOW,
                    persist=False,
                ).to_dict(),
            )
            _write_run(
                temp_path / "failed.json",
                _synthetic_record(
                    run_id="run_failed_response",
                    agent_version="candidate-v1",
                    passed=False,
                    score=0.8,
                    failure_tags=["poor_final_response"],
                ),
            )

            records = load_run_records(temp_path)
            self.assertEqual(len(records), 2)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = failures.main([str(temp_path)])

            output = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(output["run_count"], 2)
            self.assertEqual(output["failed_count"], 1)
            summaries = {
                summary["failure"]: summary
                for summary in output["failure_summaries"]
            }
            self.assertEqual(summaries["poor_final_response"]["count"], 1)

    def test_compares_agent_versions(self) -> None:
        records = [
            _synthetic_record(
                run_id="run_baseline",
                agent_version="baseline-v1",
                passed=True,
                score=1.0,
                failure_tags=[],
            ),
            _synthetic_record(
                run_id="run_candidate",
                agent_version="candidate-v1",
                passed=False,
                score=0.6,
                failure_tags=["missing_evidence"],
            ),
        ]

        comparison = compare_agent_versions(
            records,
            "baseline-v1",
            "candidate-v1",
        )

        self.assertEqual(comparison.baseline_label, "baseline-v1")
        self.assertEqual(comparison.candidate_label, "candidate-v1")
        self.assertEqual(comparison.deltas["pass_rate"], -1.0)
        self.assertEqual(comparison.deltas["average_score"], -0.4)
        self.assertEqual(
            comparison.deltas["failure_counts"],
            {"missing_evidence": 1},
        )

    def test_compares_two_run_sets(self) -> None:
        baseline_records = [
            _synthetic_record(
                run_id="run_baseline",
                agent_version="agent-v1",
                passed=True,
                score=1.0,
                failure_tags=[],
            )
        ]
        candidate_records = [
            _synthetic_record(
                run_id="run_candidate",
                agent_version="agent-v2",
                passed=False,
                score=0.5,
                failure_tags=["policy_violation", "wrong_user"],
            )
        ]

        comparison = compare_run_sets(
            baseline_records,
            candidate_records,
            baseline_label="left",
            candidate_label="right",
        )

        self.assertEqual(comparison.baseline_label, "left")
        self.assertEqual(comparison.candidate_label, "right")
        self.assertEqual(comparison.deltas["failed_count"], 1)
        self.assertEqual(
            comparison.deltas["failure_counts"],
            {"policy_violation": 1, "wrong_user": 1},
        )


def _synthetic_record(
    *,
    run_id: str,
    agent_version: str,
    passed: bool,
    score: float,
    failure_tags: list[str],
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "scenario_id": "support_login_lockout_v1",
        "agent_version": agent_version,
        "evaluation": {
            "passed": passed,
            "score": score,
            "failure_tags": failure_tags,
            "checks": [],
        },
    }


def _write_run(path: Path, record: dict[str, object]) -> None:
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
