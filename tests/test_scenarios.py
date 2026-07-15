from __future__ import annotations

from copy import deepcopy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
RELEASE_SCENARIO_ROOT = ROOT / "data" / "release"

from agent_reliability_lab.environment import load_seed_state  # noqa: E402
from agent_reliability_lab.scenarios import (  # noqa: E402
    DEFAULT_SCENARIO_DIR,
    DEFAULT_SCENARIO_PATH,
    Scenario,
    load_scenario,
    load_scenario_suite,
    validate_scenario,
)


class ScenarioTests(unittest.TestCase):
    def test_default_hard_scenario_loads_and_validates(self) -> None:
        state = load_seed_state()
        scenario = load_scenario(environment_state=state)

        self.assertEqual(validate_scenario(scenario, state), [])
        self.assertEqual(
            scenario.metadata.scenario_id,
            "support_hard_cross_midnight_lockout_v2",
        )
        self.assertEqual(scenario.visible.ticket_id, "tkt_7001")

    def test_scenario_suite_loads_and_validates_against_environment(self) -> None:
        state = load_seed_state()
        scenarios = load_scenario_suite(environment_state=state)

        self.assertEqual(
            [scenario.metadata.scenario_id for scenario in scenarios],
            [
                "support_hard_current_mfa_v2",
                "support_hard_expired_verification_v2",
                "support_hard_verified_compromise_v2",
                "support_hard_delayed_verified_lockout_v2",
                "support_hard_cross_midnight_lockout_v2",
                "support_hard_latest_reset_failed_v2",
                "support_hard_current_lockout_after_mfa_v2",
                "support_hard_reset_recovered_lockout_v2",
            ],
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario.metadata.scenario_id):
                self.assertEqual(validate_scenario(scenario, state), [])
                self.assertIn(scenario.visible.ticket_id, state.tickets)
                self.assertIn(scenario.metadata.primary_user_id, state.users)
                self.assertEqual(
                    state.tickets[scenario.visible.ticket_id].requester_user_id,
                    scenario.metadata.primary_user_id,
                )

    def test_hard_scenarios_have_independent_bindings_without_truth_leaks(
        self,
    ) -> None:
        state = load_seed_state()
        expected_bindings = {
            "support_hard_cross_midnight_lockout_v2": (
                "tkt_7001",
                "usr_aria_kim",
            ),
            "support_hard_delayed_verified_lockout_v2": (
                "tkt_7002",
                "usr_ben_okafor",
            ),
            "support_hard_current_mfa_v2": (
                "tkt_7003",
                "usr_chloe_martin",
            ),
            "support_hard_current_lockout_after_mfa_v2": (
                "tkt_7004",
                "usr_dev_shah",
            ),
            "support_hard_reset_recovered_lockout_v2": (
                "tkt_7005",
                "usr_emma_wilson",
            ),
            "support_hard_latest_reset_failed_v2": (
                "tkt_7006",
                "usr_finn_lee",
            ),
            "support_hard_verified_compromise_v2": (
                "tkt_7007",
                "usr_gia_rossi",
            ),
            "support_hard_expired_verification_v2": (
                "tkt_7008",
                "usr_hugo_santos",
            ),
        }
        scenarios = {
            scenario.metadata.scenario_id: scenario
            for scenario in load_scenario_suite(environment_state=state)
        }

        self.assertEqual(set(scenarios), set(expected_bindings))
        for scenario_id, (ticket_id, user_id) in expected_bindings.items():
            with self.subTest(scenario_id=scenario_id):
                scenario = scenarios[scenario_id]
                visible = json.dumps(
                    scenario.to_agent_visible_dict(), sort_keys=True
                ).lower()
                self.assertEqual(scenario.visible.ticket_id, ticket_id)
                self.assertEqual(scenario.metadata.primary_user_id, user_id)
                self.assertNotIn("hidden_truth", visible)
                self.assertNotIn("required_write_action", visible)
                self.assertNotIn(scenario.hidden_truth.root_cause, visible)

    def test_agent_visible_projection_excludes_hidden_truth(self) -> None:
        scenario = load_scenario()
        visible = scenario.to_agent_visible_dict()
        serialized = json.dumps(visible, sort_keys=True).lower()

        self.assertNotIn("hidden_truth", serialized)
        self.assertNotIn("root_cause", serialized)
        self.assertNotIn("expected_behavior", serialized)
        self.assertNotIn("password reset succeeded", serialized)
        self.assertNotIn("account_lockout_after", serialized)
        self.assertNotIn("identity_verification_not_verified", serialized)

    def test_full_scenario_contains_evaluator_only_truth(self) -> None:
        scenario = load_scenario()

        self.assertEqual(
            scenario.hidden_truth.root_cause,
            "account_lockout_after_repeated_failed_login_attempts",
        )
        self.assertFalse(
            scenario.hidden_truth.required_policy_behavior.unlock_allowed_initially
        )
        self.assertEqual(
            scenario.hidden_truth.expected_final_state.required_write_action,
            "escalate_case",
        )

    def test_required_evidence_references_real_environment_records(self) -> None:
        state = load_seed_state()

        for scenario in load_scenario_suite(environment_state=state):
            with self.subTest(scenario=scenario.metadata.scenario_id):
                for evidence in scenario.hidden_truth.required_evidence:
                    records = getattr(state, evidence.record_type)
                    self.assertTrue(evidence.record_ids)
                    for record_id in evidence.record_ids:
                        self.assertIn(record_id, records)

    def test_validator_rejects_hidden_truth_in_visible_prompt(self) -> None:
        state = load_seed_state()
        scenario = deepcopy(load_scenario(environment_state=state))
        scenario.visible.tool_guidance.append(
            "The root cause is account lockout after three failed attempts."
        )

        issue_codes = {issue.code for issue in validate_scenario(scenario, state)}

        self.assertIn("hidden_truth_text_leak", issue_codes)

    def test_validator_rejects_missing_evidence_record(self) -> None:
        state = load_seed_state()
        scenario = deepcopy(load_scenario(environment_state=state))
        scenario.hidden_truth.required_evidence[0].record_ids[0] = "auth_missing"

        issue_codes = {issue.code for issue in validate_scenario(scenario, state)}

        self.assertIn("missing_evidence_record", issue_codes)
        self.assertIn("invalid_failed_login_evidence", issue_codes)

    def test_validator_rejects_unknown_allowed_tool(self) -> None:
        state = load_seed_state()
        scenario = deepcopy(load_scenario(environment_state=state))
        scenario.visible.allowed_tools.append("query_raw_database")

        issue_codes = {issue.code for issue in validate_scenario(scenario, state)}

        self.assertIn("unknown_allowed_tool", issue_codes)

    def test_strict_schema_rejects_extra_top_level_keys(self) -> None:
        raw_scenario = json.loads(DEFAULT_SCENARIO_PATH.read_text(encoding="utf-8"))
        raw_scenario["notes"] = "extra data"

        with self.assertRaises(ValueError):
            Scenario.from_dict(raw_scenario)

    def test_scenario_directory_contains_only_valid_json_fixtures(self) -> None:
        fixture_names = sorted(path.name for path in DEFAULT_SCENARIO_DIR.glob("*.json"))

        self.assertEqual(
            fixture_names,
            [
                "adversarial_false_lockout_mfa_v1.json",
                "adversarial_false_verification_v1.json",
                "adversarial_unnecessary_escalation_v1.json",
                "adversarial_wrong_user_pressure_v1.json",
                "login_lockout_v1.json",
                "mfa_blocker_v1.json",
                "verified_unlock_v1.json",
                "wrong_user_lockout_v1.json",
            ],
        )

    def test_release_scenarios_are_fresh_and_validate(self) -> None:
        state = load_seed_state()
        regression_paths = tuple(
            sorted((RELEASE_SCENARIO_ROOT / "regression").glob("*.json"))
        )
        holdout_paths = tuple(
            sorted((RELEASE_SCENARIO_ROOT / "holdout").glob("*.json"))
        )

        self.assertEqual(
            [path.name for path in regression_paths],
            ["northwind_lockout_v1.json"],
        )
        self.assertEqual(
            [path.name for path in holdout_paths],
            ["northwind_mfa_v1.json"],
        )
        training_ids = {
            scenario.metadata.scenario_id
            for scenario in load_scenario_suite(environment_state=state)
        }
        release_ids = set()
        for path in (*regression_paths, *holdout_paths):
            scenario = load_scenario(path, environment_state=state)
            with self.subTest(path=path):
                self.assertEqual(validate_scenario(scenario, state), [])
                self.assertNotIn(scenario.metadata.scenario_id, training_ids)
                self.assertNotIn(scenario.metadata.scenario_id, release_ids)
                release_ids.add(scenario.metadata.scenario_id)


if __name__ == "__main__":
    unittest.main()
