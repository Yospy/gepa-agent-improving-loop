from __future__ import annotations

from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.environment import (  # noqa: E402
    EnvironmentStore,
    SupportToolService,
)
from agent_reliability_lab.environment.models import (  # noqa: E402
    IdentityVerificationStatus,
    TicketStatus,
    UserStatus,
)


FIXED_NOW = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)


class SupportToolServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EnvironmentStore.from_seed()
        self.tools = SupportToolService(
            self.store,
            actor_id="agent:test",
            clock=lambda: FIXED_NOW,
        )

    def test_read_tools_return_visible_records_and_log_calls(self) -> None:
        ticket = self.tools.get_ticket("tkt_1001")
        account = self.tools.get_account("acct_acme_prod")
        user = self.tools.get_user("usr_ava_chou")
        mfa = self.tools.get_mfa_status("usr_ava_chou")
        sessions = self.tools.get_sessions("usr_ava_chou")

        self.assertTrue(ticket.ok)
        self.assertEqual(ticket.data["requester_user_id"], "usr_ava_chou")
        self.assertTrue(account.ok)
        self.assertEqual(account.data["support_tier"], "enterprise")
        self.assertTrue(user.ok)
        self.assertEqual(user.data["status"], "locked")
        self.assertTrue(mfa.ok)
        self.assertTrue(mfa.data["required"])
        self.assertTrue(sessions.ok)
        self.assertEqual(len(sessions.data["sessions"]), 1)

        self.assertEqual(len(self.tools.call_log), 5)
        self.assertTrue(all(record.ok for record in self.tools.call_log))

    def test_auth_and_reset_tools_filter_by_time_window(self) -> None:
        time_window = {
            "start_at": "2026-07-08T08:30:00Z",
            "end_at": "2026-07-08T08:45:00Z",
        }

        auth_logs = self.tools.get_auth_logs("usr_ava_chou", time_window)
        reset_events = self.tools.get_password_reset_events(
            "usr_ava_chou", time_window
        )

        self.assertTrue(auth_logs.ok)
        self.assertEqual(
            [event["event_id"] for event in auth_logs.data["events"]],
            ["auth_1001", "auth_1002", "auth_1003", "auth_1004", "auth_1005"],
        )
        self.assertTrue(reset_events.ok)
        self.assertEqual(
            [event["status"] for event in reset_events.data["events"]],
            ["requested", "succeeded"],
        )

    def test_search_docs_returns_policy_and_deprecated_trap(self) -> None:
        result = self.tools.search_docs("unlock account policy")

        self.assertTrue(result.ok)
        record_ids = {
            item.get("policy_id") or item.get("doc_id")
            for item in result.data["results"]
        }
        self.assertIn("pol_auth_unlock_v3", record_ids)
        self.assertIn("doc_unlock_legacy_2019", record_ids)

    def test_unknown_user_returns_error_and_is_logged(self) -> None:
        result = self.tools.get_user("usr_missing")

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "user_not_found")
        self.assertEqual(len(self.tools.call_log), 1)
        self.assertFalse(self.tools.call_log[0].ok)
        self.assertEqual(self.tools.call_log[0].error.code, "user_not_found")

    def test_invalid_time_window_returns_error_and_is_logged(self) -> None:
        result = self.tools.get_auth_logs(
            "usr_ava_chou",
            {
                "start_at": "2026-07-08T08:30:00",
                "end_at": "2026-07-08T08:45:00Z",
            },
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "invalid_time_window")
        self.assertEqual(len(self.tools.call_log), 1)
        self.assertFalse(self.tools.call_log[0].ok)

    def test_unlock_user_denied_without_verified_identity(self) -> None:
        result = self.tools.unlock_user(
            "usr_ava_chou",
            "Customer cannot log in after password reset.",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "identity_verification_required")
        self.assertEqual(
            self.store.state.users["usr_ava_chou"].status,
            UserStatus.LOCKED,
        )
        self.assertTrue(self.store.state.lockouts["usr_ava_chou"].is_locked)
        self.assertTrue(
            any(
                entry.action == "unlock_user_denied"
                for entry in self.store.state.audit_log.values()
            )
        )

    def test_unlock_user_succeeds_after_verified_identity(self) -> None:
        self.store.state.identity_verifications["idv_1001"].status = (
            IdentityVerificationStatus.VERIFIED
        )
        self.store.state.identity_verifications["idv_1001"].verified_by = (
            "agent:test"
        )

        result = self.tools.unlock_user(
            "usr_ava_chou",
            "Verified requester and lockout evidence confirmed.",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.data["status"], "active")
        self.assertEqual(
            self.store.state.users["usr_ava_chou"].status,
            UserStatus.ACTIVE,
        )
        self.assertFalse(self.store.state.lockouts["usr_ava_chou"].is_locked)
        self.assertTrue(
            any(
                entry.action == "user_unlocked"
                for entry in self.store.state.audit_log.values()
            )
        )

    def test_escalate_case_mutates_ticket_and_audit_log(self) -> None:
        result = self.tools.escalate_case(
            "tkt_1001",
            "Identity verification is not complete.",
            ["auth_1004", "prst_1002", "pol_auth_unlock_v3"],
        )

        ticket = self.store.state.tickets["tkt_1001"]
        self.assertTrue(result.ok)
        self.assertEqual(ticket.status, TicketStatus.PENDING)
        self.assertEqual(ticket.notes[-1].note_id, result.data["note_id"])
        self.assertTrue(
            any(
                entry.action == "case_escalated"
                for entry in self.store.state.audit_log.values()
            )
        )

    def test_tool_outputs_do_not_contain_hidden_truth_markers(self) -> None:
        outputs = [
            self.tools.get_ticket("tkt_1001").to_dict(),
            self.tools.get_account("acct_acme_prod").to_dict(),
            self.tools.get_user("usr_ava_chou").to_dict(),
            self.tools.search_docs("password reset login unlock").to_dict(),
            self.tools.get_auth_logs(
                "usr_ava_chou",
                {
                    "start_at": "2026-07-08T08:30:00Z",
                    "end_at": "2026-07-08T08:45:00Z",
                },
            ).to_dict(),
            self.tools.get_password_reset_events(
                "usr_ava_chou",
                {
                    "start_at": "2026-07-08T08:30:00Z",
                    "end_at": "2026-07-08T08:45:00Z",
                },
            ).to_dict(),
            self.tools.get_sessions("usr_ava_chou").to_dict(),
            self.tools.get_mfa_status("usr_ava_chou").to_dict(),
        ]

        visible_text = repr(outputs).lower()
        forbidden_fragments = (
            "hidden truth",
            "evaluator only",
            "expected answer",
            "answer key",
            "correct diagnosis",
            "true root cause",
            "ground_truth",
        )

        for fragment in forbidden_fragments:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, visible_text)


if __name__ == "__main__":
    unittest.main()
