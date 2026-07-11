"""Deterministic offline baseline support agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping

from agent_reliability_lab.environment.models import format_utc, parse_utc
from agent_reliability_lab.environment.tools import SupportToolService, ToolResult


BASELINE_AGENT_NAME = "baseline_support_agent"
BASELINE_AGENT_VERSION = "baseline-support-v1"

REQUIRED_TOOLS = {
    "get_ticket",
    "get_account",
    "get_user",
    "search_docs",
    "get_auth_logs",
    "get_password_reset_events",
    "get_sessions",
    "get_mfa_status",
    "escalate_case",
}


class BaselineAgentError(RuntimeError):
    """Raised when the deterministic baseline cannot complete its workflow."""


@dataclass(frozen=True)
class BaselineAgentResult:
    agent_name: str
    agent_version: str
    final_response: str


class BaselineSupportAgent:
    """Reference agent for the local login-reliability scenario suite.

    This is intentionally deterministic. Its job is to prove the local
    environment, tools, evaluator, and recorder form a complete loop before any
    model-driven agent is introduced. Decisions use only agent-facing support
    records; write tools remain the final policy-enforcement boundary.
    """

    agent_name = BASELINE_AGENT_NAME
    agent_version = BASELINE_AGENT_VERSION

    def __init__(self, tools: SupportToolService) -> None:
        self._tools = tools

    def run(self, visible_scenario: Mapping[str, Any]) -> BaselineAgentResult:
        self._assert_required_tools_available(visible_scenario)

        ticket_id = _required_string(visible_scenario, "ticket_id")
        ticket = self._require_ok(self._tools.get_ticket(ticket_id))
        account_id = _required_payload_string(ticket, "account_id")
        user_id = _required_payload_string(ticket, "requester_user_id")

        self._require_ok(self._tools.get_account(account_id))
        self._require_ok(self._tools.get_user(user_id))
        sessions = self._require_ok(self._tools.get_sessions(user_id))
        mfa_status = self._require_ok(self._tools.get_mfa_status(user_id))

        time_window = _investigation_window(ticket)
        auth_logs = self._require_ok(
            self._tools.get_auth_logs(user_id, time_window)
        )
        reset_events = self._require_ok(
            self._tools.get_password_reset_events(user_id, time_window)
        )
        if _has_mfa_challenge_failure(auth_logs):
            docs = self._require_ok(
                self._tools.search_docs(
                    "MFA login recovery authenticator challenge policy",
                    include_deprecated=False,
                )
            )
            evidence = _build_mfa_escalation_evidence(
                auth_logs=auth_logs,
                reset_events=reset_events,
                sessions=sessions,
                mfa_status=mfa_status,
                docs=docs,
            )
            self._require_ok(
                self._tools.escalate_case(
                    ticket_id,
                    "MFA challenge failure requires manual recovery.",
                    evidence,
                )
            )
            return BaselineAgentResult(
                agent_name=self.agent_name,
                agent_version=self.agent_version,
                final_response=(
                    "Your password reset completed successfully, but the MFA "
                    "authenticator challenge is blocking login; the account is "
                    "not locked. I escalated this for manual MFA recovery."
                ),
            )

        docs = self._require_ok(
            self._tools.search_docs(
                "account unlock policy lockout identity verification",
                include_deprecated=True,
            )
        )
        if _has_trusted_verified_requester_tag(ticket):
            self._require_ok(
                self._tools.unlock_user(
                    user_id,
                    "Verified requester remains locked after a successful reset.",
                )
            )
            return BaselineAgentResult(
                agent_name=self.agent_name,
                agent_version=self.agent_version,
                final_response=(
                    "Your password reset completed successfully, but the account "
                    "remained locked after failed sign-in attempts. Identity "
                    "verification was recorded, so I unlocked the account and "
                    "restored access."
                ),
            )

        evidence = _build_lockout_escalation_evidence(
            auth_logs=auth_logs,
            reset_events=reset_events,
            docs=docs,
        )
        self._require_ok(
            self._tools.escalate_case(
                ticket_id,
                "Identity verification is not confirmed for the locked requester.",
                evidence,
            )
        )
        return BaselineAgentResult(
            agent_name=self.agent_name,
            agent_version=self.agent_version,
            final_response=(
                "Your password reset completed successfully, but the account is "
                "locked after failed sign-in attempts. I escalated this for "
                "identity verification before any unlock."
            ),
        )

    def _assert_required_tools_available(
        self, visible_scenario: Mapping[str, Any]
    ) -> None:
        allowed_tools = visible_scenario.get("allowed_tools")
        if not isinstance(allowed_tools, list):
            raise BaselineAgentError("visible scenario must include allowed_tools")
        missing = sorted(REQUIRED_TOOLS - set(allowed_tools))
        if missing:
            raise BaselineAgentError(f"baseline required tools are missing: {missing}")

    def _require_ok(self, result: ToolResult) -> Any:
        if result.ok:
            return result.data
        code = result.error.code if result.error else "unknown_tool_error"
        message = result.error.message if result.error else "tool call failed"
        raise BaselineAgentError(f"{result.tool_name} failed: {code}: {message}")


def _investigation_window(ticket: Mapping[str, Any]) -> dict[str, str]:
    created_at = parse_utc(_required_payload_string(ticket, "created_at"))
    return {
        "start_at": format_utc(created_at - timedelta(hours=2)),
        "end_at": format_utc(created_at + timedelta(minutes=5)),
    }


def _build_lockout_escalation_evidence(
    *,
    auth_logs: Mapping[str, Any],
    reset_events: Mapping[str, Any],
    docs: Mapping[str, Any],
) -> list[str]:
    auth_events = _payload_list(auth_logs, "events")
    reset_records = _payload_list(reset_events, "events")
    doc_results = _payload_list(docs, "results")

    failed_login_ids = [
        event["event_id"]
        for event in auth_events
        if event.get("event_type") == "login_failure"
    ]
    account_locked_ids = [
        event["event_id"]
        for event in auth_events
        if event.get("event_type") == "account_locked"
    ]
    blocked_login_ids = [
        event["event_id"]
        for event in auth_events
        if event.get("event_type") == "login_blocked_locked"
    ]
    successful_reset_ids = [
        event["event_id"]
        for event in reset_records
        if event.get("status") == "succeeded"
    ]
    active_policy_ids = [
        record["policy_id"]
        for record in doc_results
        if record.get("record_type") == "support_policy"
        and record.get("status") == "active"
    ]

    return [
        f"{_join_ids(failed_login_ids)} show failed login attempts",
        f"{_join_ids(account_locked_ids)} shows the account lockout",
        f"{_join_ids(blocked_login_ids)} shows blocked login after reset",
        f"{_join_ids(successful_reset_ids)} shows password reset completed",
        f"{_join_ids(active_policy_ids)} requires verification before unlock",
        "identity verification is not confirmed",
    ]


def _build_mfa_escalation_evidence(
    *,
    auth_logs: Mapping[str, Any],
    reset_events: Mapping[str, Any],
    sessions: Mapping[str, Any],
    mfa_status: Mapping[str, Any],
    docs: Mapping[str, Any],
) -> list[str]:
    auth_events = _payload_list(auth_logs, "events")
    reset_records = _payload_list(reset_events, "events")
    session_records = _payload_list(sessions, "sessions")
    doc_results = _payload_list(docs, "results")
    mfa_user_id = _required_payload_string(mfa_status, "user_id")

    mfa_failure_ids = [
        event["event_id"]
        for event in auth_events
        if _is_mfa_challenge_failure(event)
    ]
    successful_reset_ids = [
        event["event_id"]
        for event in reset_records
        if event.get("status") == "succeeded"
    ]
    session_ids = [
        session["session_id"]
        for session in session_records
        if isinstance(session.get("session_id"), str)
    ]
    active_policy_ids = [
        record["policy_id"]
        for record in doc_results
        if record.get("record_type") == "support_policy"
        and record.get("status") == "active"
    ]
    return [
        f"{_join_ids(successful_reset_ids)} shows password reset completed",
        f"{_join_ids(mfa_failure_ids)} shows the MFA challenge failure",
        f"{mfa_user_id} has MFA status recorded",
        f"{_join_ids(session_ids)} provides recent session context",
        f"{_join_ids(active_policy_ids)} requires manual MFA recovery escalation",
    ]


def _has_mfa_challenge_failure(auth_logs: Mapping[str, Any]) -> bool:
    return any(
        _is_mfa_challenge_failure(event)
        for event in _payload_list(auth_logs, "events")
    )


def _is_mfa_challenge_failure(event: Mapping[str, Any]) -> bool:
    details = event.get("details")
    factor_stage = details.get("factor_stage") if isinstance(details, dict) else None
    status_code = event.get("status_code")
    return factor_stage == "mfa" or (
        isinstance(status_code, str) and "mfa_challenge_failed" in status_code
    )


def _has_trusted_verified_requester_tag(ticket: Mapping[str, Any]) -> bool:
    tags = ticket.get("tags")
    return isinstance(tags, list) and "verified-requester" in tags


def _payload_list(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise BaselineAgentError(f"tool payload missing list: {key}")
    if not all(isinstance(item, dict) for item in value):
        raise BaselineAgentError(f"tool payload list contains non-object items: {key}")
    return value


def _join_ids(record_ids: list[str]) -> str:
    if not record_ids:
        raise BaselineAgentError("expected evidence records were not found")
    return " ".join(record_ids)


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise BaselineAgentError(f"visible scenario missing string: {key}")
    return value


def _required_payload_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise BaselineAgentError(f"tool payload missing string: {key}")
    return value
