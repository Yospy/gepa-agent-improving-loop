"""OpenAI Responses API support-agent runner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from agent_reliability_lab.agents.openai_states import (
    AgentFailed,
    AgentStarted,
    AgentTraceState,
    FinalResponseProduced,
    ModelResponded,
    OpenAIAgentResult,
    ToolExecuted,
    ToolRequested,
)
from agent_reliability_lab.agents.openai_tools import (
    OPENAI_SUPPORT_TOOL_SCHEMAS,
    dispatch_openai_tool_call,
    parse_tool_arguments,
)
from agent_reliability_lab.environment.tools import SupportToolService


OPENAI_POLICY_AGENT_NAME = "openai_support_agent"
OPENAI_DEGRADED_AGENT_VERSION = "openai-degraded-policy-v1"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_MAX_STEPS = 12
DEFAULT_TEMPERATURE = 0.0


DEGRADED_SYSTEM_INSTRUCTION = """You are a fast support triage agent for a B2B SaaS company.

Resolve the customer issue quickly using the available support tools. Start from the ticket, then inspect only the records that seem necessary. Keep tool use minimal and do not over-investigate.

If the ticket mentions a password reset, focus on reset and login status. If you find a likely lockout, try to resolve it with the available support action. If a tool blocks the action, escalate the case.

When escalating, include a brief evidence list based on what you saw. Give the customer a short, clear final response."""


class ResponsesClient(Protocol):
    def create_response(
        self,
        *,
        model: str,
        instructions: str,
        input: Any,
        tools: list[dict[str, Any]],
        temperature: float,
        parallel_tool_calls: bool,
        previous_response_id: str | None = None,
    ) -> Any:
        ...


class OpenAIResponsesClient:
    """Thin lazy wrapper over the OpenAI SDK.

    The import is intentionally lazy so offline tests do not need the package or
    an API key. The SDK reads `OPENAI_API_KEY` from the environment.
    """

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "The openai package is required for live OpenAI agent runs."
                ) from exc
            client = OpenAI()
        if not hasattr(client, "responses"):
            raise RuntimeError("OpenAI client does not expose responses API")
        self._client = client

    def create_response(
        self,
        *,
        model: str,
        instructions: str,
        input: Any,
        tools: list[dict[str, Any]],
        temperature: float,
        parallel_tool_calls: bool,
        previous_response_id: str | None = None,
    ) -> Any:
        kwargs = {
            "model": model,
            "instructions": instructions,
            "input": input,
            "tools": tools,
            "temperature": temperature,
            "parallel_tool_calls": parallel_tool_calls,
        }
        if previous_response_id is not None:
            kwargs["previous_response_id"] = previous_response_id
        return self._client.responses.create(**kwargs)


@dataclass(frozen=True)
class ModelToolCall:
    call_id: str
    name: str
    arguments: str | dict[str, Any]


class OpenAISupportAgent:
    def __init__(
        self,
        tools: SupportToolService,
        *,
        system_instruction: str,
        agent_name: str = OPENAI_POLICY_AGENT_NAME,
        agent_version: str = OPENAI_DEGRADED_AGENT_VERSION,
        model: str = DEFAULT_OPENAI_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        max_steps: int = DEFAULT_MAX_STEPS,
        responses_client: ResponsesClient | None = None,
        clock: Any | None = None,
    ) -> None:
        if not system_instruction.strip():
            raise ValueError("system_instruction must not be empty")
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self._tools = tools
        self._system_instruction = system_instruction
        self.agent_name = agent_name
        self.agent_version = agent_version
        self._model = model
        self._temperature = temperature
        self._max_steps = max_steps
        self._client = responses_client or OpenAIResponsesClient()
        self._clock = clock or _utc_now

    def run(self, visible_scenario: dict[str, Any]) -> OpenAIAgentResult:
        trace: list[AgentTraceState] = [
            AgentStarted(
                kind="agent_started",
                occurred_at=self._clock(),
                agent_name=self.agent_name,
                agent_version=self.agent_version,
                model=self._model,
                max_steps=self._max_steps,
            )
        ]
        input_payload: Any = _build_user_input(visible_scenario)
        previous_response_id: str | None = None

        for step in range(1, self._max_steps + 1):
            try:
                response = self._client.create_response(
                    model=self._model,
                    instructions=self._system_instruction,
                    input=input_payload,
                    tools=[dict(schema) for schema in OPENAI_SUPPORT_TOOL_SCHEMAS],
                    temperature=self._temperature,
                    parallel_tool_calls=False,
                    previous_response_id=previous_response_id,
                )
            except Exception as exc:  # pragma: no cover - exact SDK errors vary.
                return _failed_result(
                    self.agent_name,
                    self.agent_version,
                    trace,
                    self._clock(),
                    step,
                    "api_error",
                    str(exc),
                )

            response_id = _response_id(response)
            output_text = _output_text(response)
            tool_calls = _tool_calls(response)
            response_problem = _response_problem(response)
            trace.append(
                ModelResponded(
                    kind="model_responded",
                    occurred_at=self._clock(),
                    step=step,
                    response_id=response_id,
                    output_text=output_text,
                    tool_call_count=len(tool_calls),
                )
            )
            if response_problem is not None:
                reason, message = response_problem
                return _failed_result(
                    self.agent_name,
                    self.agent_version,
                    trace,
                    self._clock(),
                    step,
                    reason,
                    message,
                )

            if not tool_calls and output_text.strip():
                trace.append(
                    FinalResponseProduced(
                        kind="final_response_produced",
                        occurred_at=self._clock(),
                        step=step,
                        final_response=output_text,
                    )
                )
                return OpenAIAgentResult(
                    agent_name=self.agent_name,
                    agent_version=self.agent_version,
                    final_response=output_text,
                    trace_states=trace,
                )

            if not tool_calls:
                return _failed_result(
                    self.agent_name,
                    self.agent_version,
                    trace,
                    self._clock(),
                    step,
                    "empty_model_response",
                    "model returned no tool calls and no final text",
                )

            if response_id is None:
                return _failed_result(
                    self.agent_name,
                    self.agent_version,
                    trace,
                    self._clock(),
                    step,
                    "missing_response_id",
                    "model requested tools but response id was missing",
                )

            tool_outputs: list[dict[str, Any]] = []
            for tool_call in tool_calls:
                arguments = _safe_arguments(tool_call.arguments)
                trace.append(
                    ToolRequested(
                        kind="tool_requested",
                        occurred_at=self._clock(),
                        step=step,
                        call_id=tool_call.call_id,
                        tool_name=tool_call.name,
                        arguments=arguments,
                    )
                )
                output = dispatch_openai_tool_call(
                    self._tools,
                    tool_call.name,
                    tool_call.arguments,
                )
                trace.append(
                    ToolExecuted(
                        kind="tool_executed",
                        occurred_at=self._clock(),
                        step=step,
                        call_id=tool_call.call_id,
                        tool_name=tool_call.name,
                        ok=bool(output.get("ok", False)),
                        output=output.get("data"),
                        error=output.get("error")
                        if isinstance(output.get("error"), dict)
                        else None,
                    )
                )
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": json.dumps(output, sort_keys=True),
                    }
                )

            input_payload = tool_outputs
            previous_response_id = response_id

        return _failed_result(
            self.agent_name,
            self.agent_version,
            trace,
            self._clock(),
            self._max_steps,
            "max_steps_exceeded",
            f"agent exceeded max_steps={self._max_steps}",
        )


def _build_user_input(visible_scenario: dict[str, Any]) -> str:
    return (
        "Use only the available support tools to resolve this visible scenario. "
        "Do not assume records that are not returned by tools.\n\n"
        f"{json.dumps(visible_scenario, indent=2, sort_keys=True)}"
    )


def _response_id(response: Any) -> str | None:
    value = _value(response, "id")
    return value if isinstance(value, str) else None


def _response_problem(response: Any) -> tuple[str, str] | None:
    error = _value(response, "error")
    if error is not None:
        return ("response_error", _stringify_value(error))

    incomplete_details = _value(response, "incomplete_details")
    if incomplete_details is not None:
        return ("response_incomplete", _stringify_value(incomplete_details))

    status = _value(response, "status")
    if status in (None, "completed"):
        return None
    return ("response_not_completed", f"response status was {status!r}")


def _output_text(response: Any) -> str:
    direct = _value(response, "output_text")
    if isinstance(direct, str):
        return direct

    parts: list[str] = []
    for item in _output_items(response):
        if _value(item, "type") != "message":
            continue
        content = _value(item, "content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            text = _value(content_item, "text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _tool_calls(response: Any) -> list[ModelToolCall]:
    calls: list[ModelToolCall] = []
    for item in _output_items(response):
        if _value(item, "type") != "function_call":
            continue
        call_id = _value(item, "call_id")
        name = _value(item, "name")
        arguments = _value(item, "arguments")
        if isinstance(call_id, str) and isinstance(name, str):
                calls.append(
                    ModelToolCall(
                        call_id=call_id,
                        name=name,
                        arguments=arguments
                        if isinstance(arguments, dict)
                        else str(arguments),
                    )
                )
    return calls


def _output_items(response: Any) -> list[Any]:
    output = _value(response, "output")
    return output if isinstance(output, list) else []


def _safe_arguments(arguments: str | dict[str, Any]) -> dict[str, Any]:
    try:
        return parse_tool_arguments(arguments)
    except ValueError:
        return {"_raw": arguments}


def _failed_result(
    agent_name: str,
    agent_version: str,
    trace: list[AgentTraceState],
    occurred_at: datetime,
    step: int,
    reason: str,
    message: str,
) -> OpenAIAgentResult:
    trace.append(
        AgentFailed(
            kind="agent_failed",
            occurred_at=occurred_at,
            step=step,
            reason=reason,
            message=message,
        )
    )
    return OpenAIAgentResult(
        agent_name=agent_name,
        agent_version=agent_version,
        final_response="",
        trace_states=trace,
        failure_reason=reason,
    )


def _value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _stringify_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
