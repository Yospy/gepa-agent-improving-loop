from __future__ import annotations

from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.optimization import (  # noqa: E402
    BASELINE_CANDIDATE_ID,
    DEFAULT_CANDIDATE_POOL,
    assert_complete_score_matrix,
    build_score_matrix,
    pareto_frontier,
    select_parent_candidate,
)
from agent_reliability_lab.runs import run_candidate_scenario  # noqa: E402


FIXED_NOW = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)


class CandidateOptimizationTests(unittest.TestCase):
    def test_default_candidate_pool_has_unique_baseline_and_variants(self) -> None:
        candidate_ids = [
            candidate.candidate_id
            for candidate in DEFAULT_CANDIDATE_POOL.candidates
        ]

        self.assertEqual(len(candidate_ids), len(set(candidate_ids)))
        self.assertEqual(candidate_ids[0], BASELINE_CANDIDATE_ID)
        self.assertEqual(
            DEFAULT_CANDIDATE_POOL.require(BASELINE_CANDIDATE_ID).generation,
            0,
        )
        self.assertEqual(
            {
                candidate.kind
                for candidate in DEFAULT_CANDIDATE_POOL.candidates
            },
            {
                "baseline",
                "missing_auth_logs",
                "openai_policy",
                "reset_failure",
                "unsafe_unlock",
            },
        )

    def test_candidate_runner_records_lineage_and_failure_tags(self) -> None:
        baseline = run_candidate_scenario(
            BASELINE_CANDIDATE_ID,
            clock=lambda: FIXED_NOW,
            persist=False,
        )
        unsafe = run_candidate_scenario(
            "cand_unsafe_unlock_v1",
            clock=lambda: FIXED_NOW,
            persist=False,
        )

        self.assertTrue(baseline.evaluation["passed"])
        self.assertEqual(baseline.candidate_id, BASELINE_CANDIDATE_ID)
        self.assertIsNone(baseline.parent_candidate_id)
        self.assertEqual(baseline.candidate_generation, 0)
        self.assertEqual(baseline.candidate_kind, "baseline")
        self.assertFalse(unsafe.evaluation["passed"])
        self.assertEqual(unsafe.parent_candidate_id, BASELINE_CANDIDATE_ID)
        self.assertEqual(unsafe.candidate_generation, 1)
        self.assertIn("policy_violation", unsafe.evaluation["failure_tags"])
        self.assertIn(
            "unlock_user",
            [call["tool_name"] for call in unsafe.tool_calls],
        )

    def test_score_matrix_aggregates_candidates_by_scenario(self) -> None:
        records = _run_all_candidates()

        matrix = build_score_matrix(records)

        self.assertEqual(
            matrix.candidate_ids,
            sorted(
                candidate.candidate_id
                for candidate in DEFAULT_CANDIDATE_POOL.candidates
                if candidate.kind != "openai_policy"
            ),
        )
        self.assertEqual(matrix.scenario_ids, ["support_login_lockout_v1"])
        baseline_cell = matrix.cell(
            BASELINE_CANDIDATE_ID,
            "support_login_lockout_v1",
        )
        unsafe_cell = matrix.cell(
            "cand_unsafe_unlock_v1",
            "support_login_lockout_v1",
        )
        reset_cell = matrix.cell(
            "cand_reset_failure_v1",
            "support_login_lockout_v1",
        )
        self.assertEqual(baseline_cell.pass_rate, 1.0)
        self.assertEqual(baseline_cell.average_score, 1.0)
        self.assertEqual(baseline_cell.failure_counts, {})
        self.assertTrue(baseline_cell.eligible_for_selection)
        self.assertEqual(unsafe_cell.safety_failure_count, 1)
        self.assertEqual(unsafe_cell.failure_counts["policy_violation"], 1)
        self.assertFalse(unsafe_cell.eligible_for_selection)
        self.assertFalse(reset_cell.eligible_for_selection)
        self.assertEqual(
            reset_cell.fatal_failure_counts,
            {"hallucinated_password_reset_failure": 1},
        )

    def test_pareto_frontier_and_weighted_selection_choose_baseline(self) -> None:
        matrix = build_score_matrix(_run_all_candidates())

        frontier = pareto_frontier(matrix)
        selection = select_parent_candidate(matrix)

        self.assertEqual(
            [candidate.candidate_id for candidate in frontier],
            [BASELINE_CANDIDATE_ID],
        )
        self.assertEqual(selection.selected_candidate_id, BASELINE_CANDIDATE_ID)
        self.assertEqual(selection.eligible_candidate_ids, [BASELINE_CANDIDATE_ID])
        self.assertEqual(
            selection.weighted_scores[BASELINE_CANDIDATE_ID],
            1.0,
        )

    def test_parent_selection_ignores_ineligible_dominating_candidate(self) -> None:
        matrix = build_score_matrix(
            [
                _synthetic_record(
                    run_id="run_safe",
                    candidate_id="cand_safe_partial",
                    score=0.6,
                    failure_tags=["poor_final_response"],
                    eligible_for_selection=True,
                ),
                _synthetic_record(
                    run_id="run_fatal",
                    candidate_id="cand_fatal_high_score",
                    score=0.9,
                    failure_tags=["hallucinated_password_reset_failure"],
                    eligible_for_selection=False,
                ),
            ]
        )

        selection = select_parent_candidate(matrix)

        self.assertEqual(selection.selected_candidate_id, "cand_safe_partial")
        self.assertEqual(selection.frontier_candidate_ids, ["cand_safe_partial"])
        self.assertEqual(selection.eligible_candidate_ids, ["cand_safe_partial"])

    def test_score_matrix_infers_legacy_eligibility_from_failure_tags(self) -> None:
        matrix = build_score_matrix(
            [
                _synthetic_record(
                    run_id="run_legacy_nonfatal",
                    candidate_id="cand_legacy_nonfatal",
                    score=0.7,
                    failure_tags=["poor_final_response"],
                ),
                _synthetic_record(
                    run_id="run_legacy_fatal",
                    candidate_id="cand_legacy_fatal",
                    score=0.8,
                    failure_tags=["wrong_root_cause"],
                ),
            ]
        )

        self.assertTrue(
            matrix.candidate_score("cand_legacy_nonfatal").eligible_for_selection
        )
        self.assertFalse(
            matrix.candidate_score("cand_legacy_fatal").eligible_for_selection
        )

    def test_complete_score_matrix_rejects_missing_cell(self) -> None:
        matrix = build_score_matrix(
            [
                _synthetic_record(
                    run_id="run_a_1",
                    candidate_id="cand_a",
                    scenario_id="scenario_1",
                    score=1.0,
                    failure_tags=[],
                ),
                _synthetic_record(
                    run_id="run_a_2",
                    candidate_id="cand_a",
                    scenario_id="scenario_2",
                    score=1.0,
                    failure_tags=[],
                ),
                _synthetic_record(
                    run_id="run_b_1",
                    candidate_id="cand_b",
                    scenario_id="scenario_1",
                    score=1.0,
                    failure_tags=[],
                ),
            ]
        )

        with self.assertRaises(ValueError):
            assert_complete_score_matrix(
                matrix,
                expected_candidate_ids=["cand_a", "cand_b"],
                expected_scenario_ids=["scenario_1", "scenario_2"],
                expected_runs_per_cell=1,
            )

    def test_complete_score_matrix_rejects_unexpected_scenario(self) -> None:
        matrix = build_score_matrix(
            [
                _synthetic_record(
                    run_id="run_extra",
                    candidate_id="cand_a",
                    scenario_id="scenario_extra",
                    score=1.0,
                    failure_tags=[],
                )
            ]
        )

        with self.assertRaises(ValueError):
            assert_complete_score_matrix(
                matrix,
                expected_candidate_ids=["cand_a"],
                expected_scenario_ids=["scenario_1"],
                expected_runs_per_cell=1,
            )

    def test_complete_score_matrix_rejects_wrong_repeat_count(self) -> None:
        matrix = build_score_matrix(
            [
                _synthetic_record(
                    run_id="run_once",
                    candidate_id="cand_a",
                    scenario_id="scenario_1",
                    score=1.0,
                    failure_tags=[],
                )
            ]
        )

        with self.assertRaises(ValueError):
            assert_complete_score_matrix(
                matrix,
                expected_candidate_ids=["cand_a"],
                expected_scenario_ids=["scenario_1"],
                expected_runs_per_cell=2,
            )

    def test_complete_score_matrix_accepts_full_cross_product(self) -> None:
        records = [
            _synthetic_record(
                run_id=f"run_{candidate_id}_{scenario_id}_{repeat}",
                candidate_id=candidate_id,
                scenario_id=scenario_id,
                score=1.0,
                failure_tags=[],
            )
            for candidate_id in ("cand_a", "cand_b")
            for scenario_id in ("scenario_1", "scenario_2")
            for repeat in range(2)
        ]
        matrix = build_score_matrix(records)

        self.assertIsNone(
            assert_complete_score_matrix(
                matrix,
                expected_candidate_ids=["cand_a", "cand_b"],
                expected_scenario_ids=["scenario_1", "scenario_2"],
                expected_runs_per_cell=2,
            )
        )


def _run_all_candidates() -> list[object]:
    return [
        run_candidate_scenario(
            candidate.candidate_id,
            clock=lambda: FIXED_NOW,
            persist=False,
        )
        for candidate in DEFAULT_CANDIDATE_POOL.candidates
        if candidate.kind != "openai_policy"
    ]


def _synthetic_record(
    *,
    run_id: str,
    candidate_id: str,
    scenario_id: str = "support_login_lockout_v1",
    score: float,
    failure_tags: list[str],
    eligible_for_selection: bool | None = None,
) -> dict[str, object]:
    evaluation: dict[str, object] = {
        "passed": not failure_tags,
        "score": score,
        "failure_tags": failure_tags,
        "checks": [],
    }
    if eligible_for_selection is not None:
        evaluation["eligible_for_selection"] = eligible_for_selection
    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "agent_version": candidate_id,
        "candidate_id": candidate_id,
        "evaluation": evaluation,
    }


if __name__ == "__main__":
    unittest.main()
