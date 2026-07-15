from __future__ import annotations

from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.agents import BaselineSupportAgent  # noqa: E402
from agent_reliability_lab.environment import (  # noqa: E402
    EnvironmentStore,
    SupportToolService,
)
from agent_reliability_lab.evaluation import AgentAttempt, evaluate_attempt  # noqa: E402
from agent_reliability_lab.environment.models import TicketStatus, UserStatus  # noqa: E402
from agent_reliability_lab.scenarios import (  # noqa: E402
    load_scenario,
    load_scenario_suite,
)


FIXED_NOW = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)


class BaselineSupportAgentTests(unittest.TestCase):
    def test_baseline_passes_every_training_scenario(self) -> None:
        state = EnvironmentStore.from_seed().snapshot()

        for scenario in load_scenario_suite(environment_state=state):
            with self.subTest(scenario_id=scenario.metadata.scenario_id):
                store = EnvironmentStore.from_seed()
                initial_state = store.snapshot()
                tools = SupportToolService(
                    store,
                    actor_id="agent:test-baseline-suite",
                    clock=lambda: FIXED_NOW,
                )

                result = BaselineSupportAgent(tools).run(
                    scenario.to_agent_visible_dict()
                )
                evaluation = evaluate_attempt(
                    AgentAttempt(
                        scenario=scenario,
                        initial_state=initial_state,
                        final_state=store.snapshot(),
                        tool_calls=tools.call_log,
                        final_response=result.final_response,
                    )
                )

                self.assertTrue(evaluation.passed, evaluation.feedback_text)

    def test_baseline_agent_passes_cross_midnight_lockout_scenario(self) -> None:
        store = EnvironmentStore.from_seed()
        scenario = load_scenario(environment_state=store.snapshot())
        initial_state = store.snapshot()
        tools = SupportToolService(
            store,
            actor_id="agent:test-baseline",
            clock=lambda: FIXED_NOW,
        )

        result = BaselineSupportAgent(tools).run(scenario.to_agent_visible_dict())
        evaluation = evaluate_attempt(
            AgentAttempt(
                scenario=scenario,
                initial_state=initial_state,
                final_state=store.snapshot(),
                tool_calls=tools.call_log,
                final_response=result.final_response,
            )
        )

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.score, 1.0)
        self.assertEqual(evaluation.failure_tags, [])
        self.assertNotIn("unlock_user", [call.tool_name for call in tools.call_log])
        self.assertEqual(
            store.state.users["usr_aria_kim"].status,
            UserStatus.LOCKED,
        )
        self.assertTrue(store.state.lockouts["usr_aria_kim"].is_locked)
        self.assertEqual(
            store.state.tickets["tkt_7001"].status,
            TicketStatus.PENDING,
        )

    def test_baseline_uses_only_visible_ticket_binding(self) -> None:
        store = EnvironmentStore.from_seed()
        scenario = load_scenario(environment_state=store.snapshot())
        tools = SupportToolService(store, clock=lambda: FIXED_NOW)

        BaselineSupportAgent(tools).run(scenario.to_agent_visible_dict())

        get_user_calls = [
            call for call in tools.call_log if call.tool_name == "get_user"
        ]
        self.assertEqual(len(get_user_calls), 1)
        self.assertEqual(
            get_user_calls[0].arguments,
            {"user_id": "usr_aria_kim"},
        )


if __name__ == "__main__":
    unittest.main()
