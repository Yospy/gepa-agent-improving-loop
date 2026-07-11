"""Scenario records and evaluator-only hidden truth schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime
from typing import Any, TypeVar

from agent_reliability_lab.environment.models import format_utc, parse_utc


DataT = TypeVar("DataT")


def _strict_dataclass(
    cls: type[DataT],
    data: dict[str, Any],
    *,
    datetime_fields: tuple[str, ...] = (),
) -> DataT:
    field_names = {field.name for field in fields(cls)}
    supplied_names = set(data)
    missing = field_names - supplied_names
    extra = supplied_names - field_names
    if missing or extra:
        raise ValueError(
            f"{cls.__name__} field mismatch; missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )

    values = dict(data)
    for field_name in datetime_fields:
        values[field_name] = parse_utc(values[field_name])
    return cls(**values)


@dataclass(frozen=True)
class ScenarioMetadata:
    scenario_id: str
    version: str
    title: str
    description: str
    environment_id: str
    primary_ticket_id: str
    primary_user_id: str
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScenarioMetadata":
        return _strict_dataclass(cls, data, datetime_fields=("created_at",))


@dataclass(frozen=True)
class ScenarioEnvironmentBinding:
    seed_path: str
    environment_id: str
    required_ticket_id: str
    required_user_id: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScenarioEnvironmentBinding":
        return _strict_dataclass(cls, data)


@dataclass(frozen=True)
class VisibleScenarioInput:
    ticket_id: str
    customer_issue: str
    starting_prompt: str
    allowed_tools: list[str]
    tool_guidance: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VisibleScenarioInput":
        return _strict_dataclass(cls, data)


@dataclass(frozen=True)
class RequiredEvidence:
    evidence_id: str
    record_type: str
    record_ids: list[str]
    claim: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RequiredEvidence":
        return _strict_dataclass(cls, data)


@dataclass(frozen=True)
class RequiredPolicyBehavior:
    policy_ids: list[str]
    unlock_allowed_initially: bool
    required_action_without_verified_identity: str
    rationale: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RequiredPolicyBehavior":
        return _strict_dataclass(cls, data)


@dataclass(frozen=True)
class ExpectedFinalState:
    primary_user_status: str
    primary_lockout_is_locked: bool
    ticket_status: str
    required_write_action: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExpectedFinalState":
        return _strict_dataclass(cls, data)


@dataclass(frozen=True)
class ForbiddenAction:
    action: str
    target_id: str
    when: str
    failure_tag: str
    reason: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ForbiddenAction":
        return _strict_dataclass(cls, data)


@dataclass(frozen=True)
class FailureTrap:
    trap_id: str
    description: str
    trigger: str
    failure_tag: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FailureTrap":
        return _strict_dataclass(cls, data)


@dataclass(frozen=True)
class HiddenGroundTruth:
    root_cause: str
    diagnosis: str
    expected_behavior: list[str]
    required_evidence: list[RequiredEvidence]
    required_policy_behavior: RequiredPolicyBehavior
    expected_final_state: ExpectedFinalState
    forbidden_actions: list[ForbiddenAction]
    failure_traps: list[FailureTrap]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HiddenGroundTruth":
        values = dict(data)
        values["required_evidence"] = [
            RequiredEvidence.from_dict(item) for item in values["required_evidence"]
        ]
        values["required_policy_behavior"] = RequiredPolicyBehavior.from_dict(
            values["required_policy_behavior"]
        )
        values["expected_final_state"] = ExpectedFinalState.from_dict(
            values["expected_final_state"]
        )
        values["forbidden_actions"] = [
            ForbiddenAction.from_dict(item) for item in values["forbidden_actions"]
        ]
        values["failure_traps"] = [
            FailureTrap.from_dict(item) for item in values["failure_traps"]
        ]
        return _strict_dataclass(cls, values)


@dataclass(frozen=True)
class Scenario:
    metadata: ScenarioMetadata
    environment: ScenarioEnvironmentBinding
    visible: VisibleScenarioInput
    hidden_truth: HiddenGroundTruth

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scenario":
        expected_keys = {"metadata", "environment", "visible", "hidden_truth"}
        supplied_keys = set(data)
        missing = expected_keys - supplied_keys
        extra = supplied_keys - expected_keys
        if missing or extra:
            raise ValueError(
                "Scenario field mismatch; "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )

        return cls(
            metadata=ScenarioMetadata.from_dict(data["metadata"]),
            environment=ScenarioEnvironmentBinding.from_dict(data["environment"]),
            visible=VisibleScenarioInput.from_dict(data["visible"]),
            hidden_truth=HiddenGroundTruth.from_dict(data["hidden_truth"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)

    def to_agent_visible_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.metadata.scenario_id,
            "version": self.metadata.version,
            "title": self.metadata.title,
            "environment_id": self.metadata.environment_id,
            "ticket_id": self.visible.ticket_id,
            "customer_issue": self.visible.customer_issue,
            "starting_prompt": self.visible.starting_prompt,
            "allowed_tools": list(self.visible.allowed_tools),
            "tool_guidance": list(self.visible.tool_guidance),
        }


def to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return format_utc(value)
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value
