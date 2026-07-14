from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.optimization.candidates import (  # noqa: E402
    DEFAULT_CANDIDATE_POOL,
    Candidate,
)
from agent_reliability_lab.optimization.reflection import (  # noqa: E402
    MAX_SYSTEM_INSTRUCTION_LENGTH,
    REFLECTION_INSTRUCTIONS,
    OpenAIReflectionClient,
    build_reflection_bundle,
    create_child_candidate,
    format_reflection_input,
    parse_mutation_proposal,
    reflect_and_create_child,
)
from agent_reliability_lab.optimization.scoring import build_score_matrix  # noqa: E402
from agent_reliability_lab.runs import (  # noqa: E402
    CandidateSuiteRun,
    RunRecord,
    run_candidate_scenario,
)


FIXED_NOW = datetime(2026, 7, 10, 10, 0, 0, tzinfo=timezone.utc)
PARENT_ID = "cand_openai_degraded_v1"


class FakeReflectionClient:
    def __init__(self, response: str = "", *, error: Exception | None = None):
        self.response = response
        self.error = error
        self.bundles = []

    def reflect(self, bundle):
        self.bundles.append(bundle)
        if self.error is not None:
            raise self.error
        return self.response


class FakeResponsesClient:
    def __init__(self, response: object):
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create_response(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class GEPAReflectionTests(unittest.TestCase):
    def test_public_tool_name_does_not_trigger_identifier_memorization(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        record = _record("run_1", "scenario_a", score=0.4, passed=False)
        record.evaluation["feedback_text"] = "Missing evidence ID: mfa_status"
        bundle = build_reflection_bundle(parent, _suite([record]))
        client = FakeReflectionClient(
            '{"analysis":"Read MFA state.",'
            '"system_instruction":"Call get_mfa_status before diagnosing MFA."}'
        )

        result = reflect_and_create_child(
            parent,
            bundle,
            client,
            mutation_id_factory=lambda: "mutation_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertTrue(result.succeeded)
        self.assertIsNotNone(result.child)

    def test_exact_optimizer_identifier_remains_blocked(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        record = _record("run_1", "scenario_a", score=0.4, passed=False)
        record.evaluation["feedback_text"] = "Missing evidence ID: mfa_status"
        bundle = build_reflection_bundle(parent, _suite([record]))
        client = FakeReflectionClient(
            '{"analysis":"Copy an identifier.",'
            '"system_instruction":"Always special-case mfa_status."}'
        )

        result = reflect_and_create_child(
            parent,
            bundle,
            client,
            mutation_id_factory=lambda: "mutation_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertFalse(result.succeeded)
        self.assertEqual(result.error.error_type, "identifier_memorization")

    def test_candidate_pool_extension_is_immutable_and_reuses_validation(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        child = Candidate(
            candidate_id="cand_child",
            agent_name=parent.agent_name,
            agent_version="openai-child-v1",
            parent_id=parent.candidate_id,
            generation=1,
            kind="openai_policy",
            description="Generated child.",
            payload={"system_instruction": "Inspect evidence before acting."},
        )

        extended = DEFAULT_CANDIDATE_POOL.with_candidate(child)

        self.assertIsNone(DEFAULT_CANDIDATE_POOL.get(child.candidate_id))
        self.assertIs(extended.require(child.candidate_id), child)
        with self.assertRaises(ValueError):
            extended.with_candidate(child)

    def test_reflection_bundle_selects_lowest_score_once_per_scenario(self) -> None:
        suite = _suite(
            [
                _record("run_b", "scenario_a", score=0.7, passed=False),
                _record("run_a", "scenario_a", score=0.7, passed=False),
                _record("run_low", "scenario_a", score=0.2, passed=False),
                _record("run_success", "scenario_b", score=1.0, passed=True),
            ],
            repeat_count=2,
        )
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)

        bundle = build_reflection_bundle(parent, suite)

        self.assertEqual(
            [example.run_id for example in bundle.examples],
            ["run_low", "run_success"],
        )
        self.assertEqual(bundle.source_run_ids, ("run_low", "run_success"))
        self.assertEqual(bundle.parent_candidate_id, parent.candidate_id)
        self.assertEqual(
            bundle.parent_system_instruction,
            parent.payload["system_instruction"],
        )
        self.assertEqual(bundle.examples[0].failure_tags, ("wrong_root_cause",))
        self.assertEqual(bundle.examples[0].feedback_text, "feedback run_low")
        self.assertEqual(
            bundle.examples[0].trace_excerpt,
            ("get_ticket(ok) args={'ticket_id': 'tkt_1001'}",),
        )

    def test_reflection_bundle_rejects_incomplete_or_wrong_parent_suite(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        incomplete = CandidateSuiteRun(
            suite_name="training",
            candidate_id=PARENT_ID,
            scenario_ids=("scenario_a",),
            repeat_count=1,
            expected_run_count=1,
            records=(),
            errors=(),
            matrix=None,
        )
        wrong_parent = _suite(
            [_record("run_1", "scenario_a")],
            candidate_id="cand_missing_auth_logs_v1",
        )

        with self.assertRaises(ValueError):
            build_reflection_bundle(parent, incomplete)
        with self.assertRaises(ValueError):
            build_reflection_bundle(parent, wrong_parent)

    def test_reflection_input_contains_optimizer_feedback_not_hidden_container(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        bundle = build_reflection_bundle(
            parent,
            _suite([_record("run_1", "scenario_a", score=0.4, passed=False)]),
        )

        payload = json.loads(format_reflection_input(bundle))

        self.assertEqual(payload["parent_candidate_id"], PARENT_ID)
        self.assertEqual(payload["examples"][0]["feedback_text"], "feedback run_1")
        self.assertNotIn("hidden_truth", payload)
        self.assertNotIn("agent_visible_scenario", payload["examples"][0])

    def test_retry_feedback_is_serialized_without_hidden_container(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        bundle = build_reflection_bundle(
            parent,
            _suite([_record("run_1", "scenario_a", score=0.4, passed=False)]),
        )
        retry_bundle = bundle.with_revision_feedback(
            "Previous proposal was rejected as unchanged_instruction."
        )

        payload = json.loads(format_reflection_input(retry_bundle))

        self.assertEqual(
            payload["revision_feedback"],
            "Previous proposal was rejected as unchanged_instruction.",
        )
        self.assertNotIn("hidden_truth", payload)

    def test_reflection_instructions_preserve_runtime_invariants_and_focus_mutation(
        self,
    ) -> None:
        normalized_instructions = " ".join(REFLECTION_INSTRUCTIONS.lower().split())
        required_phrases = (
            "runtime-enforced invariants",
            "ticket-first requester binding",
            "required evidence tool calls",
            "active-policy lookup",
            "allowed write capability",
            "event time-window selection",
            "diagnosis language",
            "policy query quality",
            "escalation evidence composition",
            "explicit completed-action confirmation",
            "safe next steps",
        )

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized_instructions)
        self.assertIn("preserve", normalized_instructions)
        self.assertIn("not redesign", normalized_instructions)

    def test_mutation_parser_requires_exact_nonempty_json_contract(self) -> None:
        proposal = parse_mutation_proposal(
            json.dumps(
                {
                    "analysis": "The parent skipped evidence.",
                    "system_instruction": "Inspect all required evidence before acting.",
                }
            )
        )

        self.assertEqual(proposal.analysis, "The parent skipped evidence.")
        self.assertEqual(
            proposal.system_instruction,
            "Inspect all required evidence before acting.",
        )

        invalid = (
            "not json",
            "{}",
            '{"analysis":"a","system_instruction":"b","extra":true}',
            '{"analysis":"","system_instruction":"b"}',
        )
        for response in invalid:
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    parse_mutation_proposal(response)

    def test_create_child_candidate_records_lineage_and_provenance(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        proposal = parse_mutation_proposal(
            '{"analysis":"Use evidence.","system_instruction":"Inspect evidence first."}'
        )

        child = create_child_candidate(
            parent,
            proposal,
            source_run_ids=("run_1",),
            mutation_id="mutation_fixed",
            created_at=FIXED_NOW,
        )

        self.assertEqual(child.candidate_id, "cand_openai_gepa_g1_mutation_fixed")
        self.assertEqual(child.parent_id, parent.candidate_id)
        self.assertEqual(child.generation, parent.generation + 1)
        self.assertEqual(child.kind, "openai_policy")
        self.assertEqual(child.payload["system_instruction"], "Inspect evidence first.")
        metadata = child.payload["optimizer_metadata"]
        self.assertEqual(metadata["mutation_id"], "mutation_fixed")
        self.assertEqual(metadata["source_run_ids"], ["run_1"])
        self.assertNotEqual(
            metadata["parent_instruction_sha256"],
            metadata["child_instruction_sha256"],
        )

    def test_reflect_and_create_child_validates_before_returning_candidate(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        bundle = build_reflection_bundle(
            parent,
            _suite([_record("run_1", "scenario_a", score=0.4, passed=False)]),
        )
        client = FakeReflectionClient(
            '{"analysis":"Require evidence.",'
            '"system_instruction":"Inspect logs and policy before acting."}'
        )

        result = reflect_and_create_child(
            parent,
            bundle,
            client,
            mutation_id_factory=lambda: "mutation_fixed",
            clock=lambda: FIXED_NOW,
        )

        self.assertTrue(result.succeeded)
        self.assertIsNotNone(result.child)
        self.assertIsNone(result.error)
        self.assertEqual(result.source_run_ids, ("run_1",))
        self.assertEqual(len(client.bundles), 1)

    def test_generated_child_runs_through_existing_instruction_boundary(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        proposal = parse_mutation_proposal(
            '{"analysis":"Use evidence.",'
            '"system_instruction":"Inspect evidence before answering."}'
        )
        child = create_child_candidate(
            parent,
            proposal,
            source_run_ids=("run_1",),
            mutation_id="mutation_fixed",
            created_at=FIXED_NOW,
        )
        pool = DEFAULT_CANDIDATE_POOL.with_candidate(child)
        responses = FakeResponsesClient(
            {
                "id": "resp_final",
                "status": "completed",
                "output_text": "I need to investigate further.",
                "output": [],
            }
        )

        record = run_candidate_scenario(
            child.candidate_id,
            candidate_pool=pool,
            responses_client=responses,
            clock=lambda: FIXED_NOW,
            persist=False,
        )

        self.assertEqual(
            responses.calls[0]["instructions"],
            "Inspect evidence before answering.",
        )
        self.assertEqual(record.candidate_id, child.candidate_id)
        self.assertEqual(record.parent_candidate_id, parent.candidate_id)
        self.assertEqual(record.candidate_generation, 1)
        self.assertNotIn("optimizer_metadata", record.agent_visible_scenario)

    def test_reflect_and_create_child_rejects_bad_mutations_and_api_errors(self) -> None:
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        bundle = build_reflection_bundle(
            parent,
            _suite([_record("run_1", "scenario_a", score=0.4, passed=False)]),
        )
        cases = [
            (
                FakeReflectionClient(error=RuntimeError("offline")),
                "reflection_error",
            ),
            (FakeReflectionClient("not json"), "invalid_response"),
            (
                FakeReflectionClient(
                    json.dumps(
                        {
                            "analysis": "No change.",
                            "system_instruction": parent.payload["system_instruction"],
                        }
                    )
                ),
                "unchanged_instruction",
            ),
            (
                FakeReflectionClient(
                    '{"analysis":"Memorize.",'
                    '"system_instruction":"Always special-case scenario_a."}'
                ),
                "identifier_memorization",
            ),
            (
                FakeReflectionClient(
                    '{"analysis":"Memorize a ticket.",'
                    '"system_instruction":"Always special-case tkt_1001."}'
                ),
                "identifier_memorization",
            ),
            (
                FakeReflectionClient(
                    json.dumps(
                        {
                            "analysis": "Too long.",
                            "system_instruction": "x"
                            * (MAX_SYSTEM_INSTRUCTION_LENGTH + 1),
                        }
                    )
                ),
                "instruction_too_long",
            ),
        ]

        for client, error_type in cases:
            with self.subTest(error_type=error_type):
                result = reflect_and_create_child(
                    parent,
                    bundle,
                    client,
                    mutation_id_factory=lambda: "mutation_fixed",
                    clock=lambda: FIXED_NOW,
                )
                self.assertFalse(result.succeeded)
                self.assertIsNone(result.child)
                self.assertEqual(result.error.error_type, error_type)

    def test_openai_reflection_client_uses_existing_responses_boundary_without_tools(
        self,
    ) -> None:
        responses = FakeResponsesClient(
            {
                "status": "completed",
                "output_text": '{"analysis":"a","system_instruction":"b"}',
            }
        )
        client = OpenAIReflectionClient(responses_client=responses, model="test-model")
        parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
        bundle = build_reflection_bundle(
            parent,
            _suite([_record("run_1", "scenario_a")]),
        )

        output = client.reflect(bundle)

        self.assertEqual(output, '{"analysis":"a","system_instruction":"b"}')
        self.assertEqual(len(responses.calls), 1)
        call = responses.calls[0]
        self.assertEqual(call["model"], "test-model")
        self.assertEqual(call["tools"], [])
        self.assertEqual(call["temperature"], 0.0)
        self.assertFalse(call["parallel_tool_calls"])
        self.assertIn(PARENT_ID, call["input"])


def _suite(
    records: list[RunRecord],
    *,
    candidate_id: str = PARENT_ID,
    repeat_count: int = 1,
) -> CandidateSuiteRun:
    normalized = [
        _replace_candidate(record, candidate_id)
        if record.candidate_id != candidate_id
        else record
        for record in records
    ]
    matrix = build_score_matrix(normalized)
    scenario_ids = tuple(sorted({record.scenario_id for record in normalized}))
    return CandidateSuiteRun(
        suite_name="training",
        candidate_id=candidate_id,
        scenario_ids=scenario_ids,
        repeat_count=repeat_count,
        expected_run_count=len(normalized),
        records=tuple(normalized),
        errors=(),
        matrix=matrix,
    )


def _record(
    run_id: str,
    scenario_id: str,
    *,
    score: float = 1.0,
    passed: bool = True,
) -> RunRecord:
    parent = DEFAULT_CANDIDATE_POOL.require(PARENT_ID)
    failure_tags = [] if passed else ["wrong_root_cause"]
    return RunRecord(
        run_id=run_id,
        scenario_id=scenario_id,
        scenario_version="1.0.0",
        environment_id="support_env_v1",
        agent_name=parent.agent_name,
        agent_version=parent.agent_version,
        started_at=FIXED_NOW,
        completed_at=FIXED_NOW,
        initial_state_hash="initial",
        final_state_hash="final",
        state_diff={},
        agent_visible_scenario={},
        tool_calls=[],
        final_response=f"response {run_id}",
        evaluation={
            "passed": passed,
            "score": score,
            "failure_tags": failure_tags,
            "fatal_tags": failure_tags,
            "nonfatal_tags": [],
            "eligible_for_selection": passed,
            "checks": [],
            "notes": [],
            "feedback_text": f"feedback {run_id}",
            "trace_excerpt": [
                "get_ticket(ok) args={'ticket_id': 'tkt_1001'}"
            ],
        },
        agent_visible_evaluation={"passed": passed, "score": score},
        candidate_id=parent.candidate_id,
        parent_candidate_id=parent.parent_id,
        candidate_generation=parent.generation,
        candidate_kind=parent.kind,
    )


def _replace_candidate(record: RunRecord, candidate_id: str) -> RunRecord:
    candidate = DEFAULT_CANDIDATE_POOL.require(candidate_id)
    values = record.to_dict()
    values.update(
        {
            "candidate_id": candidate.candidate_id,
            "agent_name": candidate.agent_name,
            "agent_version": candidate.agent_version,
            "parent_candidate_id": candidate.parent_id,
            "candidate_generation": candidate.generation,
            "candidate_kind": candidate.kind,
            "started_at": record.started_at,
            "completed_at": record.completed_at,
        }
    )
    return RunRecord(**values)


if __name__ == "__main__":
    unittest.main()
