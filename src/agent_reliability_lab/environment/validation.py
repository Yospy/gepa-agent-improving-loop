"""Environment integrity checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_reliability_lab.environment.models import (
    AuthEvent,
    AuthEventType,
    DocumentStatus,
    EnvironmentState,
    IdentityVerificationStatus,
    PasswordResetStatus,
    PolicyStatus,
    UserStatus,
)


FORBIDDEN_AGENT_VISIBLE_KEY_FRAGMENTS = (
    "hidden",
    "ground_truth",
    "expected_answer",
    "expected_diagnosis",
    "evaluator_only",
    "answer_key",
    "root_cause",
)

FORBIDDEN_AGENT_VISIBLE_TEXT_FRAGMENTS = (
    "hidden truth",
    "evaluator only",
    "evaluator-only",
    "expected answer",
    "answer key",
    "correct diagnosis",
    "true root cause",
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    record_id: str | None = None


class EnvironmentValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        summary = "; ".join(
            f"{issue.code}: {issue.message}" for issue in issues[:5]
        )
        if len(issues) > 5:
            summary += f"; plus {len(issues) - 5} more"
        super().__init__(summary)


def validate_environment(state: EnvironmentState) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _validate_references(state, issues)
    _validate_agent_visible_boundary(state, issues)
    _validate_primary_login_lockout_invariant(state, issues)
    return issues


def assert_valid_environment(state: EnvironmentState) -> None:
    issues = validate_environment(state)
    if issues:
        raise EnvironmentValidationError(issues)


def _validate_references(
    state: EnvironmentState, issues: list[ValidationIssue]
) -> None:
    for organization in state.organizations.values():
        for account_id in organization.account_ids:
            if account_id not in state.accounts:
                _add(
                    issues,
                    "missing_org_account",
                    f"Organization references missing account {account_id}",
                    organization.organization_id,
                )

    for account in state.accounts.values():
        if account.organization_id not in state.organizations:
            _add(
                issues,
                "missing_account_org",
                f"Account references missing organization {account.organization_id}",
                account.account_id,
            )

    for user in state.users.values():
        if user.account_id not in state.accounts:
            _add(
                issues,
                "missing_user_account",
                f"User references missing account {user.account_id}",
                user.user_id,
            )

    for ticket in state.tickets.values():
        if ticket.account_id not in state.accounts:
            _add(
                issues,
                "missing_ticket_account",
                f"Ticket references missing account {ticket.account_id}",
                ticket.ticket_id,
            )
        if ticket.requester_user_id not in state.users:
            _add(
                issues,
                "missing_ticket_requester",
                f"Ticket references missing user {ticket.requester_user_id}",
                ticket.ticket_id,
            )
        elif state.users[ticket.requester_user_id].account_id != ticket.account_id:
            _add(
                issues,
                "ticket_requester_account_mismatch",
                "Ticket requester does not belong to ticket account",
                ticket.ticket_id,
            )

    for event in state.auth_events.values():
        _validate_user_account_pair(
            state, issues, event.user_id, event.account_id, event.event_id
        )

    for event in state.password_reset_events.values():
        _validate_user_account_pair(
            state, issues, event.user_id, event.account_id, event.event_id
        )

    for verification in state.identity_verifications.values():
        _validate_user_account_pair(
            state,
            issues,
            verification.user_id,
            verification.account_id,
            verification.verification_id,
        )
        if verification.ticket_id not in state.tickets:
            _add(
                issues,
                "missing_verification_ticket",
                f"Verification references missing ticket {verification.ticket_id}",
                verification.verification_id,
            )
        elif state.tickets[verification.ticket_id].account_id != verification.account_id:
            _add(
                issues,
                "verification_ticket_account_mismatch",
                "Verification ticket does not belong to verification account",
                verification.verification_id,
            )

    for lockout in state.lockouts.values():
        _validate_user_account_pair(
            state, issues, lockout.user_id, lockout.account_id, lockout.user_id
        )

    for mfa_state in state.mfa_states.values():
        _validate_user_account_pair(
            state, issues, mfa_state.user_id, mfa_state.account_id, mfa_state.user_id
        )

    for session in state.sessions.values():
        _validate_user_account_pair(
            state, issues, session.user_id, session.account_id, session.session_id
        )


def _validate_user_account_pair(
    state: EnvironmentState,
    issues: list[ValidationIssue],
    user_id: str,
    account_id: str,
    record_id: str,
) -> None:
    if user_id not in state.users:
        _add(
            issues,
            "missing_user",
            f"Record references missing user {user_id}",
            record_id,
        )
        return
    if account_id not in state.accounts:
        _add(
            issues,
            "missing_account",
            f"Record references missing account {account_id}",
            record_id,
        )
        return
    if state.users[user_id].account_id != account_id:
        _add(
            issues,
            "user_account_mismatch",
            f"User {user_id} does not belong to account {account_id}",
            record_id,
        )


def _validate_agent_visible_boundary(
    state: EnvironmentState, issues: list[ValidationIssue]
) -> None:
    _walk_visible_data(state.to_seed_dict(), issues)


def _walk_visible_data(
    value: Any, issues: list[ValidationIssue], path: str = "environment"
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower()
            if any(
                fragment in normalized
                for fragment in FORBIDDEN_AGENT_VISIBLE_KEY_FRAGMENTS
            ):
                _add(
                    issues,
                    "hidden_truth_key_leak",
                    f"Forbidden key {key!r} appears at {path}",
                    path,
                )
            _walk_visible_data(child, issues, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_visible_data(child, issues, f"{path}[{index}]")
    elif isinstance(value, str):
        normalized = value.lower()
        if any(
            fragment in normalized
            for fragment in FORBIDDEN_AGENT_VISIBLE_TEXT_FRAGMENTS
        ):
            _add(
                issues,
                "hidden_truth_text_leak",
                f"Forbidden text appears at {path}",
                path,
            )


def _validate_primary_login_lockout_invariant(
    state: EnvironmentState, issues: list[ValidationIssue]
) -> None:
    primary_user_id = state.metadata.primary_user_id
    primary_ticket_id = state.metadata.primary_ticket_id

    if primary_user_id not in state.users:
        _add(
            issues,
            "missing_primary_user",
            f"Primary user {primary_user_id} is absent",
            primary_user_id,
        )
        return
    if primary_ticket_id not in state.tickets:
        _add(
            issues,
            "missing_primary_ticket",
            f"Primary ticket {primary_ticket_id} is absent",
            primary_ticket_id,
        )
        return

    user = state.users[primary_user_id]
    ticket = state.tickets[primary_ticket_id]
    lockout = state.lockouts.get(primary_user_id)
    auth_events = _events_for_user(state, primary_user_id)
    reset_events = [
        event
        for event in state.password_reset_events.values()
        if event.user_id == primary_user_id
    ]

    if ticket.requester_user_id != primary_user_id:
        _add(
            issues,
            "primary_ticket_wrong_requester",
            "Primary ticket requester is not the primary scenario user",
            primary_ticket_id,
        )
    if "reset" not in ticket.body.lower() or "log in" not in ticket.body.lower():
        _add(
            issues,
            "primary_ticket_weak_prompt",
            "Primary ticket does not clearly express reset followed by login failure",
            primary_ticket_id,
        )

    if user.status != UserStatus.LOCKED:
        _add(
            issues,
            "primary_user_not_locked",
            "Primary user must begin locked for the login-lockout scenario",
            primary_user_id,
        )
    if lockout is None or not lockout.is_locked:
        _add(
            issues,
            "missing_active_lockout",
            "Primary user needs an active lockout state",
            primary_user_id,
        )
        return

    failed_before_lock = [
        event
        for event in auth_events
        if event.event_type == AuthEventType.LOGIN_FAILURE
        and lockout.locked_at is not None
        and event.occurred_at <= lockout.locked_at
    ]
    locked_events = [
        event for event in auth_events if event.event_type == AuthEventType.ACCOUNT_LOCKED
    ]
    blocked_after_reset = _blocked_login_after_successful_reset(auth_events, reset_events)
    verification_records = [
        verification
        for verification in state.identity_verifications.values()
        if verification.ticket_id == primary_ticket_id
        and verification.user_id == primary_user_id
    ]

    if len(failed_before_lock) < 3:
        _add(
            issues,
            "insufficient_failed_login_evidence",
            "Primary user needs at least three failed login events before lockout",
            primary_user_id,
        )
    if lockout.failed_attempt_count != len(failed_before_lock):
        _add(
            issues,
            "lockout_count_mismatch",
            "Lockout failed_attempt_count must match failed login evidence",
            primary_user_id,
        )
    if not locked_events:
        _add(
            issues,
            "missing_auth_lock_event",
            "Auth logs must include an account_locked event",
            primary_user_id,
        )
    elif lockout.locked_at is not None and not any(
        event.occurred_at == lockout.locked_at for event in locked_events
    ):
        _add(
            issues,
            "lockout_timestamp_mismatch",
            "Lockout state timestamp must match an auth account_locked event",
            primary_user_id,
        )
    if not any(event.status == PasswordResetStatus.SUCCEEDED for event in reset_events):
        _add(
            issues,
            "missing_successful_reset",
            "Password reset evidence must include a successful reset",
            primary_user_id,
        )
    if not blocked_after_reset:
        _add(
            issues,
            "missing_blocked_login_after_reset",
            "Auth logs must show a locked-account login block after reset success",
            primary_user_id,
        )
    if lockout.unlock_requires_verified_requester and not verification_records:
        _add(
            issues,
            "missing_identity_verification_state",
            "Lockout policy requires explicit identity verification state",
            primary_user_id,
        )

    _validate_traps(state, issues)


def _events_for_user(state: EnvironmentState, user_id: str) -> list[AuthEvent]:
    return sorted(
        [event for event in state.auth_events.values() if event.user_id == user_id],
        key=lambda event: event.occurred_at,
    )


def _blocked_login_after_successful_reset(
    auth_events: list[AuthEvent], reset_events: list[Any]
) -> bool:
    successful_reset_times = [
        event.completed_at
        for event in reset_events
        if event.status == PasswordResetStatus.SUCCEEDED and event.completed_at is not None
    ]
    if not successful_reset_times:
        return False
    first_successful_reset = min(successful_reset_times)
    return any(
        event.event_type == AuthEventType.LOGIN_BLOCKED_LOCKED
        and event.occurred_at > first_successful_reset
        for event in auth_events
    )


def _validate_traps(
    state: EnvironmentState, issues: list[ValidationIssue]
) -> None:
    primary_user = state.users[state.metadata.primary_user_id]
    primary_account = state.accounts[primary_user.account_id]
    same_account_other_users = [
        user
        for user in state.users.values()
        if user.account_id == primary_user.account_id
        and user.user_id != primary_user.user_id
        and user.email.endswith(f"@{primary_account.domain}")
        and _looks_confusable(
            primary_user.full_name,
            primary_user.email,
            user.full_name,
            user.email,
        )
    ]
    deprecated_unlock_docs = [
        doc
        for doc in state.knowledge_docs.values()
        if doc.status == DocumentStatus.DEPRECATED
        and "unlock" in f"{doc.title} {doc.content}".lower()
    ]
    active_unlock_policies = [
        policy
        for policy in state.support_policies.values()
        if policy.status == PolicyStatus.ACTIVE
        and policy.agent_visible
        and "unlock" in f"{policy.title} {' '.join(policy.rules)}".lower()
    ]

    if not same_account_other_users:
        _add(
            issues,
            "missing_wrong_user_trap",
            "Seed needs a same-account user that can be confused with the requester",
            primary_user.user_id,
        )
    if not deprecated_unlock_docs:
        _add(
            issues,
            "missing_deprecated_doc_trap",
            "Seed needs a deprecated unlock doc trap",
            None,
        )
    if not active_unlock_policies:
        _add(
            issues,
            "missing_active_unlock_policy",
            "Seed needs an active agent-visible unlock policy",
            None,
        )


def identity_is_verified_for_ticket(
    state: EnvironmentState, user_id: str, ticket_id: str
) -> bool:
    return any(
        verification.user_id == user_id
        and verification.ticket_id == ticket_id
        and verification.status == IdentityVerificationStatus.VERIFIED
        for verification in state.identity_verifications.values()
    )


def _looks_confusable(
    primary_name: str, primary_email: str, candidate_name: str, candidate_email: str
) -> bool:
    primary_first_name = primary_name.split()[0].lower()
    candidate_first_name = candidate_name.split()[0].lower()
    primary_local = _normalized_email_local(primary_email)
    candidate_local = _normalized_email_local(candidate_email)

    if primary_first_name == candidate_first_name:
        return True
    shared_prefix_length = min(len(primary_local), len(candidate_local), 5)
    return shared_prefix_length >= 5 and (
        primary_local[:shared_prefix_length] == candidate_local[:shared_prefix_length]
    )


def _normalized_email_local(email: str) -> str:
    return "".join(
        character
        for character in email.split("@", 1)[0].lower()
        if character.isalnum()
    )


def _add(
    issues: list[ValidationIssue], code: str, message: str, record_id: str | None
) -> None:
    issues.append(ValidationIssue(code=code, message=message, record_id=record_id))
