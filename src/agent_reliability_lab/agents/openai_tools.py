"""Fixed OpenAI tool schemas and dispatcher for support tools."""

from __future__ import annotations

import json
from typing import Any

from agent_reliability_lab.environment.tools import SupportToolService


OPENAI_SUPPORT_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "name": "get_ticket",
        "description": "Fetch one support ticket by ticket ID.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"ticket_id": {"type": "string"}},
            "required": ["ticket_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_account",
        "description": "Fetch one customer account by account ID.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"account_id": {"type": "string"}},
            "required": ["account_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_user",
        "description": "Fetch one user by user ID.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "search_docs",
        "description": "Search visible support docs and policies.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "include_deprecated": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query", "include_deprecated", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_auth_logs",
        "description": "Fetch auth events for one user within a UTC time window.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "time_window": {
                    "type": "object",
                    "properties": {
                        "start_at": {"type": "string"},
                        "end_at": {"type": "string"},
                    },
                    "required": ["start_at", "end_at"],
                    "additionalProperties": False,
                },
            },
            "required": ["user_id", "time_window"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_password_reset_events",
        "description": "Fetch password reset events for one user within a UTC time window.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "time_window": {
                    "type": "object",
                    "properties": {
                        "start_at": {"type": "string"},
                        "end_at": {"type": "string"},
                    },
                    "required": ["start_at", "end_at"],
                    "additionalProperties": False,
                },
            },
            "required": ["user_id", "time_window"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_sessions",
        "description": "Fetch active and historical sessions for one user.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_mfa_status",
        "description": "Fetch MFA status for one user.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "unlock_user",
        "description": "Unlock a locked user when policy preconditions are satisfied.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["user_id", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "escalate_case",
        "description": "Escalate a support case with reason and evidence.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "reason": {"type": "string"},
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            "required": ["ticket_id", "reason", "evidence"],
            "additionalProperties": False,
        },
    },
)


def parse_tool_arguments(arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return dict(arguments)
    if not isinstance(arguments, str):
        raise ValueError("tool arguments must be a JSON string or object")
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(f"tool arguments are not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("tool arguments must decode to an object")
    return value


def dispatch_openai_tool_call(
    tools: SupportToolService,
    tool_name: str,
    arguments: str | dict[str, Any],
) -> dict[str, Any]:
    try:
        parsed = parse_tool_arguments(arguments)
        result = _dispatch_validated(tools, tool_name, parsed)
    except ValueError as exc:
        return _tool_error("invalid_tool_arguments", str(exc), retryable=False)
    return result.to_dict()


def _dispatch_validated(
    tools: SupportToolService,
    tool_name: str,
    arguments: dict[str, Any],
):
    if tool_name == "get_ticket":
        return tools.get_ticket(_required_string(arguments, "ticket_id"))
    if tool_name == "get_account":
        return tools.get_account(_required_string(arguments, "account_id"))
    if tool_name == "get_user":
        return tools.get_user(_required_string(arguments, "user_id"))
    if tool_name == "search_docs":
        return tools.search_docs(
            _required_string(arguments, "query"),
            include_deprecated=_required_bool(arguments, "include_deprecated"),
            limit=_required_int(arguments, "limit"),
        )
    if tool_name == "get_auth_logs":
        return tools.get_auth_logs(
            _required_string(arguments, "user_id"),
            _required_time_window(arguments),
        )
    if tool_name == "get_password_reset_events":
        return tools.get_password_reset_events(
            _required_string(arguments, "user_id"),
            _required_time_window(arguments),
        )
    if tool_name == "get_sessions":
        return tools.get_sessions(_required_string(arguments, "user_id"))
    if tool_name == "get_mfa_status":
        return tools.get_mfa_status(_required_string(arguments, "user_id"))
    if tool_name == "unlock_user":
        return tools.unlock_user(
            _required_string(arguments, "user_id"),
            _required_string(arguments, "reason"),
        )
    if tool_name == "escalate_case":
        return tools.escalate_case(
            _required_string(arguments, "ticket_id"),
            _required_string(arguments, "reason"),
            _required_string_list(arguments, "evidence"),
        )
    raise ValueError(f"unknown tool: {tool_name}")


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_bool(arguments: dict[str, Any], key: str) -> bool:
    value = arguments.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _required_int(arguments: dict[str, Any], key: str) -> int:
    value = arguments.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def _required_string_list(arguments: dict[str, Any], key: str) -> list[str]:
    value = arguments.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ValueError(f"{key} must be a non-empty list of strings")
    return list(value)


def _required_time_window(arguments: dict[str, Any]) -> dict[str, str]:
    value = arguments.get("time_window")
    if not isinstance(value, dict):
        raise ValueError("time_window must be an object")
    if set(value) != {"start_at", "end_at"}:
        raise ValueError("time_window must contain exactly start_at and end_at")
    return {
        "start_at": _required_string(value, "start_at"),
        "end_at": _required_string(value, "end_at"),
    }


def _tool_error(code: str, message: str, *, retryable: bool) -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }
