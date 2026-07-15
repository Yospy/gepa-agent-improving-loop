"""Agent-facing support tools over the local environment."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable

from agent_reliability_lab.environment.models import (
    Account,
    AuditEntry,
    AuthEvent,
    IdentityVerificationStatus,
    KnowledgeDocument,
    MFAState,
    PasswordResetEvent,
    PolicyStatus,
    Session,
    SupportPolicy,
    Ticket,
    TicketNote,
    TicketStatus,
    User,
    UserStatus,
    format_utc,
    parse_utc,
    to_jsonable,
)
from agent_reliability_lab.environment.store import EnvironmentStore


class ToolExecutionError(ValueError):
    def __init__(
        self, code: str, message: str, *, retryable: bool = False
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class ToolInputError(ToolExecutionError):
    pass


class ToolPolicyError(ToolExecutionError):
    pass


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    tool_name: str
    ok: bool
    data: Any
    error: ToolError | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class ToolCallRecord:
    call_id: str
    tool_name: str
    called_at: datetime
    arguments: dict[str, Any]
    ok: bool
    output: Any
    error: ToolError | None

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class TimeWindow:
    start_at: datetime
    end_at: datetime

    @classmethod
    def from_dict(cls, value: dict[str, str]) -> "TimeWindow":
        if not isinstance(value, dict):
            raise ToolInputError(
                "invalid_time_window",
                "time_window must be an object with start_at and end_at",
            )
        if set(value) != {"start_at", "end_at"}:
            raise ToolInputError(
                "invalid_time_window",
                "time_window must contain exactly start_at and end_at",
            )

        try:
            start_at = parse_utc(value["start_at"])
            end_at = parse_utc(value["end_at"])
        except ValueError as exc:
            raise ToolInputError(
                "invalid_time_window",
                f"time_window timestamps must be timezone-aware ISO strings: {exc}",
            ) from exc
        if start_at > end_at:
            raise ToolInputError(
                "invalid_time_window",
                "time_window start_at must be before or equal to end_at",
            )
        return cls(start_at=start_at, end_at=end_at)


Clock = Callable[[], datetime]


class SupportToolService:
    """Support-console style tools exposed to an agent."""

    def __init__(
        self,
        store: EnvironmentStore,
        *,
        actor_id: str = "agent:local-support-agent",
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self.actor_id = actor_id
        self._clock = clock or _utc_now
        self._call_counter = 0
        self._audit_counter = 0
        self._call_log: list[ToolCallRecord] = []

    @property
    def call_log(self) -> list[ToolCallRecord]:
        return deepcopy(self._call_log)

    def call_log_as_dicts(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self._call_log]

    def get_ticket(self, ticket_id: str) -> ToolResult:
        return self._run(
            "get_ticket",
            {"ticket_id": ticket_id},
            lambda: _ticket_payload(self._require_ticket(ticket_id)),
        )

    def get_account(self, account_id: str) -> ToolResult:
        return self._run(
            "get_account",
            {"account_id": account_id},
            lambda: _account_payload(self._require_account(account_id)),
        )

    def get_user(self, user_id: str) -> ToolResult:
        return self._run(
            "get_user",
            {"user_id": user_id},
            lambda: _user_payload(self._require_user(user_id)),
        )

    def search_docs(
        self, query: str, *, include_deprecated: bool = True, limit: int = 5
    ) -> ToolResult:
        return self._run(
            "search_docs",
            {
                "query": query,
                "include_deprecated": include_deprecated,
                "limit": limit,
            },
            lambda: self._search_docs(query, include_deprecated, limit),
        )

    def get_auth_logs(self, user_id: str, time_window: dict[str, str]) -> ToolResult:
        return self._run(
            "get_auth_logs",
            {"user_id": user_id, "time_window": time_window},
            lambda: {
                "user_id": self._require_user(user_id).user_id,
                "events": [
                    _auth_event_payload(event)
                    for event in _events_in_window(
                        self.store.state.auth_events.values(),
                        user_id,
                        TimeWindow.from_dict(time_window),
                        "occurred_at",
                    )
                ],
            },
        )

    def get_password_reset_events(
        self, user_id: str, time_window: dict[str, str]
    ) -> ToolResult:
        return self._run(
            "get_password_reset_events",
            {"user_id": user_id, "time_window": time_window},
            lambda: {
                "user_id": self._require_user(user_id).user_id,
                "events": [
                    _password_reset_payload(event)
                    for event in _events_in_window(
                        self.store.state.password_reset_events.values(),
                        user_id,
                        TimeWindow.from_dict(time_window),
                        "occurred_at",
                    )
                ],
            },
        )

    def get_sessions(self, user_id: str) -> ToolResult:
        return self._run(
            "get_sessions",
            {"user_id": user_id},
            lambda: {
                "user_id": self._require_user(user_id).user_id,
                "sessions": [
                    _session_payload(session)
                    for session in sorted(
                        self.store.state.sessions.values(),
                        key=lambda session: session.created_at,
                    )
                    if session.user_id == user_id
                ],
            },
        )

    def get_mfa_status(self, user_id: str) -> ToolResult:
        return self._run(
            "get_mfa_status",
            {"user_id": user_id},
            lambda: _mfa_payload(self._require_mfa_state(user_id)),
        )

    def unlock_user(self, user_id: str, reason: str) -> ToolResult:
        return self._run(
            "unlock_user",
            {"user_id": user_id, "reason": reason},
            lambda: self._unlock_user(user_id, reason),
        )

    def escalate_case(
        self, ticket_id: str, reason: str, evidence: list[str]
    ) -> ToolResult:
        return self._run(
            "escalate_case",
            {"ticket_id": ticket_id, "reason": reason, "evidence": evidence},
            lambda: self._escalate_case(ticket_id, reason, evidence),
        )

    def _run(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        handler: Callable[[], Any],
    ) -> ToolResult:
        call_id = self._next_call_id()
        called_at = self._clock()
        try:
            output = handler()
            result = ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=True,
                data=output,
                error=None,
            )
        except ToolExecutionError as exc:
            error = ToolError(
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
            )
            result = ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=False,
                data=None,
                error=error,
            )

        self._call_log.append(
            ToolCallRecord(
                call_id=call_id,
                tool_name=tool_name,
                called_at=called_at,
                arguments=to_jsonable(arguments),
                ok=result.ok,
                output=result.data,
                error=result.error,
            )
        )
        return result

    def _search_docs(
        self, query: str, include_deprecated: bool, limit: int
    ) -> dict[str, Any]:
        if not query or not query.strip():
            raise ToolInputError("invalid_query", "query must not be empty")
        if limit < 1 or limit > 20:
            raise ToolInputError("invalid_limit", "limit must be between 1 and 20")

        terms = _tokenize(query)
        records: list[tuple[int, str, dict[str, Any]]] = []

        for document in self.store.state.knowledge_docs.values():
            if not include_deprecated and document.status.value == "deprecated":
                continue
            payload = _knowledge_document_payload(document)
            score = _score_text(terms, _document_search_text(document))
            if score:
                records.append((score, document.updated_at.isoformat(), payload))

        for policy in self.store.state.support_policies.values():
            if not policy.agent_visible:
                continue
            if not include_deprecated and policy.status != PolicyStatus.ACTIVE:
                continue
            payload = _support_policy_payload(policy)
            score = _score_text(terms, _policy_search_text(policy))
            if score:
                records.append((score, policy.updated_at.isoformat(), payload))

        records.sort(key=lambda record: (-record[0], record[1]))
        return {
            "query": query,
            "results": [payload for _, _, payload in records[:limit]],
        }

    def _unlock_user(self, user_id: str, reason: str) -> dict[str, Any]:
        user = self._require_user(user_id)
        if not reason or not reason.strip():
            raise ToolInputError("invalid_reason", "reason must not be empty")

        lockout = self.store.state.lockouts.get(user_id)
        if (
            user.status != UserStatus.LOCKED
            or lockout is None
            or not lockout.is_locked
        ):
            raise ToolInputError("user_not_locked", "user is not currently locked")

        if (
            lockout.unlock_requires_verified_requester
            and not self._has_verified_identity(user_id)
        ):
            audit_id = self._append_audit_entry(
                action="unlock_user_denied",
                target_type="user",
                target_id=user_id,
                details={
                    "reason": reason,
                    "denial_code": "identity_verification_required",
                },
            )
            raise ToolPolicyError(
                "identity_verification_required",
                "identity verification must be verified before unlocking "
                f"{user_id}; audit_id={audit_id}",
            )

        if self._has_unresolved_compromise(user_id):
            audit_id = self._append_audit_entry(
                action="unlock_user_denied",
                target_type="user",
                target_id=user_id,
                details={
                    "reason": reason,
                    "denial_code": "security_review_required",
                },
            )
            raise ToolPolicyError(
                "security_review_required",
                "unresolved compromise evidence requires security review before "
                f"unlocking {user_id}; audit_id={audit_id}",
            )

        user.status = UserStatus.ACTIVE
        lockout.is_locked = False
        lockout.locked_at = None
        lockout.reason = "cleared_by_support_unlock"
        lockout.failed_attempt_count = 0
        audit_id = self._append_audit_entry(
            action="user_unlocked",
            target_type="user",
            target_id=user_id,
            details={"reason": reason},
        )
        return {
            "user_id": user_id,
            "status": user.status.value,
            "lockout_cleared": True,
            "audit_id": audit_id,
        }

    def _escalate_case(
        self, ticket_id: str, reason: str, evidence: list[str]
    ) -> dict[str, Any]:
        ticket = self._require_ticket(ticket_id)
        if not reason or not reason.strip():
            raise ToolInputError("invalid_reason", "reason must not be empty")
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(item, str) and item.strip() for item in evidence)
        ):
            raise ToolInputError(
                "invalid_evidence",
                "evidence must be a non-empty list of strings",
            )

        ticket.status = TicketStatus.PENDING
        note = TicketNote(
            note_id=self._next_note_id(ticket),
            created_at=self._clock(),
            author_type="support_agent",
            author_id=self.actor_id,
            body=(
                "Escalated for manual review. "
                f"Reason: {reason}. Evidence count: {len(evidence)}."
            ),
            trust_level="agent_generated_support_record",
        )
        ticket.notes.append(note)
        audit_id = self._append_audit_entry(
            action="case_escalated",
            target_type="ticket",
            target_id=ticket_id,
            details={"reason": reason, "evidence": evidence, "note_id": note.note_id},
        )
        return {
            "ticket_id": ticket_id,
            "status": ticket.status.value,
            "note_id": note.note_id,
            "audit_id": audit_id,
            "evidence_count": len(evidence),
        }

    def _require_ticket(self, ticket_id: str) -> Ticket:
        try:
            return self.store.state.tickets[ticket_id]
        except KeyError as exc:
            raise ToolInputError(
                "ticket_not_found", f"ticket {ticket_id} was not found"
            ) from exc

    def _require_account(self, account_id: str) -> Account:
        try:
            return self.store.state.accounts[account_id]
        except KeyError as exc:
            raise ToolInputError(
                "account_not_found", f"account {account_id} was not found"
            ) from exc

    def _require_user(self, user_id: str) -> User:
        try:
            return self.store.state.users[user_id]
        except KeyError as exc:
            raise ToolInputError(
                "user_not_found", f"user {user_id} was not found"
            ) from exc

    def _require_mfa_state(self, user_id: str) -> MFAState:
        self._require_user(user_id)
        try:
            return self.store.state.mfa_states[user_id]
        except KeyError as exc:
            raise ToolInputError(
                "mfa_state_not_found", f"mfa state for {user_id} was not found"
            ) from exc

    def _has_verified_identity(self, user_id: str) -> bool:
        records = [
            verification
            for verification in self.store.state.identity_verifications.values()
            if verification.user_id == user_id
        ]
        if not records:
            return False
        latest = max(records, key=lambda verification: verification.occurred_at)
        return latest.status == IdentityVerificationStatus.VERIFIED and (
            latest.expires_at is None or latest.expires_at > self._clock()
        )

    def _has_unresolved_compromise(self, user_id: str) -> bool:
        return any(
            event.user_id == user_id
            and event.details.get("compromise_indicator") is True
            and event.details.get("resolved") is not True
            for event in self.store.state.auth_events.values()
        )

    def _append_audit_entry(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str,
        details: dict[str, Any],
    ) -> str:
        audit_id = self._next_audit_id()
        self.store.state.audit_log[audit_id] = AuditEntry(
            audit_id=audit_id,
            occurred_at=self._clock(),
            actor_id=self.actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            source_system="support-tool-service",
            details=details,
        )
        return audit_id

    def _next_call_id(self) -> str:
        self._call_counter += 1
        return f"call_{self._call_counter:04d}"

    def _next_audit_id(self) -> str:
        while True:
            self._audit_counter += 1
            audit_id = f"audit_tool_{self._audit_counter:04d}"
            if audit_id not in self.store.state.audit_log:
                return audit_id

    def _next_note_id(self, ticket: Ticket) -> str:
        existing_note_ids = {note.note_id for note in ticket.notes}
        index = 1
        while True:
            note_id = f"note_tool_{index:04d}"
            if note_id not in existing_note_ids:
                return note_id
            index += 1


def _ticket_payload(ticket: Ticket) -> dict[str, Any]:
    return {
        "ticket_id": ticket.ticket_id,
        "account_id": ticket.account_id,
        "requester_user_id": ticket.requester_user_id,
        "subject": ticket.subject,
        "body": ticket.body,
        "status": ticket.status.value,
        "channel": ticket.channel,
        "created_at": format_utc(ticket.created_at),
        "tags": list(ticket.tags),
        "notes": [
            {
                "note_id": note.note_id,
                "created_at": format_utc(note.created_at),
                "author_type": note.author_type,
                "author_id": note.author_id,
                "body": note.body,
                "trust_level": note.trust_level,
            }
            for note in ticket.notes
        ],
    }


def _account_payload(account: Account) -> dict[str, Any]:
    return {
        "account_id": account.account_id,
        "organization_id": account.organization_id,
        "name": account.name,
        "domain": account.domain,
        "subscription_status": account.subscription_status,
        "support_tier": account.support_tier,
    }


def _user_payload(user: User) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "account_id": user.account_id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "status": user.status.value,
        "created_at": format_utc(user.created_at),
        "last_login_at": format_utc(user.last_login_at)
        if user.last_login_at
        else None,
    }


def _auth_event_payload(event: AuthEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "user_id": event.user_id,
        "account_id": event.account_id,
        "occurred_at": format_utc(event.occurred_at),
        "event_type": event.event_type.value,
        "ip_address": event.ip_address,
        "user_agent": event.user_agent,
        "status_code": event.status_code,
        "source_system": event.source_system,
        "details": deepcopy(event.details),
    }


def _password_reset_payload(event: PasswordResetEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "user_id": event.user_id,
        "account_id": event.account_id,
        "occurred_at": format_utc(event.occurred_at),
        "completed_at": format_utc(event.completed_at)
        if event.completed_at
        else None,
        "status": event.status.value,
        "delivery_channel": event.delivery_channel,
        "initiated_by": event.initiated_by,
        "source_system": event.source_system,
    }


def _session_payload(session: Session) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "account_id": session.account_id,
        "status": session.status.value,
        "created_at": format_utc(session.created_at),
        "last_seen_at": format_utc(session.last_seen_at),
        "ip_address": session.ip_address,
    }


def _mfa_payload(mfa_state: MFAState) -> dict[str, Any]:
    return {
        "user_id": mfa_state.user_id,
        "account_id": mfa_state.account_id,
        "required": mfa_state.required,
        "enrolled_factors": list(mfa_state.enrolled_factors),
        "last_verified_at": format_utc(mfa_state.last_verified_at)
        if mfa_state.last_verified_at
        else None,
    }


def _knowledge_document_payload(document: KnowledgeDocument) -> dict[str, Any]:
    return {
        "record_type": "knowledge_document",
        "doc_id": document.doc_id,
        "title": document.title,
        "audience": document.audience.value,
        "status": document.status.value,
        "updated_at": format_utc(document.updated_at),
        "tags": list(document.tags),
        "content": document.content,
    }


def _support_policy_payload(policy: SupportPolicy) -> dict[str, Any]:
    return {
        "record_type": "support_policy",
        "policy_id": policy.policy_id,
        "title": policy.title,
        "status": policy.status.value,
        "updated_at": format_utc(policy.updated_at),
        "applies_to": list(policy.applies_to),
        "rules": list(policy.rules),
        "escalation_required_when": list(policy.escalation_required_when),
    }


def _events_in_window(
    events: Any, user_id: str, time_window: TimeWindow, timestamp_field: str
) -> list[Any]:
    return sorted(
        [
            event
            for event in events
            if event.user_id == user_id
            and time_window.start_at
            <= getattr(event, timestamp_field)
            <= time_window.end_at
        ],
        key=lambda event: getattr(event, timestamp_field),
    )


def _document_search_text(document: KnowledgeDocument) -> str:
    return " ".join(
        [document.title, document.content, document.status.value, *document.tags]
    )


def _policy_search_text(policy: SupportPolicy) -> str:
    return " ".join(
        [
            policy.title,
            policy.status.value,
            *policy.applies_to,
            *policy.rules,
            *policy.escalation_required_when,
        ]
    )


def _score_text(terms: set[str], text: str) -> int:
    text_terms = _tokenize(text)
    return len(terms & text_terms)


def _tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
