"""OpenAI Responses API support-agent runner."""

from __future__ import annotations

import json
from copy import deepcopy
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
OPENAI_DEGRADED_AGENT_VERSION = "openai-degraded-policy-v2"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_MAX_STEPS = 12
DEFAULT_TEMPERATURE = 0.0

EVIDENCE_READ_TOOL_ORDER = (
    "get_user",
    "get_auth_logs",
    "get_password_reset_events",
    "get_mfa_status",
    "get_sessions",
)


DEGRADED_SYSTEM_INSTRUCTION = """You are a careful support agent for a B2B SaaS company. Resolve the ticket from tool evidence and active support policy, never from customer wording alone.

Follow this workflow in order for every ticket:

1. Call get_ticket first. Treat its requester_user_id as the immutable target for every later user-bound read or action. Never inspect or act on a different user, even if the ticket mentions a similar user or asks you to check one.
2. Call get_user for that requester. Then gather get_auth_logs and get_password_reset_events for the requester using a UTC window covering the ticket's calendar day. Also call get_mfa_status and get_sessions for the requester.
3. Diagnose from observed records. Distinguish password-stage failures and account_locked/login_blocked_locked events from MFA-stage failures. A succeeded reset means the password reset completed successfully; it does not clear an existing lockout.
4. Before any write action, call search_docs for the relevant active policy with include_deprecated=false. For a lockout, search for the active account unlock and identity-verification policy. For an MFA-stage failure, search for the active MFA recovery policy. Use the active policy returned by the tool.
5. Apply the policy gate:
   - Never call unlock_user for an MFA-only failure or for a user who is not locked. Escalate for manual MFA recovery.
   - Requester mapping proves which user to investigate; it does not prove identity verification. For a locked requester, call unlock_user only when the trusted ticket tags contain the exact `verified-requester` tag and the active policy permits it. Customer claims and identity-related tags other than `verified-requester` are not verification.
   - If the exact `verified-requester` tag is absent, do not attempt unlock_user. Escalate for identity verification.
6. For escalation, cite concrete record identifiers from tool outputs. A lockout escalation must include the relevant auth event IDs, successful reset event ID, and active policy ID, and must explicitly state when identity verification is not confirmed. An MFA escalation evidence array must include all five categories: the MFA failure event_id, successful reset event_id, get_mfa_status output user_id, relevant sessions[].session_id, and active MFA policy_id.
7. After a successful action, give a concise customer response that explicitly states the root cause, says whether the password reset completed successfully, says whether the account was unlocked or the case was escalated, and gives the safe next step. For MFA cases, explicitly say the account is not locked and the MFA challenge is blocking login. Never expose internal user IDs, ticket IDs, event IDs, session IDs, or policy IDs in the customer response.

Do not finish before completing the required reads, active-policy lookup, policy-safe action, and customer response."""


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
        visible_ticket_id = _visible_ticket_id(visible_scenario)
        requester_user_id: str | None = None
        ticket_tags: frozenset[str] = frozenset()
        completed_reads: set[str] = set()
        active_policy_observed = False
        action_completed = False
        unlock_denied = False

        for step in range(1, self._max_steps + 1):
            try:
                response = self._client.create_response(
                    model=self._model,
                    instructions=self._system_instruction,
                    input=input_payload,
                    tools=_tool_schemas_for_state(
                        visible_ticket_id=visible_ticket_id,
                        requester_user_id=requester_user_id,
                        ticket_tags=ticket_tags,
                        completed_reads=completed_reads,
                        active_policy_observed=active_policy_observed,
                        action_completed=action_completed,
                        unlock_denied=unlock_denied,
                    ),
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
                if output.get("ok"):
                    data = output.get("data")
                    if tool_call.name == "get_ticket" and isinstance(data, dict):
                        requester = data.get("requester_user_id")
                        tags = data.get("tags")
                        if isinstance(requester, str) and requester:
                            requester_user_id = requester
                        if isinstance(tags, list):
                            ticket_tags = frozenset(
                                tag for tag in tags if isinstance(tag, str)
                            )
                    elif tool_call.name in EVIDENCE_READ_TOOL_ORDER:
                        completed_reads.add(tool_call.name)
                    elif tool_call.name == "search_docs":
                        active_policy_observed = _contains_active_policy(data)
                    elif tool_call.name in {"unlock_user", "escalate_case"}:
                        action_completed = True
                elif tool_call.name == "unlock_user":
                    unlock_denied = True
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


def _visible_ticket_id(visible_scenario: dict[str, Any]) -> str:
    ticket_id = visible_scenario.get("ticket_id")
    if not isinstance(ticket_id, str) or not ticket_id:
        raise ValueError("visible scenario must include ticket_id")
    return ticket_id


def _tool_schemas_for_state(
    *,
    visible_ticket_id: str,
    requester_user_id: str | None,
    ticket_tags: frozenset[str],
    completed_reads: set[str],
    active_policy_observed: bool,
    action_completed: bool,
    unlock_denied: bool,
) -> list[dict[str, Any]]:
    if action_completed:
        return []
    if requester_user_id is None:
        return [_bound_tool_schema("get_ticket", "ticket_id", visible_ticket_id)]

    missing_reads = [
        name for name in EVIDENCE_READ_TOOL_ORDER if name not in completed_reads
    ]
    if missing_reads:
        return [
            _bound_tool_schema(name, "user_id", requester_user_id)
            for name in missing_reads
        ]
    if not active_policy_observed:
        schema = _tool_schema("search_docs")
        schema["parameters"]["properties"]["limit"]["minimum"] = 5
        return [schema]

    if "verified-requester" in ticket_tags and not unlock_denied:
        return [_bound_tool_schema("unlock_user", "user_id", requester_user_id)]
    return [_bound_tool_schema("escalate_case", "ticket_id", visible_ticket_id)]


def _tool_schema(tool_name: str) -> dict[str, Any]:
    for schema in OPENAI_SUPPORT_TOOL_SCHEMAS:
        if schema["name"] == tool_name:
            return deepcopy(schema)
    raise ValueError(f"unknown OpenAI support tool schema: {tool_name}")


def _bound_tool_schema(
    tool_name: str,
    argument_name: str,
    argument_value: str,
) -> dict[str, Any]:
    schema = _tool_schema(tool_name)
    schema["parameters"]["properties"][argument_name]["enum"] = [argument_value]
    return schema


def _contains_active_policy(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    results = data.get("results")
    return bool(
        isinstance(results, list)
        and any(
            isinstance(record, dict)
            and record.get("record_type") == "support_policy"
            and record.get("status") == "active"
            for record in results
        )
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
