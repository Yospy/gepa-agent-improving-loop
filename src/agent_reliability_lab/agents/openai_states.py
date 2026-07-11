"""Typed trace states for the OpenAI-backed support agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypeAlias

from agent_reliability_lab.environment.models import to_jsonable


@dataclass(frozen=True)
class AgentStarted:
    kind: Literal["agent_started"]
    occurred_at: datetime
    agent_name: str
    agent_version: str
    model: str
    max_steps: int

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class ModelResponded:
    kind: Literal["model_responded"]
    occurred_at: datetime
    step: int
    response_id: str | None
    output_text: str
    tool_call_count: int

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class ToolRequested:
    kind: Literal["tool_requested"]
    occurred_at: datetime
    step: int
    call_id: str
    tool_name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class ToolExecuted:
    kind: Literal["tool_executed"]
    occurred_at: datetime
    step: int
    call_id: str
    tool_name: str
    ok: bool
    output: Any
    error: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class FinalResponseProduced:
    kind: Literal["final_response_produced"]
    occurred_at: datetime
    step: int
    final_response: str

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class AgentFailed:
    kind: Literal["agent_failed"]
    occurred_at: datetime
    step: int
    reason: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


AgentTraceState: TypeAlias = (
    AgentStarted
    | ModelResponded
    | ToolRequested
    | ToolExecuted
    | FinalResponseProduced
    | AgentFailed
)


@dataclass(frozen=True)
class OpenAIAgentResult:
    agent_name: str
    agent_version: str
    final_response: str
    trace_states: list[AgentTraceState]
    failure_reason: str | None = None

    def trace_as_dicts(self) -> list[dict[str, Any]]:
        return [state.to_dict() for state in self.trace_states]
