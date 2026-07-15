from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.runs import RunRecorder, run_baseline_scenario  # noqa: E402


FIXED_NOW = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)


class RunRecorderTests(unittest.TestCase):
    def test_baseline_run_record_persists_full_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            record = run_baseline_scenario(
                output_dir=temp_dir,
                clock=lambda: FIXED_NOW,
            )
            path = RunRecorder(temp_dir).record_path(record)

            self.assertTrue(path.exists())
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved, record.to_dict())
            self.assertEqual(
                record.scenario_id,
                "support_hard_cross_midnight_lockout_v2",
            )
            self.assertEqual(record.agent_version, "baseline-support-v1")
            self.assertTrue(record.evaluation["passed"])
            self.assertEqual(record.evaluation["score"], 1.0)
            self.assertNotEqual(record.initial_state_hash, record.final_state_hash)
            self.assertEqual(record.state_diff["changed_tickets"], ["tkt_7001"])
            self.assertEqual(
                record.state_diff["added_audit_entries"],
                ["audit_tool_0001"],
            )
            self.assertIn(
                "escalate_case",
                [call["tool_name"] for call in record.tool_calls],
            )

    def test_repeated_fixed_clock_runs_use_distinct_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = run_baseline_scenario(
                output_dir=temp_dir,
                clock=lambda: FIXED_NOW,
            )
            second = run_baseline_scenario(
                output_dir=temp_dir,
                clock=lambda: FIXED_NOW,
            )

            self.assertNotEqual(first.run_id, second.run_id)
            self.assertTrue(RunRecorder(temp_dir).record_path(first).exists())
            self.assertTrue(RunRecorder(temp_dir).record_path(second).exists())
            self.assertEqual(len(list(Path(temp_dir).glob("*.json"))), 2)

    def test_recorder_refuses_to_overwrite_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            record = run_baseline_scenario(
                output_dir=temp_dir,
                clock=lambda: FIXED_NOW,
            )

            with self.assertRaises(FileExistsError):
                RunRecorder(temp_dir).save(record)

    def test_agent_visible_run_projection_omits_evaluator_only_details(self) -> None:
        record = run_baseline_scenario(
            clock=lambda: FIXED_NOW,
            persist=False,
        )

        visible = record.to_agent_visible_dict()
        serialized = json.dumps(visible, sort_keys=True)

        self.assertEqual(
            set(visible),
            {
                "run_id",
                "scenario_id",
                "scenario_version",
                "agent_name",
                "agent_version",
                "final_response",
                "evaluation",
            },
        )
        self.assertEqual(visible["evaluation"], {"passed": True, "score": 1.0})
        self.assertNotIn("hidden_truth", serialized)
        self.assertNotIn("usr_ava_cho", serialized)
        self.assertNotIn("failed_login_attempts", serialized)
        self.assertNotIn("failure_tags", serialized)
        self.assertNotIn("agent_failure_reason", visible)
        self.assertIsNone(record.agent_failure_reason)


if __name__ == "__main__":
    unittest.main()
