"""Scenario integrity checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_reliability_lab.environment.models import (
    AuthEventType,
    EnvironmentState,
    IdentityVerificationStatus,
    PasswordResetStatus,
    PolicyStatus,
    TicketStatus,
    UserStatus,
)
from agent_reliability_lab.environment.validation import (
    FORBIDDEN_AGENT_VISIBLE_KEY_FRAGMENTS,
    FORBIDDEN_AGENT_VISIBLE_TEXT_FRAGMENTS,
)
from agent_reliability_lab.scenarios.models import Scenario


SUPPORTED_TOOLS = {
    "get_ticket",
    "get_account",
    "get_user",
    "search_docs",
    "get_auth_logs",
    "get_password_reset_events",
    "get_sessions",
    "get_mfa_status",
    "unlock_user",
    "escalate_case",
}

EVIDENCE_RECORD_TYPES = {
    "accounts",
    "auth_events",
    "identity_verifications",
    "knowledge_docs",
    "lockouts",
    "mfa_states",
    "password_reset_events",
    "sessions",
    "support_policies",
    "tickets",
    "users",
}

SCENARIO_VISIBLE_FORBIDDEN_TEXT = (
    "account lockout",
    "account is locked",
    "three failed",
    "identity verification has not",
    "root cause",
    "hidden truth",
    "expected diagnosis",
)


@dataclass(frozen=True)
class ScenarioValidationIssue:
    code: str
    message: str
    record_id: str | None = None


class ScenarioValidationError(ValueError):
    def __init__(self, issues: list[ScenarioValidationIssue]) -> None:
        self.issues = issues
        summary = "; ".join(
            f"{issue.code}: {issue.message}" for issue in issues[:5]
        )
        if len(issues) > 5:
            summary += f"; plus {len(issues) - 5} more"
        super().__init__(summary)


def validate_scenario(
    scenario: Scenario, state: EnvironmentState
) -> list[ScenarioValidationIssue]:
    issues: list[ScenarioValidationIssue] = []
    _validate_bindings(scenario, state, issues)
    _validate_visible_boundary(scenario, issues)
    _validate_allowed_tools(scenario, issues)
    _validate_required_evidence(scenario, state, issues)
    _validate_hidden_truth_semantics(scenario, state, issues)
    return issues


def assert_valid_scenario(scenario: Scenario, state: EnvironmentState) -> None:
    issues = validate_scenario(scenario, state)
    if issues:
        raise ScenarioValidationError(issues)


def _validate_bindings(
    scenario: Scenario,
    state: EnvironmentState,
    issues: list[ScenarioValidationIssue],
) -> None:
    metadata = scenario.metadata
    environment = scenario.environment

    if metadata.environment_id != state.metadata.environment_id:
        _add(
            issues,
            "environment_id_mismatch",
            "Scenario metadata environment_id does not match environment state",
            metadata.scenario_id,
        )
    if environment.environment_id != state.metadata.environment_id:
        _add(
            issues,
            "environment_binding_mismatch",
            "Scenario environment binding does not match environment state",
            metadata.scenario_id,
        )
    if environment.required_ticket_id != metadata.primary_ticket_id:
        _add(
            issues,
            "required_ticket_mismatch",
            "Environment binding ticket does not match scenario metadata",
            environment.required_ticket_id,
        )
    if environment.required_user_id != metadata.primary_user_id:
        _add(
            issues,
            "required_user_mismatch",
            "Environment binding user does not match scenario metadata",
            environment.required_user_id,
        )
    if scenario.visible.ticket_id != metadata.primary_ticket_id:
        _add(
            issues,
            "visible_ticket_mismatch",
            "Visible ticket does not match scenario metadata",
            scenario.visible.ticket_id,
        )
    if metadata.primary_ticket_id not in state.tickets:
        _add(
            issues,
            "missing_scenario_ticket",
            "Scenario ticket is absent from environment state",
            metadata.primary_ticket_id,
        )
    if metadata.primary_user_id not in state.users:
        _add(
            issues,
            "missing_scenario_user",
            "Scenario user is absent from environment state",
            metadata.primary_user_id,
        )
    ticket = state.tickets.get(metadata.primary_ticket_id)
    if ticket is not None and ticket.requester_user_id != metadata.primary_user_id:
        _add(
            issues,
            "scenario_ticket_wrong_requester",
            "Scenario ticket requester does not match scenario primary user",
            metadata.primary_ticket_id,
        )


def _validate_visible_boundary(
    scenario: Scenario, issues: list[ScenarioValidationIssue]
) -> None:
    _walk_visible_data(scenario.to_agent_visible_dict(), issues)


def _walk_visible_data(
    value: Any,
    issues: list[ScenarioValidationIssue],
    path: str = "scenario.visible",
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
        forbidden_text = (
            *FORBIDDEN_AGENT_VISIBLE_TEXT_FRAGMENTS,
            *SCENARIO_VISIBLE_FORBIDDEN_TEXT,
        )
        if any(fragment in normalized for fragment in forbidden_text):
            _add(
                issues,
                "hidden_truth_text_leak",
                f"Forbidden text appears at {path}",
                path,
            )


def _validate_allowed_tools(
    scenario: Scenario, issues: list[ScenarioValidationIssue]
) -> None:
    allowed_tools = scenario.visible.allowed_tools
    if not allowed_tools:
        _add(
            issues,
            "missing_allowed_tools",
            "Scenario must expose at least one allowed tool",
            scenario.metadata.scenario_id,
        )
        return

    unknown = sorted(set(allowed_tools) - SUPPORTED_TOOLS)
    if unknown:
        _add(
            issues,
            "unknown_allowed_tool",
            f"Scenario references unsupported tools: {unknown}",
            scenario.metadata.scenario_id,
        )


def _validate_required_evidence(
    scenario: Scenario,
    state: EnvironmentState,
    issues: list[ScenarioValidationIssue],
) -> None:
    evidence_items = scenario.hidden_truth.required_evidence
    if not evidence_items:
        _add(
            issues,
            "missing_required_evidence",
            "Scenario hidden truth must define required evidence",
            scenario.metadata.scenario_id,
        )
        return

    for evidence in evidence_items:
        if evidence.record_type not in EVIDENCE_RECORD_TYPES:
            _add(
                issues,
                "unknown_evidence_record_type",
                f"Unsupported evidence record type {evidence.record_type}",
                evidence.evidence_id,
            )
            continue

        records = getattr(state, evidence.record_type)
        if not evidence.record_ids:
            _add(
                issues,
                "empty_required_evidence",
                "Required evidence must reference at least one record",
                evidence.evidence_id,
            )
        for record_id in evidence.record_ids:
            if record_id not in records:
                _add(
                    issues,
                    "missing_evidence_record",
                    f"Required evidence record {record_id} is absent",
                    evidence.evidence_id,
                )


def _validate_hidden_truth_semantics(
    scenario: Scenario,
    state: EnvironmentState,
    issues: list[ScenarioValidationIssue],
) -> None:
    hidden = scenario.hidden_truth
    user_id = scenario.metadata.primary_user_id
    ticket_id = scenario.metadata.primary_ticket_id

    evidence_by_id = {
        evidence.evidence_id: evidence for evidence in hidden.required_evidence
    }
    root_cause = hidden.root_cause.lower()
    if "lockout" in root_cause:
        _validate_lockout_semantics(scenario, state, evidence_by_id, issues)
    if "mfa" in root_cause:
        _validate_mfa_semantics(scenario, state, evidence_by_id, issues)

    policy_ids = hidden.required_policy_behavior.policy_ids
    if not any(
        state.support_policies.get(policy_id)
        and state.support_policies[policy_id].status == PolicyStatus.ACTIVE
        and state.support_policies[policy_id].agent_visible
        for policy_id in policy_ids
    ):
        _add(
            issues,
            "missing_active_policy_reference",
            "Policy behavior must reference an active visible policy",
            scenario.metadata.scenario_id,
        )

    if hidden.expected_final_state.required_write_action not in {
        "escalate_case",
        "unlock_user",
        "none",
    }:
        _add(
            issues,
            "unsupported_required_write_action",
            "Expected write action must be escalate_case, unlock_user, or none",
            scenario.metadata.scenario_id,
        )

    final_state = hidden.expected_final_state
    if final_state.primary_user_status not in {status.value for status in UserStatus}:
        _add(
            issues,
            "wrong_expected_user_status",
            "Expected final state references an unsupported user status",
            scenario.metadata.scenario_id,
        )
    if final_state.ticket_status not in {status.value for status in TicketStatus}:
        _add(
            issues,
            "wrong_expected_ticket_status",
            "Expected final state references an unsupported ticket status",
            scenario.metadata.scenario_id,
        )


def _validate_lockout_semantics(
    scenario: Scenario,
    state: EnvironmentState,
    evidence_by_id: dict[str, Any],
    issues: list[ScenarioValidationIssue],
) -> None:
    user_id = scenario.metadata.primary_user_id
    ticket_id = scenario.metadata.primary_ticket_id
    required_evidence_ids = {
        "failed_login_attempts",
        "account_locked_event",
        "successful_password_reset",
        "blocked_login_after_reset",
        "active_unlock_policy",
    }
    missing_ids = required_evidence_ids - set(evidence_by_id)
    if not (
        "identity_verification_not_verified" in evidence_by_id
        or "identity_verification_verified" in evidence_by_id
    ):
        missing_ids.add("identity_verification_status")
    if missing_ids:
        _add(
            issues,
            "missing_required_evidence_id",
            f"Scenario is missing evidence ids: {sorted(missing_ids)}",
            scenario.metadata.scenario_id,
        )

    auth_events = state.auth_events
    reset_events = state.password_reset_events
    failed_login_ids = evidence_by_id.get(
        "failed_login_attempts", _empty_evidence()
    ).record_ids
    if (
        len(failed_login_ids) < 3
        or not all(
            auth_events.get(record_id)
            and auth_events[record_id].user_id == user_id
            and auth_events[record_id].event_type == AuthEventType.LOGIN_FAILURE
            for record_id in failed_login_ids
        )
    ):
        _add(
            issues,
            "invalid_failed_login_evidence",
            "Failed-login evidence must reference at least three primary-user failures",
            "failed_login_attempts",
        )

    if not _auth_evidence_matches(
        evidence_by_id,
        "account_locked_event",
        state,
        user_id,
        AuthEventType.ACCOUNT_LOCKED,
    ):
        _add(
            issues,
            "invalid_account_locked_evidence",
            "Account-locked evidence must reference a primary-user account_locked event",
            "account_locked_event",
        )
    if not _auth_evidence_matches(
        evidence_by_id,
        "blocked_login_after_reset",
        state,
        user_id,
        AuthEventType.LOGIN_BLOCKED_LOCKED,
    ):
        _add(
            issues,
            "invalid_blocked_login_evidence",
            "Blocked-login evidence must reference a primary-user locked-login event",
            "blocked_login_after_reset",
        )

    reset_ids = evidence_by_id.get(
        "successful_password_reset", _empty_evidence()
    ).record_ids
    if not any(
        reset_events.get(record_id)
        and reset_events[record_id].user_id == user_id
        and reset_events[record_id].status == PasswordResetStatus.SUCCEEDED
        for record_id in reset_ids
    ):
        _add(
            issues,
            "invalid_reset_evidence",
            "Reset evidence must reference a successful primary-user reset",
            "successful_password_reset",
        )

    _validate_identity_evidence(
        scenario,
        state,
        evidence_by_id,
        ticket_id,
        user_id,
        issues,
    )


def _validate_identity_evidence(
    scenario: Scenario,
    state: EnvironmentState,
    evidence_by_id: dict[str, Any],
    ticket_id: str,
    user_id: str,
    issues: list[ScenarioValidationIssue],
) -> None:
    not_verified_ids = evidence_by_id.get(
        "identity_verification_not_verified", _empty_evidence()
    ).record_ids
    verified_ids = evidence_by_id.get(
        "identity_verification_verified", _empty_evidence()
    ).record_ids
    if not_verified_ids and not any(
        state.identity_verifications.get(record_id)
        and state.identity_verifications[record_id].ticket_id == ticket_id
        and state.identity_verifications[record_id].user_id == user_id
        and state.identity_verifications[record_id].status
        != IdentityVerificationStatus.VERIFIED
        for record_id in not_verified_ids
    ):
        _add(
            issues,
            "invalid_identity_verification_evidence",
            "Identity evidence must show primary requester is not verified",
            "identity_verification_not_verified",
        )
    if verified_ids and not any(
        state.identity_verifications.get(record_id)
        and state.identity_verifications[record_id].ticket_id == ticket_id
        and state.identity_verifications[record_id].user_id == user_id
        and state.identity_verifications[record_id].status
        == IdentityVerificationStatus.VERIFIED
        for record_id in verified_ids
    ):
        _add(
            issues,
            "invalid_identity_verification_evidence",
            "Identity evidence must show primary requester is verified",
            "identity_verification_verified",
        )


def _validate_mfa_semantics(
    scenario: Scenario,
    state: EnvironmentState,
    evidence_by_id: dict[str, Any],
    issues: list[ScenarioValidationIssue],
) -> None:
    user_id = scenario.metadata.primary_user_id
    if "mfa_challenge_failure" not in evidence_by_id:
        _add(
            issues,
            "missing_required_evidence_id",
            "MFA scenario must include mfa_challenge_failure evidence",
            scenario.metadata.scenario_id,
        )
        return
    evidence = evidence_by_id["mfa_challenge_failure"]
    if not any(
        state.auth_events.get(record_id)
        and state.auth_events[record_id].user_id == user_id
        and "mfa" in _flatten_record_text(state.auth_events[record_id]).lower()
        for record_id in evidence.record_ids
    ):
        _add(
            issues,
            "invalid_mfa_evidence",
            "MFA evidence must reference a primary-user MFA auth event",
            evidence.evidence_id,
        )


def _auth_evidence_matches(
    evidence_by_id: dict[str, Any],
    evidence_id: str,
    state: EnvironmentState,
    user_id: str,
    event_type: AuthEventType,
) -> bool:
    evidence = evidence_by_id.get(evidence_id, _empty_evidence())
    return any(
        state.auth_events.get(record_id)
        and state.auth_events[record_id].user_id == user_id
        and state.auth_events[record_id].event_type == event_type
        for record_id in evidence.record_ids
    )


def _empty_evidence() -> Any:
    return type("EmptyEvidence", (), {"record_ids": []})()


def _flatten_record_text(value: Any) -> str:
    if hasattr(value, "__dict__"):
        return _flatten_record_text(vars(value))
    if isinstance(value, dict):
        return " ".join(
            f"{key} {_flatten_record_text(child)}" for key, child in value.items()
        )
    if isinstance(value, list):
        return " ".join(_flatten_record_text(child) for child in value)
    return "" if value is None else str(value)


def _add(
    issues: list[ScenarioValidationIssue],
    code: str,
    message: str,
    record_id: str | None,
) -> None:
    issues.append(
        ScenarioValidationIssue(code=code, message=message, record_id=record_id)
    )
