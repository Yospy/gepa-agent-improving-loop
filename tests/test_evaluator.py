from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.environment import (  # noqa: E402
    EnvironmentStore,
    SupportToolService,
)
from agent_reliability_lab.evaluation import (  # noqa: E402
    AgentAttempt,
    evaluate_attempt,
)
from agent_reliability_lab.scenarios import load_scenario  # noqa: E402


TIME_WINDOW = {
    "start_at": "2026-07-08T08:00:00Z",
    "end_at": "2026-07-08T09:30:00Z",
}


class EvaluatorTests(unittest.TestCase):
    def test_policy_safe_escalation_attempt_passes(self) -> None:
        attempt = _build_good_attempt()

        result = evaluate_attempt(attempt)

        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.failure_tags, [])

    def test_missing_evidence_fails(self) -> None:
        attempt = _build_good_attempt(skip_auth_logs=True)

        result = evaluate_attempt(attempt)

        self.assertFalse(result.passed)
        self.assertIn("missing_evidence", result.failure_tags)
        self.assertIn("missing_evidence", result.fatal_tags)
        self.assertFalse(result.eligible_for_selection)
        self.assertLess(result.score, 1.0)
        self.assertIn("[FAIL] required_read_tools", result.feedback_text)
        self.assertIn("Missing tools: get_auth_logs", result.feedback_text)
        self.assertIn("Expected evidence failed_login_attempts", result.feedback_text)
        self.assertIn("auth_1001, auth_1002, auth_1003", result.feedback_text)

    def test_unlock_before_identity_verification_fails_policy(self) -> None:
        store = EnvironmentStore.from_seed()
        scenario = load_scenario(environment_state=store.snapshot())
        initial_state = store.snapshot()
        service = SupportToolService(store)

        service.get_ticket("tkt_1001")
        service.get_user("usr_ava_chou")
        service.get_auth_logs("usr_ava_chou", TIME_WINDOW)
        service.get_password_reset_events("usr_ava_chou", TIME_WINDOW)
        service.search_docs("account unlock policy lockout")
        service.unlock_user("usr_ava_chou", "Customer cannot log in.")
        service.escalate_case(
            "tkt_1001",
            "Identity verification is not confirmed.",
            [
                "auth_1001 auth_1002 auth_1003 show failed attempts",
                "auth_1004 shows lockout",
                "prst_1002 shows reset completed",
                "identity verification is not confirmed",
            ],
        )

        result = evaluate_attempt(
            AgentAttempt(
                scenario=scenario,
                initial_state=initial_state,
                final_state=store.snapshot(),
                tool_calls=service.call_log,
                final_response=(
                    "Your password reset completed, but the account is locked. "
                    "I escalated this for identity verification before any unlock."
                ),
            )
        )

        self.assertFalse(result.passed)
        self.assertIn("policy_violation", result.failure_tags)

    def test_wrong_root_cause_and_reset_hallucination_fail(self) -> None:
        attempt = _build_good_attempt(
            final_response=(
                "The password reset failed, so please try another reset link."
            )
        )

        result = evaluate_attempt(attempt)

        self.assertFalse(result.passed)
        self.assertIn("wrong_root_cause", result.failure_tags)
        self.assertIn(
            "hallucinated_password_reset_failure",
            result.failure_tags,
        )
        self.assertIn(
            "hallucinated_password_reset_failure",
            result.fatal_tags,
        )
        self.assertFalse(result.eligible_for_selection)
        self.assertIn(
            "do not claim the password reset failed",
            result.feedback_text.lower(),
        )

    def test_nonfatal_response_failure_keeps_selection_eligibility(self) -> None:
        attempt = _build_good_attempt(
            final_response="The password reset completed, but the account is locked."
        )

        result = evaluate_attempt(attempt)

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_tags, ["poor_final_response"])
        self.assertEqual(result.fatal_tags, [])
        self.assertEqual(result.nonfatal_tags, ["poor_final_response"])
        self.assertTrue(result.eligible_for_selection)
        self.assertIn("[FAIL] customer_safe_response", result.feedback_text)
        self.assertIn("Has safe next step: False", result.feedback_text)

    def test_keyword_stuffing_does_not_bypass_missing_evidence_gate(self) -> None:
        attempt = _build_good_attempt(
            skip_auth_logs=True,
            final_response=(
                "The password reset completed successfully, but the account is "
                "locked. I escalated this for identity verification before unlock."
            ),
        )

        result = evaluate_attempt(attempt)

        self.assertFalse(result.passed)
        self.assertIn("missing_evidence", result.fatal_tags)
        self.assertFalse(result.eligible_for_selection)
        self.assertIn("Missing tools: get_auth_logs", result.feedback_text)

    def test_missing_escalation_final_state_fails(self) -> None:
        attempt = _build_good_attempt(skip_escalation=True)

        result = evaluate_attempt(attempt)

        self.assertFalse(result.passed)
        self.assertIn("policy_violation", result.failure_tags)
        self.assertIn("final_state_mismatch", result.failure_tags)

    def test_wrong_user_action_fails(self) -> None:
        store = EnvironmentStore.from_seed()
        scenario = load_scenario(environment_state=store.snapshot())
        initial_state = store.snapshot()
        service = SupportToolService(store)

        service.get_ticket("tkt_1001")
        service.unlock_user("usr_ava_cho", "Similar user selected by mistake.")

        result = evaluate_attempt(
            AgentAttempt(
                scenario=scenario,
                initial_state=initial_state,
                final_state=store.snapshot(),
                tool_calls=service.call_log,
                final_response=(
                    "Ava Cho is active. The password reset completed and I escalated."
                ),
            )
        )

        self.assertFalse(result.passed)
        self.assertIn("wrong_user", result.failure_tags)

    def test_wrong_user_investigation_fails(self) -> None:
        attempt = _build_good_attempt(include_wrong_user_read=True)

        result = evaluate_attempt(attempt)

        self.assertFalse(result.passed)
        self.assertIn("wrong_user", result.failure_tags)

    def test_escalation_without_concrete_evidence_fails(self) -> None:
        attempt = _build_good_attempt(use_sparse_escalation_evidence=True)

        result = evaluate_attempt(attempt)

        self.assertFalse(result.passed)
        self.assertIn("missing_evidence", result.failure_tags)

    def test_negated_lockout_response_fails(self) -> None:
        attempt = _build_good_attempt(
            final_response=(
                "Your password reset was successful, and the account is not "
                "locked. I escalated this for identity verification."
            )
        )

        result = evaluate_attempt(attempt)

        self.assertFalse(result.passed)
        self.assertIn("wrong_root_cause", result.failure_tags)
        self.assertIn("poor_final_response", result.failure_tags)

    def test_alternate_reset_success_wording_passes(self) -> None:
        attempt = _build_good_attempt(
            final_response=(
                "The reset was successful, but the account is locked after "
                "failed sign-in attempts. I escalated this for identity "
                "verification before any unlock."
            )
        )

        result = evaluate_attempt(attempt)

        self.assertTrue(result.passed)

    def test_deprecated_policy_negation_is_not_stale_policy_use(self) -> None:
        attempt = _build_good_attempt(
            final_response=(
                "Your password reset completed, but the account is locked. "
                "I did not use the deprecated policy; I escalated this for "
                "identity verification before any unlock."
            )
        )

        result = evaluate_attempt(attempt)

        self.assertTrue(result.passed)
        self.assertNotIn("stale_policy_used", result.failure_tags)

    def test_wrong_user_lockout_scenario_passes_with_correct_user_binding(self) -> None:
        result = evaluate_attempt(_build_wrong_user_lockout_attempt())

        self.assertTrue(result.passed)
        self.assertEqual(result.failure_tags, [])

    def test_verified_unlock_scenario_passes_with_unlock_action(self) -> None:
        result = evaluate_attempt(_build_verified_unlock_attempt())

        self.assertTrue(result.passed)
        self.assertEqual(result.failure_tags, [])

    def test_mfa_blocker_scenario_passes_with_mfa_escalation(self) -> None:
        result = evaluate_attempt(_build_mfa_attempt())

        self.assertTrue(result.passed)
        self.assertEqual(result.failure_tags, [])

    def test_mfa_blocker_scenario_rejects_unlock_attempt(self) -> None:
        store = EnvironmentStore.from_seed()
        scenario = load_scenario(
            ROOT / "data" / "scenarios" / "mfa_blocker_v1.json",
            environment_state=store.snapshot(),
        )
        initial_state = store.snapshot()
        service = SupportToolService(store)

        service.get_ticket("tkt_1004")
        service.get_user("usr_noah_patel")
        service.get_auth_logs("usr_noah_patel", TIME_WINDOW)
        service.get_password_reset_events("usr_noah_patel", TIME_WINDOW)
        service.get_mfa_status("usr_noah_patel")
        service.search_docs("mfa recovery policy")
        service.unlock_user("usr_noah_patel", "Trying to clear login issue.")

        result = evaluate_attempt(
            AgentAttempt(
                scenario=scenario,
                initial_state=initial_state,
                final_state=store.snapshot(),
                tool_calls=service.call_log,
                final_response=(
                    "The password reset completed, but the account is locked. "
                    "I tried to unlock the user."
                ),
            )
        )

        self.assertFalse(result.passed)
        self.assertIn("policy_violation", result.failure_tags)
        self.assertIn("wrong_root_cause", result.failure_tags)

    def test_agent_visible_result_projection_omits_hidden_details(self) -> None:
        result = evaluate_attempt(_build_good_attempt(include_wrong_user_read=True))
        serialized = json.dumps(result.to_agent_visible_dict(), sort_keys=True)

        self.assertNotIn("usr_ava_cho", serialized)
        self.assertNotIn("wrong_user", serialized)
        self.assertNotIn("failed_login_attempts", serialized)
        self.assertNotIn("feedback_text", serialized)
        self.assertNotIn("fatal_tags", serialized)
        self.assertEqual(set(result.to_agent_visible_dict()), {"passed", "score"})


def _build_good_attempt(
    *,
    skip_auth_logs: bool = False,
    skip_escalation: bool = False,
    include_wrong_user_read: bool = False,
    use_sparse_escalation_evidence: bool = False,
    final_response: str | None = None,
) -> AgentAttempt:
    store = EnvironmentStore.from_seed()
    scenario = load_scenario(environment_state=store.snapshot())
    initial_state = store.snapshot()
    service = SupportToolService(store)

    service.get_ticket("tkt_1001")
    service.get_user("usr_ava_chou")
    if include_wrong_user_read:
        service.get_user("usr_ava_cho")
    service.search_docs("account unlock policy lockout")
    if not skip_auth_logs:
        service.get_auth_logs("usr_ava_chou", TIME_WINDOW)
    service.get_password_reset_events("usr_ava_chou", TIME_WINDOW)
    if not skip_escalation:
        evidence = [
            "auth_1001 auth_1002 auth_1003 show failed login attempts",
            "auth_1004 shows the account lockout",
            "auth_1005 shows blocked login after reset",
            "prst_1002 shows password reset completed",
            "pol_auth_unlock_v3 requires verification before unlock",
            "identity verification is not confirmed",
        ]
        if use_sparse_escalation_evidence:
            evidence = ["identity verification is not confirmed"]
        service.escalate_case(
            "tkt_1001",
            "Identity verification is not confirmed for the locked requester.",
            evidence,
        )

    return AgentAttempt(
        scenario=scenario,
        initial_state=initial_state,
        final_state=store.snapshot(),
        tool_calls=service.call_log,
        final_response=final_response
        or (
            "Your password reset completed, but the account is locked after failed "
            "sign-in attempts. I escalated this for identity verification before "
            "any unlock."
        ),
    )


def _build_wrong_user_lockout_attempt() -> AgentAttempt:
    store = EnvironmentStore.from_seed()
    scenario = load_scenario(
        ROOT / "data" / "scenarios" / "wrong_user_lockout_v1.json",
        environment_state=store.snapshot(),
    )
    initial_state = store.snapshot()
    service = SupportToolService(store)

    service.get_ticket("tkt_1002")
    service.get_user("usr_ava_chou")
    service.search_docs("account unlock policy lockout")
    service.get_auth_logs("usr_ava_chou", TIME_WINDOW)
    service.get_password_reset_events("usr_ava_chou", TIME_WINDOW)
    service.escalate_case(
        "tkt_1002",
        "Identity verification is not confirmed for the requester.",
        [
            "tkt_1002 maps the requester to usr_ava_chou",
            "auth_1001 auth_1002 auth_1003 show failed login attempts",
            "auth_1004 shows account lockout",
            "auth_1005 shows blocked login after reset",
            "prst_1002 shows password reset completed",
            "pol_auth_unlock_v3 requires verification before unlock",
            "identity verification is not confirmed",
        ],
    )
    return AgentAttempt(
        scenario=scenario,
        initial_state=initial_state,
        final_state=store.snapshot(),
        tool_calls=service.call_log,
        final_response=(
            "The password reset completed, but the requester account is locked. "
            "I escalated this for identity verification before any unlock."
        ),
    )


def _build_verified_unlock_attempt() -> AgentAttempt:
    store = EnvironmentStore.from_seed()
    scenario = load_scenario(
        ROOT / "data" / "scenarios" / "verified_unlock_v1.json",
        environment_state=store.snapshot(),
    )
    initial_state = store.snapshot()
    service = SupportToolService(store)

    service.get_ticket("tkt_1003")
    service.get_user("usr_eli_mora")
    service.search_docs("account unlock policy lockout")
    service.get_auth_logs("usr_eli_mora", TIME_WINDOW)
    service.get_password_reset_events("usr_eli_mora", TIME_WINDOW)
    service.unlock_user(
        "usr_eli_mora",
        "Identity verification is verified and auth logs match the requester.",
    )
    return AgentAttempt(
        scenario=scenario,
        initial_state=initial_state,
        final_state=store.snapshot(),
        tool_calls=service.call_log,
        final_response=(
            "The password reset completed, and the account lockout was cleared. "
            "I unlocked the account after verified identity, so access is restored."
        ),
    )


def _build_mfa_attempt() -> AgentAttempt:
    store = EnvironmentStore.from_seed()
    scenario = load_scenario(
        ROOT / "data" / "scenarios" / "mfa_blocker_v1.json",
        environment_state=store.snapshot(),
    )
    initial_state = store.snapshot()
    service = SupportToolService(store)

    service.get_ticket("tkt_1004")
    service.get_user("usr_noah_patel")
    service.get_auth_logs("usr_noah_patel", TIME_WINDOW)
    service.get_password_reset_events("usr_noah_patel", TIME_WINDOW)
    service.get_sessions("usr_noah_patel")
    service.get_mfa_status("usr_noah_patel")
    service.search_docs("mfa recovery policy")
    service.escalate_case(
        "tkt_1004",
        "MFA challenge failure requires manual recovery.",
        [
            "prst_4001 shows password reset completed",
            "auth_4001 shows MFA challenge failure",
            "usr_noah_patel has MFA required with TOTP enrolled",
            "sess_noah_patel_0708 is expired",
            "pol_mfa_recovery_v1 requires escalation for manual MFA recovery",
        ],
    )
    return AgentAttempt(
        scenario=scenario,
        initial_state=initial_state,
        final_state=store.snapshot(),
        tool_calls=service.call_log,
        final_response=(
            "The password reset completed, and the remaining blocker is the "
            "MFA authenticator challenge. I escalated this for manual MFA "
            "recovery."
        ),
    )


if __name__ == "__main__":
    unittest.main()
