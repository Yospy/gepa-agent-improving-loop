"""Typed records for the fake support environment."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeVar


class TextEnum(str, Enum):
    """String-backed enum that serializes cleanly to JSON."""


class UserStatus(TextEnum):
    ACTIVE = "active"
    LOCKED = "locked"
    DISABLED = "disabled"


class TicketStatus(TextEnum):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"


class AuthEventType(TextEnum):
    LOGIN_FAILURE = "login_failure"
    LOGIN_BLOCKED_LOCKED = "login_blocked_locked"
    LOGIN_SUCCESS = "login_success"
    ACCOUNT_LOCKED = "account_locked"


class PasswordResetStatus(TextEnum):
    REQUESTED = "requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class IdentityVerificationStatus(TextEnum):
    NOT_STARTED = "not_started"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class SessionStatus(TextEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class DocumentAudience(TextEnum):
    PUBLIC = "public"
    INTERNAL_SUPPORT = "internal_support"


class DocumentStatus(TextEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class PolicyStatus(TextEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


EnumT = TypeVar("EnumT", bound=TextEnum)
DataT = TypeVar("DataT")


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Expected ISO timestamp string, got {type(value).__name__}")

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Timestamp must include timezone: {value}")
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Timestamp must include timezone: {value!r}")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_enum(enum_type: type[EnumT], value: Any, field_name: str) -> EnumT:
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value!r}") from exc


def _strict_dataclass(
    cls: type[DataT],
    data: dict[str, Any],
    *,
    datetime_fields: tuple[str, ...] = (),
    optional_datetime_fields: tuple[str, ...] = (),
    enum_fields: dict[str, type[TextEnum]] | None = None,
) -> DataT:
    field_names = {field.name for field in fields(cls)}
    supplied_names = set(data)
    missing = field_names - supplied_names
    extra = supplied_names - field_names
    if missing or extra:
        raise ValueError(
            f"{cls.__name__} field mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )

    values = dict(data)
    for field_name in datetime_fields:
        values[field_name] = parse_utc(values[field_name])
    for field_name in optional_datetime_fields:
        if values[field_name] is not None:
            values[field_name] = parse_utc(values[field_name])
    for field_name, enum_type in (enum_fields or {}).items():
        values[field_name] = _coerce_enum(enum_type, values[field_name], field_name)
    return cls(**values)


@dataclass
class EnvironmentMetadata:
    environment_id: str
    version: str
    company_name: str
    seeded_at: datetime
    primary_ticket_id: str
    primary_user_id: str
    description: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvironmentMetadata":
        return _strict_dataclass(cls, data, datetime_fields=("seeded_at",))


@dataclass
class Organization:
    organization_id: str
    name: str
    plan: str
    region: str
    account_ids: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Organization":
        return _strict_dataclass(cls, data)


@dataclass
class Account:
    account_id: str
    organization_id: str
    name: str
    domain: str
    subscription_status: str
    support_tier: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Account":
        return _strict_dataclass(cls, data)


@dataclass
class User:
    user_id: str
    account_id: str
    email: str
    full_name: str
    role: str
    status: UserStatus
    created_at: datetime
    last_login_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
        return _strict_dataclass(
            cls,
            data,
            datetime_fields=("created_at",),
            optional_datetime_fields=("last_login_at",),
            enum_fields={"status": UserStatus},
        )


@dataclass
class TicketNote:
    note_id: str
    created_at: datetime
    author_type: str
    author_id: str
    body: str
    trust_level: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TicketNote":
        return _strict_dataclass(cls, data, datetime_fields=("created_at",))


@dataclass
class Ticket:
    ticket_id: str
    account_id: str
    requester_user_id: str
    subject: str
    body: str
    status: TicketStatus
    channel: str
    created_at: datetime
    tags: list[str]
    notes: list[TicketNote]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Ticket":
        values = dict(data)
        values["notes"] = [TicketNote.from_dict(note) for note in values["notes"]]
        return _strict_dataclass(
            cls,
            values,
            datetime_fields=("created_at",),
            enum_fields={"status": TicketStatus},
        )


@dataclass
class AuthEvent:
    event_id: str
    user_id: str
    account_id: str
    occurred_at: datetime
    event_type: AuthEventType
    ip_address: str
    user_agent: str
    status_code: str
    source_system: str
    details: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthEvent":
        return _strict_dataclass(
            cls,
            data,
            datetime_fields=("occurred_at",),
            enum_fields={"event_type": AuthEventType},
        )


@dataclass
class PasswordResetEvent:
    event_id: str
    user_id: str
    account_id: str
    occurred_at: datetime
    completed_at: datetime | None
    status: PasswordResetStatus
    delivery_channel: str
    initiated_by: str
    source_system: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PasswordResetEvent":
        return _strict_dataclass(
            cls,
            data,
            datetime_fields=("occurred_at",),
            optional_datetime_fields=("completed_at",),
            enum_fields={"status": PasswordResetStatus},
        )


@dataclass
class IdentityVerification:
    verification_id: str
    ticket_id: str
    user_id: str
    account_id: str
    status: IdentityVerificationStatus
    method: str
    occurred_at: datetime
    verified_by: str | None
    expires_at: datetime | None
    source_system: str
    details: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IdentityVerification":
        return _strict_dataclass(
            cls,
            data,
            datetime_fields=("occurred_at",),
            optional_datetime_fields=("expires_at",),
            enum_fields={"status": IdentityVerificationStatus},
        )


@dataclass
class LockoutState:
    user_id: str
    account_id: str
    is_locked: bool
    locked_at: datetime | None
    reason: str
    failed_attempt_count: int
    unlock_requires_verified_requester: bool
    source_system: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LockoutState":
        return _strict_dataclass(cls, data, optional_datetime_fields=("locked_at",))


@dataclass
class MFAState:
    user_id: str
    account_id: str
    required: bool
    enrolled_factors: list[str]
    last_verified_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MFAState":
        return _strict_dataclass(cls, data, optional_datetime_fields=("last_verified_at",))


@dataclass
class Session:
    session_id: str
    user_id: str
    account_id: str
    status: SessionStatus
    created_at: datetime
    last_seen_at: datetime
    ip_address: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        return _strict_dataclass(
            cls,
            data,
            datetime_fields=("created_at", "last_seen_at"),
            enum_fields={"status": SessionStatus},
        )


@dataclass
class KnowledgeDocument:
    doc_id: str
    title: str
    audience: DocumentAudience
    status: DocumentStatus
    updated_at: datetime
    tags: list[str]
    content: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeDocument":
        return _strict_dataclass(
            cls,
            data,
            datetime_fields=("updated_at",),
            enum_fields={"audience": DocumentAudience, "status": DocumentStatus},
        )


@dataclass
class SupportPolicy:
    policy_id: str
    title: str
    status: PolicyStatus
    updated_at: datetime
    applies_to: list[str]
    rules: list[str]
    escalation_required_when: list[str]
    agent_visible: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SupportPolicy":
        return _strict_dataclass(
            cls,
            data,
            datetime_fields=("updated_at",),
            enum_fields={"status": PolicyStatus},
        )


@dataclass
class AuditEntry:
    audit_id: str
    occurred_at: datetime
    actor_id: str
    action: str
    target_type: str
    target_id: str
    source_system: str
    details: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEntry":
        return _strict_dataclass(cls, data, datetime_fields=("occurred_at",))


@dataclass
class EnvironmentState:
    metadata: EnvironmentMetadata
    organizations: dict[str, Organization]
    accounts: dict[str, Account]
    users: dict[str, User]
    tickets: dict[str, Ticket]
    auth_events: dict[str, AuthEvent]
    password_reset_events: dict[str, PasswordResetEvent]
    identity_verifications: dict[str, IdentityVerification]
    lockouts: dict[str, LockoutState]
    mfa_states: dict[str, MFAState]
    sessions: dict[str, Session]
    knowledge_docs: dict[str, KnowledgeDocument]
    support_policies: dict[str, SupportPolicy]
    audit_log: dict[str, AuditEntry]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvironmentState":
        expected_keys = {
            "metadata",
            "organizations",
            "accounts",
            "users",
            "tickets",
            "auth_events",
            "password_reset_events",
            "identity_verifications",
            "lockouts",
            "mfa_states",
            "sessions",
            "knowledge_docs",
            "support_policies",
            "audit_log",
        }
        supplied_keys = set(data)
        missing = expected_keys - supplied_keys
        extra = supplied_keys - expected_keys
        if missing or extra:
            raise ValueError(
                "EnvironmentState field mismatch; "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )

        return cls(
            metadata=EnvironmentMetadata.from_dict(data["metadata"]),
            organizations=_index_by(
                (Organization.from_dict(item) for item in data["organizations"]),
                "organization_id",
            ),
            accounts=_index_by(
                (Account.from_dict(item) for item in data["accounts"]),
                "account_id",
            ),
            users=_index_by((User.from_dict(item) for item in data["users"]), "user_id"),
            tickets=_index_by(
                (Ticket.from_dict(item) for item in data["tickets"]),
                "ticket_id",
            ),
            auth_events=_index_by(
                (AuthEvent.from_dict(item) for item in data["auth_events"]),
                "event_id",
            ),
            password_reset_events=_index_by(
                (
                    PasswordResetEvent.from_dict(item)
                    for item in data["password_reset_events"]
                ),
                "event_id",
            ),
            identity_verifications=_index_by(
                (
                    IdentityVerification.from_dict(item)
                    for item in data["identity_verifications"]
                ),
                "verification_id",
            ),
            lockouts=_index_by(
                (LockoutState.from_dict(item) for item in data["lockouts"]),
                "user_id",
            ),
            mfa_states=_index_by(
                (MFAState.from_dict(item) for item in data["mfa_states"]),
                "user_id",
            ),
            sessions=_index_by(
                (Session.from_dict(item) for item in data["sessions"]),
                "session_id",
            ),
            knowledge_docs=_index_by(
                (KnowledgeDocument.from_dict(item) for item in data["knowledge_docs"]),
                "doc_id",
            ),
            support_policies=_index_by(
                (SupportPolicy.from_dict(item) for item in data["support_policies"]),
                "policy_id",
            ),
            audit_log=_index_by(
                (AuditEntry.from_dict(item) for item in data["audit_log"]),
                "audit_id",
            ),
        )

    def to_seed_dict(self) -> dict[str, Any]:
        return {
            "metadata": to_jsonable(self.metadata),
            "organizations": _sorted_records(self.organizations),
            "accounts": _sorted_records(self.accounts),
            "users": _sorted_records(self.users),
            "tickets": _sorted_records(self.tickets),
            "auth_events": _sorted_records(self.auth_events),
            "password_reset_events": _sorted_records(self.password_reset_events),
            "identity_verifications": _sorted_records(self.identity_verifications),
            "lockouts": _sorted_records(self.lockouts),
            "mfa_states": _sorted_records(self.mfa_states),
            "sessions": _sorted_records(self.sessions),
            "knowledge_docs": _sorted_records(self.knowledge_docs),
            "support_policies": _sorted_records(self.support_policies),
            "audit_log": _sorted_records(self.audit_log),
        }


def _index_by(records: Any, field_name: str) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for record in records:
        record_id = getattr(record, field_name)
        if record_id in indexed:
            raise ValueError(f"Duplicate {field_name}: {record_id}")
        indexed[record_id] = record
    return indexed


def _sorted_records(records: dict[str, Any]) -> list[dict[str, Any]]:
    return [to_jsonable(records[key]) for key in sorted(records)]


def to_jsonable(value: Any) -> Any:
    if isinstance(value, TextEnum):
        return value.value
    if isinstance(value, datetime):
        return format_utc(value)
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value
