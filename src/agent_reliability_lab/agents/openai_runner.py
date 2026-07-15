"""Provider-neutral support-agent loop with a Fireworks live adapter."""

from __future__ import annotations

import json
import os
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
FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
DEFAULT_FIREWORKS_AGENT_MODEL = "accounts/fireworks/models/minimax-m3"
DEFAULT_FIREWORKS_TEACHER_MODEL = "accounts/fireworks/models/glm-5p2"
DEFAULT_FIREWORKS_AGENT_MAX_TOKENS = 64_000
DEFAULT_FIREWORKS_TEACHER_MAX_TOKENS = 131_072
DEFAULT_FIREWORKS_TOP_K = 40
DEFAULT_FIREWORKS_PRESENCE_PENALTY = 0.0
DEFAULT_FIREWORKS_FREQUENCY_PENALTY = 0.0
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
        max_tokens: int,
        top_k: int,
        presence_penalty: float,
        frequency_penalty: float,
        parallel_tool_calls: bool,
        response_format: dict[str, Any] | None = None,
        previous_response_id: str | None = None,
    ) -> Any:
        ...


class FireworksChatCompletionsClient:
    """Adapt Fireworks Chat Completions to the runner's response protocol."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        if client is None:
            resolved_key = api_key or os.environ.get("FIREWORKS_API_KEY")
            if not isinstance(resolved_key, str) or not resolved_key.strip():
                raise RuntimeError(
                    "FIREWORKS_API_KEY is required for live Fireworks runs."
                )
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "The openai package is required for live Fireworks runs."
                ) from exc
            client = OpenAI(
                api_key=resolved_key.strip(),
                base_url=FIREWORKS_BASE_URL,
            )
        chat = getattr(client, "chat", None)
        if chat is None or not hasattr(chat, "completions"):
            raise RuntimeError(
                "Fireworks-compatible client does not expose chat.completions"
            )
        self._client = client
        self._histories: dict[str, list[dict[str, Any]]] = {}

    def create_response(
        self,
        *,
        model: str,
        instructions: str,
        input: Any,
        tools: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        top_k: int,
        presence_penalty: float,
        frequency_penalty: float,
        parallel_tool_calls: bool,
        response_format: dict[str, Any] | None = None,
        previous_response_id: str | None = None,
    ) -> Any:
        messages = self._messages_for_request(
            instructions=instructions,
            input=input,
            previous_response_id=previous_response_id,
        )
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "presence_penalty": presence_penalty,
            "frequency_penalty": frequency_penalty,
            "extra_body": {"top_k": top_k},
        }
        if tools:
            kwargs["tools"] = [_chat_completion_tool(tool) for tool in tools]
            kwargs["parallel_tool_calls"] = parallel_tool_calls
        if response_format is not None:
            kwargs["response_format"] = deepcopy(response_format)
        completion = self._client.chat.completions.create(**kwargs)
        normalized, assistant_message = _normalize_chat_completion(completion)
        response_id = normalized["id"]
        if response_id in self._histories:
            raise RuntimeError(
                f"Fireworks returned duplicate response id: {response_id!r}"
            )
        self._histories[response_id] = [*messages, assistant_message]
        return normalized

    def _messages_for_request(
        self,
        *,
        instructions: str,
        input: Any,
        previous_response_id: str | None,
    ) -> list[dict[str, Any]]:
        if previous_response_id is None:
            if not isinstance(input, str):
                raise ValueError("Initial Fireworks input must be a string.")
            return [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input},
            ]

        history = self._histories.get(previous_response_id)
        if history is None:
            raise ValueError(
                "Unknown Fireworks previous_response_id: "
                f"{previous_response_id!r}"
            )
        if not isinstance(input, list) or not input:
            raise ValueError(
                "Fireworks continuation input must contain tool outputs."
            )
        messages = deepcopy(history)
        for item in input:
            if not isinstance(item, dict) or item.get("type") != "function_call_output":
                raise ValueError(
                    "Fireworks continuation items must be function_call_output objects."
                )
            call_id = item.get("call_id")
            output = item.get("output")
            if not isinstance(call_id, str) or not call_id:
                raise ValueError("Fireworks tool output call_id must be non-empty.")
            if not isinstance(output, str):
                raise ValueError("Fireworks tool output must be a string.")
            messages.append(
                {"role": "tool", "tool_call_id": call_id, "content": output}
            )
        return messages


def _chat_completion_tool(tool: dict[str, Any]) -> dict[str, Any]:
    if tool.get("type") != "function":
        raise ValueError("Only function tools are supported by Fireworks.")
    function = {
        key: deepcopy(value)
        for key, value in tool.items()
        if key != "type"
    }
    return {"type": "function", "function": function}


def _normalize_chat_completion(
    completion: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    response_id = _value(completion, "id")
    if not isinstance(response_id, str) or not response_id:
        raise RuntimeError("Fireworks completion did not include an id.")
    choices = _value(completion, "choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise RuntimeError("Fireworks completion must include exactly one choice.")

    choice = choices[0]
    message = _value(choice, "message")
    if message is None:
        raise RuntimeError("Fireworks completion choice did not include a message.")
    content = _value(message, "content")
    if content is None:
        output_text = ""
    elif isinstance(content, str):
        output_text = content
    else:
        raise RuntimeError("Fireworks completion message content must be text or null.")

    raw_tool_calls = _value(message, "tool_calls")
    if raw_tool_calls is None:
        raw_tool_calls = []
    if not isinstance(raw_tool_calls, list):
        raise RuntimeError("Fireworks completion tool_calls must be a list.")

    output: list[dict[str, Any]] = []
    normalized_tool_calls: list[dict[str, Any]] = []
    for tool_call in raw_tool_calls:
        call_id = _value(tool_call, "id")
        call_type = _value(tool_call, "type")
        function = _value(tool_call, "function")
        name = _value(function, "name")
        arguments = _value(function, "arguments")
        if (
            not isinstance(call_id, str)
            or not call_id
            or call_type not in (None, "function")
            or not isinstance(name, str)
            or not name
            or not isinstance(arguments, str)
        ):
            raise RuntimeError("Fireworks returned an invalid function tool call.")
        output.append(
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
            }
        )
        normalized_tool_calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        )

    if output_text:
        output.insert(
            0,
            {
                "type": "message",
                "content": [{"type": "output_text", "text": output_text}],
            },
        )

    finish_reason = _value(choice, "finish_reason")
    completed = finish_reason in (None, "stop", "tool_calls")
    normalized: dict[str, Any] = {
        "id": response_id,
        "status": "completed" if completed else "incomplete",
        "output_text": output_text,
        "output": output,
    }
    if not completed:
        normalized["incomplete_details"] = {"finish_reason": finish_reason}

    assistant_message: dict[str, Any] = {
        "role": "assistant",
        "content": output_text or None,
    }
    if normalized_tool_calls:
        assistant_message["tool_calls"] = normalized_tool_calls
    return normalized, assistant_message


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
        model: str = DEFAULT_FIREWORKS_AGENT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_FIREWORKS_AGENT_MAX_TOKENS,
        top_k: int = DEFAULT_FIREWORKS_TOP_K,
        presence_penalty: float = DEFAULT_FIREWORKS_PRESENCE_PENALTY,
        frequency_penalty: float = DEFAULT_FIREWORKS_FREQUENCY_PENALTY,
        max_steps: int = DEFAULT_MAX_STEPS,
        responses_client: ResponsesClient | None = None,
        clock: Any | None = None,
    ) -> None:
        if not system_instruction.strip():
            raise ValueError("system_instruction must not be empty")
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        self._tools = tools
        self._system_instruction = system_instruction
        self.agent_name = agent_name
        self.agent_version = agent_version
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._top_k = top_k
        self._presence_penalty = presence_penalty
        self._frequency_penalty = frequency_penalty
        self._max_steps = max_steps
        self._client = responses_client or FireworksChatCompletionsClient()
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
                    max_tokens=self._max_tokens,
                    top_k=self._top_k,
                    presence_penalty=self._presence_penalty,
                    frequency_penalty=self._frequency_penalty,
                    parallel_tool_calls=False,
                    response_format=None,
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

    if unlock_denied:
        return [_bound_tool_schema("escalate_case", "ticket_id", visible_ticket_id)]
    return [
        _bound_tool_schema("unlock_user", "user_id", requester_user_id),
        _bound_tool_schema("escalate_case", "ticket_id", visible_ticket_id),
    ]


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
