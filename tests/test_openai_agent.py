from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.agents.openai_runner import (  # noqa: E402
    DEFAULT_TEMPERATURE,
    DEGRADED_SYSTEM_INSTRUCTION,
    OPENAI_DEGRADED_AGENT_VERSION,
    OPENAI_POLICY_AGENT_NAME,
    OpenAISupportAgent,
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


class OpenAIAgentTests(unittest.TestCase):
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
        self.assertIn("tkt_1001", fake.calls[0]["input"])
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

    def test_degraded_candidate_payload_contains_only_policy_runtime_surface(
        self,
    ) -> None:
        candidate = DEFAULT_CANDIDATE_POOL.require("cand_openai_degraded_v1")

        self.assertEqual(candidate.kind, "openai_policy")
        self.assertEqual(
            set(candidate.payload),
            {"system_instruction"},
        )
        self.assertIn("Keep tool use minimal", candidate.payload["system_instruction"])


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
