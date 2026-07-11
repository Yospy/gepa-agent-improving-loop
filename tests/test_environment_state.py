from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.environment import (  # noqa: E402
    EnvironmentStore,
    load_seed_state,
    validate_environment,
)
from agent_reliability_lab.environment.models import (  # noqa: E402
    AuthEventType,
    DocumentStatus,
    EnvironmentState,
    IdentityVerificationStatus,
    PasswordResetStatus,
    UserStatus,
)


class EnvironmentStateTests(unittest.TestCase):
    def test_seed_loads_and_validates(self) -> None:
        state = load_seed_state()

        self.assertEqual(validate_environment(state), [])
        self.assertEqual(state.metadata.primary_ticket_id, "tkt_1001")
        self.assertEqual(state.metadata.primary_user_id, "usr_ava_chou")

    def test_reset_restores_original_hash(self) -> None:
        store = EnvironmentStore.from_seed()
        original_hash = store.state_hash()

        primary_user = store.state.users[store.state.metadata.primary_user_id]
        primary_user.status = UserStatus.ACTIVE

        self.assertNotEqual(store.state_hash(), original_hash)
        store.reset()
        self.assertEqual(store.state_hash(), original_hash)
        self.assertEqual(
            store.state.users[store.state.metadata.primary_user_id].status,
            UserStatus.LOCKED,
        )

    def test_snapshot_is_mutation_safe(self) -> None:
        store = EnvironmentStore.from_seed()
        snapshot = store.snapshot()

        snapshot.users[snapshot.metadata.primary_user_id].status = UserStatus.ACTIVE

        self.assertEqual(
            store.state.users[store.state.metadata.primary_user_id].status,
            UserStatus.LOCKED,
        )

    def test_primary_scenario_has_required_evidence_chain(self) -> None:
        state = load_seed_state()
        user_id = state.metadata.primary_user_id
        auth_events = sorted(
            [event for event in state.auth_events.values() if event.user_id == user_id],
            key=lambda event: event.occurred_at,
        )
        reset_events = [
            event
            for event in state.password_reset_events.values()
            if event.user_id == user_id
        ]

        self.assertGreaterEqual(
            sum(
                event.event_type == AuthEventType.LOGIN_FAILURE
                for event in auth_events
            ),
            3,
        )
        self.assertTrue(
            any(event.event_type == AuthEventType.ACCOUNT_LOCKED for event in auth_events)
        )
        self.assertTrue(
            any(event.status == PasswordResetStatus.SUCCEEDED for event in reset_events)
        )
        self.assertTrue(
            any(
                event.event_type == AuthEventType.LOGIN_BLOCKED_LOCKED
                for event in auth_events
            )
        )

    def test_environment_has_realistic_failure_traps(self) -> None:
        state = load_seed_state()
        primary_user = state.users[state.metadata.primary_user_id]
        account = state.accounts[primary_user.account_id]
        same_domain_users = [
            user
            for user in state.users.values()
            if user.user_id != primary_user.user_id
            and user.account_id == primary_user.account_id
            and user.email.endswith(f"@{account.domain}")
        ]
        deprecated_unlock_docs = [
            doc
            for doc in state.knowledge_docs.values()
            if doc.status == DocumentStatus.DEPRECATED
            and "unlock" in f"{doc.title} {doc.content}".lower()
        ]

        self.assertTrue(same_domain_users)
        self.assertTrue(deprecated_unlock_docs)

    def test_environment_seed_has_no_hidden_truth_keys(self) -> None:
        state = load_seed_state()
        keys = _flatten_keys(state.to_seed_dict())
        forbidden_fragments = (
            "hidden",
            "ground_truth",
            "expected_answer",
            "expected_diagnosis",
            "evaluator_only",
            "answer_key",
            "root_cause",
        )

        leaked = [
            key
            for key in keys
            if any(fragment in key.lower() for fragment in forbidden_fragments)
        ]
        self.assertEqual(leaked, [])

    def test_raw_top_level_extra_keys_are_rejected(self) -> None:
        seed_path = ROOT / "data" / "environment" / "support_env_v1.json"
        raw_seed = json.loads(seed_path.read_text(encoding="utf-8"))
        raw_seed["hidden_truth"] = {"diagnosis": "account_lockout"}

        with self.assertRaises(ValueError):
            EnvironmentState.from_dict(raw_seed)

    def test_primary_identity_verification_state_is_explicit(self) -> None:
        state = load_seed_state()
        verification_records = [
            verification
            for verification in state.identity_verifications.values()
            if verification.ticket_id == state.metadata.primary_ticket_id
            and verification.user_id == state.metadata.primary_user_id
        ]

        self.assertEqual(len(verification_records), 1)
        self.assertEqual(
            verification_records[0].status,
            IdentityVerificationStatus.NOT_STARTED,
        )

    def test_validator_rejects_critical_scenario_regressions(self) -> None:
        base_state = load_seed_state()

        def remove_lockout(state: EnvironmentState) -> None:
            state.lockouts[state.metadata.primary_user_id].is_locked = False

        def remove_successful_reset(state: EnvironmentState) -> None:
            for event in state.password_reset_events.values():
                if event.user_id == state.metadata.primary_user_id:
                    event.status = PasswordResetStatus.REQUESTED

        def remove_blocked_login_after_reset(state: EnvironmentState) -> None:
            state.auth_events["auth_1005"].event_type = AuthEventType.LOGIN_SUCCESS

        def mismatch_requester(state: EnvironmentState) -> None:
            state.tickets[state.metadata.primary_ticket_id].requester_user_id = (
                "usr_ava_cho"
            )

        def weaken_wrong_user_trap(state: EnvironmentState) -> None:
            state.users["usr_ava_cho"].full_name = "Renee Cole"
            state.users["usr_ava_cho"].email = "renee.cole@acme-analytics.example"

        cases = [
            ("missing_active_lockout", remove_lockout),
            ("missing_successful_reset", remove_successful_reset),
            ("missing_blocked_login_after_reset", remove_blocked_login_after_reset),
            ("primary_ticket_wrong_requester", mismatch_requester),
            ("missing_wrong_user_trap", weaken_wrong_user_trap),
        ]

        for expected_code, mutate in cases:
            with self.subTest(expected_code=expected_code):
                state = deepcopy(base_state)
                mutate(state)
                issue_codes = {issue.code for issue in validate_environment(state)}

                self.assertIn(expected_code, issue_codes)

    def test_validation_rejects_hidden_truth_text_leak(self) -> None:
        state = load_seed_state()
        state.auth_events["auth_1001"].details["debug_note"] = (
            "true root cause is account lockout"
        )

        issue_codes = {issue.code for issue in validate_environment(state)}

        self.assertIn("hidden_truth_text_leak", issue_codes)

    def test_naive_datetime_is_rejected_during_serialization(self) -> None:
        state = load_seed_state()
        state.metadata.seeded_at = datetime(2026, 7, 8, 9, 30, 0)

        with self.assertRaises(ValueError):
            state.to_seed_dict()


def _flatten_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        keys: list[str] = []
        for key, child in value.items():
            keys.append(str(key))
            keys.extend(_flatten_keys(child))
        return keys
    if isinstance(value, list):
        keys = []
        for child in value:
            keys.extend(_flatten_keys(child))
        return keys
    return []


if __name__ == "__main__":
    unittest.main()
