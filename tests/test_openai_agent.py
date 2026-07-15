from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.agents.openai_runner import (  # noqa: E402
    DEFAULT_FIREWORKS_AGENT_MAX_TOKENS,
    DEFAULT_FIREWORKS_AGENT_MODEL,
    DEFAULT_FIREWORKS_FREQUENCY_PENALTY,
    DEFAULT_FIREWORKS_PRESENCE_PENALTY,
    DEFAULT_FIREWORKS_TEACHER_MODEL,
    DEFAULT_FIREWORKS_TOP_K,
    DEFAULT_TEMPERATURE,
    DEGRADED_SYSTEM_INSTRUCTION,
    FIREWORKS_BASE_URL,
    FireworksChatCompletionsClient,
    OPENAI_DEGRADED_AGENT_VERSION,
    OPENAI_POLICY_AGENT_NAME,
    OpenAISupportAgent,
    _tool_schemas_for_state,
)
from agent_reliability_lab.agents.openai_tools import (  # noqa: E402
    OPENAI_SUPPORT_TOOL_SCHEMAS,
    dispatch_openai_tool_call,
)
from agent_reliability_lab.environment import (  # noqa: E402
    DEFAULT_ENVIRONMENT_PATH,
    EnvironmentStore,
    SupportToolService,
)
from agent_reliability_lab.optimization import DEFAULT_CANDIDATE_POOL  # noqa: E402
from agent_reliability_lab.runs import run_candidate_scenario  # noqa: E402
from agent_reliability_lab.scenarios import DEFAULT_SCENARIO_PATH, load_scenario  # noqa: E402


FIXED_NOW = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)


class FakeResponsesClient:
    def __init__(self, responses: list[object], *, fail: Exception | None = None):
        self.responses = list(responses)
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def create_response(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail is not None:
            raise self.fail
        if not self.responses:
            raise AssertionError("fake response queue is empty")
        return self.responses.pop(0)


class RecordingSDKCompletions:
    def __init__(self, responses: list[object]):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("fake completion queue is empty")
        return self.responses.pop(0)


class RecordingSDKChat:
    def __init__(self, responses: list[object]):
        self.completions = RecordingSDKCompletions(responses)


class RecordingSDKClient:
    def __init__(self, responses: list[object]):
        self.chat = RecordingSDKChat(responses)


class OpenAIAgentTests(unittest.TestCase):
    def test_default_fireworks_models_are_split_by_role(self) -> None:
        self.assertEqual(
            DEFAULT_FIREWORKS_AGENT_MODEL,
            "accounts/fireworks/models/minimax-m3",
        )
        self.assertEqual(
            DEFAULT_FIREWORKS_TEACHER_MODEL,
            "accounts/fireworks/models/glm-5p2",
        )

    def test_fireworks_client_requires_api_key_for_live_construction(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "FIREWORKS_API_KEY"):
                FireworksChatCompletionsClient()

    def test_fireworks_adapter_translates_tools_and_continuation_history(
        self,
    ) -> None:
        sdk_client = RecordingSDKClient(
            [
                {
                    "id": "chat_1",
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "get_ticket",
                                            "arguments": '{"ticket_id":"tkt_7001"}',
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                },
                {
                    "id": "chat_2",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": "Resolved.", "tool_calls": []},
                        }
                    ],
                },
            ]
        )
        client = FireworksChatCompletionsClient(client=sdk_client)
        tool_schema = {
            "type": "function",
            "name": "get_ticket",
            "description": "Read a ticket.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"ticket_id": {"type": "string"}},
                "required": ["ticket_id"],
                "additionalProperties": False,
            },
        }

        first = client.create_response(
            model=DEFAULT_FIREWORKS_AGENT_MODEL,
            instructions="Follow policy.",
            input="Resolve the ticket.",
            tools=[tool_schema],
            temperature=0.0,
            max_tokens=DEFAULT_FIREWORKS_AGENT_MAX_TOKENS,
            top_k=DEFAULT_FIREWORKS_TOP_K,
            presence_penalty=DEFAULT_FIREWORKS_PRESENCE_PENALTY,
            frequency_penalty=DEFAULT_FIREWORKS_FREQUENCY_PENALTY,
            parallel_tool_calls=False,
            response_format=None,
        )
        second = client.create_response(
            model=DEFAULT_FIREWORKS_AGENT_MODEL,
            instructions="Follow policy.",
            input=[
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": '{"ok":true}',
                }
            ],
            tools=[],
            temperature=0.0,
            max_tokens=DEFAULT_FIREWORKS_AGENT_MAX_TOKENS,
            top_k=DEFAULT_FIREWORKS_TOP_K,
            presence_penalty=DEFAULT_FIREWORKS_PRESENCE_PENALTY,
            frequency_penalty=DEFAULT_FIREWORKS_FREQUENCY_PENALTY,
            parallel_tool_calls=False,
            response_format={"type": "json_object"},
            previous_response_id="chat_1",
        )

        self.assertEqual(FIREWORKS_BASE_URL, "https://api.fireworks.ai/inference/v1")
        self.assertEqual(first["id"], "chat_1")
        self.assertEqual(first["output"][0]["type"], "function_call")
        self.assertEqual(first["output"][0]["name"], "get_ticket")
        self.assertEqual(second["output_text"], "Resolved.")

        first_call, second_call = sdk_client.chat.completions.calls
        self.assertEqual(first_call["model"], DEFAULT_FIREWORKS_AGENT_MODEL)
        self.assertEqual(
            first_call["messages"],
            [
                {"role": "system", "content": "Follow policy."},
                {"role": "user", "content": "Resolve the ticket."},
            ],
        )
        self.assertEqual(
            first_call["tools"][0],
            {
                "type": "function",
                "function": {
                    "name": "get_ticket",
                    "description": "Read a ticket.",
                    "strict": True,
                    "parameters": tool_schema["parameters"],
                },
            },
        )
        self.assertEqual(first_call["temperature"], 0.0)
        self.assertEqual(first_call["max_tokens"], 64_000)
        self.assertEqual(first_call["extra_body"], {"top_k": 40})
        self.assertEqual(first_call["presence_penalty"], 0.0)
        self.assertEqual(first_call["frequency_penalty"], 0.0)
        self.assertFalse(first_call["parallel_tool_calls"])
        self.assertNotIn("response_format", first_call)
        self.assertEqual(second_call["messages"][2]["role"], "assistant")
        self.assertEqual(
            second_call["messages"][2]["tool_calls"][0]["id"],
            "call_1",
        )
        self.assertEqual(
            second_call["messages"][3],
            {"role": "tool", "tool_call_id": "call_1", "content": '{"ok":true}'},
        )
        self.assertEqual(second_call["response_format"], {"type": "json_object"})

    def test_tool_schemas_are_fixed_strict_function_tools(self) -> None:
        schema_by_name = {schema["name"]: schema for schema in OPENAI_SUPPORT_TOOL_SCHEMAS}

        self.assertEqual(
            set(schema_by_name),
            {
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
            },
        )
        for schema in schema_by_name.values():
            self.assertEqual(schema["type"], "function")
            self.assertTrue(schema["strict"])
            self.assertFalse(schema["parameters"]["additionalProperties"])

    def test_dispatcher_returns_existing_tool_result_envelope(self) -> None:
        tools = _tool_service()

        output = dispatch_openai_tool_call(
            tools,
            "get_ticket",
            {"ticket_id": "tkt_1001"},
        )

        self.assertTrue(output["ok"])
        self.assertEqual(output["tool_name"], "get_ticket")
        self.assertEqual(output["data"]["ticket_id"], "tkt_1001")
        self.assertEqual(len(tools.call_log), 1)

    def test_dispatcher_rejects_bad_arguments_without_calling_service(self) -> None:
        tools = _tool_service()

        output = dispatch_openai_tool_call(
            tools,
            "get_ticket",
            {"ticket_id": ""},
        )

        self.assertFalse(output["ok"])
        self.assertEqual(output["error"]["code"], "invalid_tool_arguments")
        self.assertEqual(tools.call_log, [])

    def test_runner_maps_instruction_to_instructions_and_loops_tools(self) -> None:
        fake = FakeResponsesClient(
            [
                _tool_response(
                    "resp_1",
                    "call_abc",
                    "get_ticket",
                    {"ticket_id": "tkt_1001"},
                ),
                _final_response("resp_2", "I checked the ticket and escalated it."),
            ]
        )
        agent = OpenAISupportAgent(
            _tool_service(),
            system_instruction=DEGRADED_SYSTEM_INSTRUCTION,
            agent_name=OPENAI_POLICY_AGENT_NAME,
            agent_version=OPENAI_DEGRADED_AGENT_VERSION,
            responses_client=fake,
            clock=lambda: FIXED_NOW,
        )

        result = agent.run(_visible_scenario())

        self.assertEqual(result.final_response, "I checked the ticket and escalated it.")
        self.assertIsNone(result.failure_reason)
        self.assertEqual(fake.calls[0]["instructions"], DEGRADED_SYSTEM_INSTRUCTION)
        self.assertEqual(fake.calls[0]["temperature"], DEFAULT_TEMPERATURE)
        self.assertFalse(fake.calls[0]["parallel_tool_calls"])
        self.assertIsNone(fake.calls[0]["response_format"])
        self.assertIn("tkt_7001", fake.calls[0]["input"])
        self.assertNotIn("hidden_truth", fake.calls[0]["input"])
        self.assertEqual(fake.calls[1]["previous_response_id"], "resp_1")

        tool_output = fake.calls[1]["input"][0]
        self.assertEqual(tool_output["type"], "function_call_output")
        self.assertEqual(tool_output["call_id"], "call_abc")
        self.assertTrue(json.loads(tool_output["output"])["ok"])
        self.assertEqual(
            [state.kind for state in result.trace_states],
            [
                "agent_started",
                "model_responded",
                "tool_requested",
                "tool_executed",
                "model_responded",
                "final_response_produced",
            ],
        )

    def test_runner_treats_text_without_tool_calls_as_final(self) -> None:
        fake = FakeResponsesClient([_final_response("resp_final", "Done.")])
        agent = OpenAISupportAgent(
            _tool_service(),
            system_instruction=DEGRADED_SYSTEM_INSTRUCTION,
            responses_client=fake,
            clock=lambda: FIXED_NOW,
        )

        result = agent.run(_visible_scenario())

        self.assertEqual(result.final_response, "Done.")
        self.assertIsNone(result.failure_reason)
        self.assertEqual(len(fake.calls), 1)

    def test_runner_returns_failed_attempt_on_max_steps(self) -> None:
        fake = FakeResponsesClient(
            [
                _tool_response(
                    "resp_1",
                    "call_abc",
                    "get_ticket",
                    {"ticket_id": "tkt_1001"},
                )
            ]
        )
        agent = OpenAISupportAgent(
            _tool_service(),
            system_instruction=DEGRADED_SYSTEM_INSTRUCTION,
            responses_client=fake,
            max_steps=1,
            clock=lambda: FIXED_NOW,
        )

        result = agent.run(_visible_scenario())

        self.assertEqual(result.final_response, "")
        self.assertEqual(result.failure_reason, "max_steps_exceeded")
        self.assertEqual(result.trace_states[-1].kind, "agent_failed")

    def test_runner_fails_tool_response_without_response_id(self) -> None:
        response = _tool_response(
            "resp_1",
            "call_abc",
            "get_ticket",
            {"ticket_id": "tkt_1001"},
        )
        del response["id"]
        fake = FakeResponsesClient([response])
        agent = OpenAISupportAgent(
            _tool_service(),
            system_instruction=DEGRADED_SYSTEM_INSTRUCTION,
            responses_client=fake,
            clock=lambda: FIXED_NOW,
        )

        result = agent.run(_visible_scenario())

        self.assertEqual(result.final_response, "")
        self.assertEqual(result.failure_reason, "missing_response_id")

    def test_runner_rejects_incomplete_response_before_finalizing_text(self) -> None:
        response = _final_response("resp_final", "Partial answer.")
        response["status"] = "incomplete"
        response["incomplete_details"] = {"reason": "max_output_tokens"}
        fake = FakeResponsesClient([response])
        agent = OpenAISupportAgent(
            _tool_service(),
            system_instruction=DEGRADED_SYSTEM_INSTRUCTION,
            responses_client=fake,
            clock=lambda: FIXED_NOW,
        )

        result = agent.run(_visible_scenario())

        self.assertEqual(result.final_response, "")
        self.assertEqual(result.failure_reason, "response_incomplete")

    def test_runner_returns_failed_attempt_on_api_error(self) -> None:
        fake = FakeResponsesClient([], fail=RuntimeError("boom"))
        agent = OpenAISupportAgent(
            _tool_service(),
            system_instruction=DEGRADED_SYSTEM_INSTRUCTION,
            responses_client=fake,
            clock=lambda: FIXED_NOW,
        )

        result = agent.run(_visible_scenario())

        self.assertEqual(result.final_response, "")
        self.assertEqual(result.failure_reason, "api_error")
        self.assertEqual(result.trace_states[-1].kind, "agent_failed")

    def test_candidate_run_records_api_failure_provenance(self) -> None:
        fake = FakeResponsesClient([], fail=RuntimeError("boom"))

        record = run_candidate_scenario(
            "cand_openai_degraded_v1",
            clock=lambda: FIXED_NOW,
            persist=False,
            responses_client=fake,
        )

        self.assertEqual(record.agent_failure_reason, "api_error")
        self.assertNotIn(
            "agent_failure_reason",
            record.to_agent_visible_dict(),
        )

    def test_openai_candidate_records_trace_and_evaluates_offline_with_fake_client(
        self,
    ) -> None:
        fake = FakeResponsesClient(
            [
                _tool_response(
                    "resp_1",
                    "call_abc",
                    "get_ticket",
                    {"ticket_id": "tkt_1001"},
                ),
                _final_response("resp_2", "I checked the ticket."),
            ]
        )

        record = run_candidate_scenario(
            "cand_openai_degraded_v1",
            clock=lambda: FIXED_NOW,
            persist=False,
            responses_client=fake,
        )

        self.assertEqual(record.candidate_kind, "openai_policy")
        self.assertEqual(record.agent_name, OPENAI_POLICY_AGENT_NAME)
        self.assertEqual(record.agent_version, OPENAI_DEGRADED_AGENT_VERSION)
        self.assertFalse(record.evaluation["passed"])
        self.assertEqual(record.tool_calls[0]["tool_name"], "get_ticket")
        self.assertIsNotNone(record.agent_trace)
        self.assertEqual(record.agent_trace[0]["kind"], "agent_started")

    def test_openai_policy_candidate_uses_fireworks_agent_model_override(
        self,
    ) -> None:
        fake = FakeResponsesClient([_final_response("resp_1", "Done.")])

        with patch.dict(
            os.environ,
            {"FIREWORKS_AGENT_MODEL": "accounts/custom/models/agent"},
        ):
            run_candidate_scenario(
                "cand_openai_degraded_v1",
                clock=lambda: FIXED_NOW,
                persist=False,
                responses_client=fake,
            )

        self.assertEqual(fake.calls[0]["model"], "accounts/custom/models/agent")

    def test_degraded_candidate_payload_contains_only_policy_runtime_surface(
        self,
    ) -> None:
        candidate = DEFAULT_CANDIDATE_POOL.require("cand_openai_degraded_v1")

        self.assertEqual(candidate.kind, "openai_policy")
        self.assertEqual(
            set(candidate.payload),
            {"system_instruction"},
        )
        self.assertIn(
            "verified-requester",
            candidate.payload["system_instruction"],
        )

    def test_runner_exposes_both_write_actions_after_policy_evidence(self) -> None:
        schemas = _tool_schemas_for_state(
            visible_ticket_id="tkt_7007",
            requester_user_id="usr_gia_rossi",
            ticket_tags=frozenset({"verified-requester"}),
            completed_reads={
                "get_user",
                "get_auth_logs",
                "get_password_reset_events",
                "get_mfa_status",
                "get_sessions",
            },
            active_policy_observed=True,
            action_completed=False,
            unlock_denied=False,
        )

        self.assertEqual(
            {schema["name"] for schema in schemas},
            {"unlock_user", "escalate_case"},
        )

    def test_runner_offers_only_escalation_after_denied_unlock(self) -> None:
        schemas = _tool_schemas_for_state(
            visible_ticket_id="tkt_7007",
            requester_user_id="usr_gia_rossi",
            ticket_tags=frozenset({"verified-requester"}),
            completed_reads={
                "get_user",
                "get_auth_logs",
                "get_password_reset_events",
                "get_mfa_status",
                "get_sessions",
            },
            active_policy_observed=True,
            action_completed=False,
            unlock_denied=True,
        )

        self.assertEqual([schema["name"] for schema in schemas], ["escalate_case"])


def _tool_service() -> SupportToolService:
    return SupportToolService(
        EnvironmentStore.from_seed(DEFAULT_ENVIRONMENT_PATH),
        clock=lambda: FIXED_NOW,
    )


def _visible_scenario() -> dict[str, object]:
    store = EnvironmentStore.from_seed(DEFAULT_ENVIRONMENT_PATH)
    scenario = load_scenario(DEFAULT_SCENARIO_PATH, environment_state=store.snapshot())
    return scenario.to_agent_visible_dict()


def _tool_response(
    response_id: str,
    call_id: str,
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    return {
        "id": response_id,
        "status": "completed",
        "output_text": "",
        "output": [
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": json.dumps(arguments),
            }
        ],
    }


def _final_response(response_id: str, text: str) -> dict[str, object]:
    return {
        "id": response_id,
        "status": "completed",
        "output_text": text,
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
