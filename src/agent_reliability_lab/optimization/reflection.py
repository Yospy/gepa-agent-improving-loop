"""Reflection-driven system-instruction mutation for GEPA candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Callable, Protocol
from uuid import uuid4

from agent_reliability_lab.agents.openai_runner import (
    DEFAULT_FIREWORKS_FREQUENCY_PENALTY,
    DEFAULT_FIREWORKS_PRESENCE_PENALTY,
    DEFAULT_FIREWORKS_TEACHER_MAX_TOKENS,
    DEFAULT_FIREWORKS_TEACHER_MODEL,
    DEFAULT_FIREWORKS_TOP_K,
    DEFAULT_TEMPERATURE,
    FireworksChatCompletionsClient,
    ResponsesClient,
)
from agent_reliability_lab.optimization.candidates import Candidate
from agent_reliability_lab.runs.suite import CandidateSuiteRun


MAX_SYSTEM_INSTRUCTION_LENGTH = 12_000
RECORD_IDENTIFIER_PATTERN = re.compile(
    r"\b(?:acct|audit|auth|doc|idv|lock|mfa|note|org|pol|prst|req|sess|tkt|usr)"
    r"_[a-zA-Z0-9_-]+\b",
    re.IGNORECASE,
)

REFLECTION_INSTRUCTIONS = """You improve a support agent's system instruction from evaluated trajectories.

Return exactly one JSON object with exactly two string fields:
- analysis: a concise explanation of the general policy failures and preserved strengths.
- system_instruction: the complete replacement system instruction.

Generalize across scenarios. Do not copy run IDs, scenario IDs, ticket IDs, user
IDs, account IDs, or evaluator-only record identifiers into the instruction.
Only revise agent behavior. Do not propose changes to tools, scenarios, evaluator
rules, model configuration, temperature, or step limits. Preserve successful
behavior while correcting failures.

Treat these as runtime-enforced invariants that the replacement must preserve,
not redesign or weaken: ticket-first requester binding, required evidence tool
calls, active-policy lookup, and the allowed write capability. Do not spend
mutation effort recreating their enforcement.

Focus mutations on the remaining mutable behavior: event time-window selection,
diagnosis language, policy query quality, escalation evidence composition using
concrete record identifiers returned by tools, explicit completed-action
confirmation, and safe next steps in the final customer response. Turn failed
mutable checks into general, executable rules. Public tool names may be used;
example-specific identifiers may not."""
REFLECTION_RESPONSE_FORMAT = {"type": "json_object"}

Clock = Callable[[], datetime]
MutationIDFactory = Callable[[], str]


@dataclass(frozen=True)
class ReflectionExample:
    run_id: str
    scenario_id: str
    passed: bool
    score: float
    failure_tags: tuple[str, ...]
    feedback_text: str
    trace_excerpt: tuple[str, ...]
    final_response: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "passed": self.passed,
            "score": self.score,
            "failure_tags": list(self.failure_tags),
            "feedback_text": self.feedback_text,
            "trace_excerpt": list(self.trace_excerpt),
            "final_response": self.final_response,
        }


@dataclass(frozen=True)
class ReflectionBundle:
    parent_candidate_id: str
    parent_system_instruction: str
    suite_name: str
    examples: tuple[ReflectionExample, ...]
    revision_feedback: str | None = None

    @property
    def source_run_ids(self) -> tuple[str, ...]:
        return tuple(example.run_id for example in self.examples)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "parent_candidate_id": self.parent_candidate_id,
            "parent_system_instruction": self.parent_system_instruction,
            "suite_name": self.suite_name,
            "examples": [example.to_dict() for example in self.examples],
        }
        if self.revision_feedback is not None:
            payload["revision_feedback"] = self.revision_feedback
        return payload

    def with_revision_feedback(self, feedback: str) -> ReflectionBundle:
        normalized = feedback.strip() if isinstance(feedback, str) else ""
        if not normalized:
            raise ValueError("Revision feedback must be a non-empty string.")
        return ReflectionBundle(
            parent_candidate_id=self.parent_candidate_id,
            parent_system_instruction=self.parent_system_instruction,
            suite_name=self.suite_name,
            examples=self.examples,
            revision_feedback=normalized,
        )


@dataclass(frozen=True)
class MutationProposal:
    analysis: str
    system_instruction: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class MutationError:
    error_type: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class MutationResult:
    mutation_id: str
    parent_candidate_id: str
    source_run_ids: tuple[str, ...]
    proposal: MutationProposal | None
    child: Candidate | None
    error: MutationError | None

    @property
    def succeeded(self) -> bool:
        return self.child is not None and self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation_id": self.mutation_id,
            "parent_candidate_id": self.parent_candidate_id,
            "source_run_ids": list(self.source_run_ids),
            "succeeded": self.succeeded,
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "child": self.child.to_dict() if self.child else None,
            "error": self.error.to_dict() if self.error else None,
        }


class ReflectionClient(Protocol):
    def reflect(self, bundle: ReflectionBundle) -> str: ...


class OpenAIReflectionClient:
    """Live Fireworks reflection adapter over the internal response boundary."""

    def __init__(
        self,
        *,
        responses_client: ResponsesClient | None = None,
        model: str = DEFAULT_FIREWORKS_TEACHER_MODEL,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Reflection model must be non-empty.")
        self._client = responses_client or FireworksChatCompletionsClient()
        self._model = model.strip()

    def reflect(self, bundle: ReflectionBundle) -> str:
        response = self._client.create_response(
            model=self._model,
            instructions=REFLECTION_INSTRUCTIONS,
            input=format_reflection_input(bundle),
            tools=[],
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_FIREWORKS_TEACHER_MAX_TOKENS,
            top_k=DEFAULT_FIREWORKS_TOP_K,
            presence_penalty=DEFAULT_FIREWORKS_PRESENCE_PENALTY,
            frequency_penalty=DEFAULT_FIREWORKS_FREQUENCY_PENALTY,
            parallel_tool_calls=False,
            response_format=REFLECTION_RESPONSE_FORMAT,
            previous_response_id=None,
        )
        status = _response_value(response, "status")
        if status not in (None, "completed"):
            raise RuntimeError(f"Reflection response was not completed: {status!r}")
        output_text = _response_value(response, "output_text")
        if not isinstance(output_text, str) or not output_text.strip():
            raise RuntimeError("Reflection response contained no output text.")
        return output_text


class _MutationValidationError(ValueError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def build_reflection_bundle(
    parent: Candidate,
    suite_run: CandidateSuiteRun,
) -> ReflectionBundle:
    """Select one deterministic optimizer example per scenario."""

    parent_instruction = _parent_instruction(parent)
    if not suite_run.complete:
        raise ValueError("Reflection requires a complete comparable parent suite.")
    if suite_run.candidate_id != parent.candidate_id:
        raise ValueError("Reflection suite candidate must match the parent candidate.")

    by_scenario: dict[str, list[Any]] = {
        scenario_id: [] for scenario_id in suite_run.scenario_ids
    }
    for record in suite_run.records:
        if record.candidate_id != parent.candidate_id:
            raise ValueError("Reflection record candidate must match the parent.")
        if record.scenario_id not in by_scenario:
            raise ValueError("Reflection record scenario is outside the suite.")
        by_scenario[record.scenario_id].append(record)

    examples: list[ReflectionExample] = []
    for scenario_id in sorted(by_scenario):
        records = by_scenario[scenario_id]
        if not records:
            raise ValueError(f"Reflection suite has no records for {scenario_id!r}.")
        selected = sorted(records, key=lambda item: (_score(item), item.run_id))[0]
        examples.append(_reflection_example(selected))

    return ReflectionBundle(
        parent_candidate_id=parent.candidate_id,
        parent_system_instruction=parent_instruction,
        suite_name=suite_run.suite_name,
        examples=tuple(examples),
    )


def format_reflection_input(bundle: ReflectionBundle) -> str:
    return json.dumps(bundle.to_dict(), indent=2, sort_keys=True)


def parse_mutation_proposal(response_text: str) -> MutationProposal:
    payload = _decode_mutation_payload(response_text)
    if not isinstance(payload, dict) or set(payload) != {
        "analysis",
        "system_instruction",
    }:
        raise ValueError(
            "Reflection response must contain exactly analysis and system_instruction."
        )
    analysis = payload["analysis"]
    instruction = payload["system_instruction"]
    if not isinstance(analysis, str) or not analysis.strip():
        raise ValueError("Mutation analysis must be a non-empty string.")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("Mutation system_instruction must be a non-empty string.")
    return MutationProposal(
        analysis=analysis.strip(),
        system_instruction=instruction.strip(),
    )


def _decode_mutation_payload(response_text: str) -> Any:
    if not isinstance(response_text, str):
        raise ValueError("Reflection response must be a JSON string.")
    normalized = response_text.strip()
    if not normalized:
        raise ValueError("Reflection response must be a non-empty JSON string.")

    try:
        return json.loads(normalized)
    except (json.JSONDecodeError, RecursionError) as exc:
        try:
            candidate = _embedded_json_object(normalized)
        except (json.JSONDecodeError, RecursionError):
            candidate = None
        if candidate is not None:
            return candidate
        raise ValueError(_json_decode_diagnostic(response_text, exc)) from exc


def _embedded_json_object(response_text: str) -> dict[str, Any] | None:
    start = response_text.find("{")
    end = response_text.rfind("}")
    if start < 0 or end < start:
        return None
    prefix = response_text[:start]
    suffix = response_text[end + 1 :]
    if any(token in prefix or token in suffix for token in "{}[]"):
        return None
    payload = json.loads(response_text[start : end + 1])
    return payload if isinstance(payload, dict) else None


def _json_decode_diagnostic(
    response_text: str,
    error: json.JSONDecodeError | RecursionError,
) -> str:
    stripped = response_text.strip()
    digest = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
    if isinstance(error, json.JSONDecodeError):
        decode_detail = (
            f"decode_error={error.msg!r} line={error.lineno} column={error.colno}"
        )
    else:
        decode_detail = "decode_error='maximum nesting depth exceeded'"
    return (
        "Reflection response must contain one valid JSON object. "
        f"{decode_detail} "
        f"chars={len(response_text)} bytes={len(response_text.encode('utf-8'))} "
        f"sha256={digest} "
        f"starts_with_code_fence={str(stripped.startswith('```')).lower()} "
        f"ends_with_code_fence={str(stripped.endswith('```')).lower()}"
    )


def create_child_candidate(
    parent: Candidate,
    proposal: MutationProposal,
    *,
    source_run_ids: tuple[str, ...],
    mutation_id: str,
    created_at: datetime,
) -> Candidate:
    parent_instruction = _parent_instruction(parent)
    _validate_instruction(parent_instruction, proposal.system_instruction, ())
    token = _identifier_token(mutation_id)
    generation = parent.generation + 1
    child_instruction = proposal.system_instruction.strip()
    return Candidate(
        candidate_id=f"cand_openai_gepa_g{generation}_{token}",
        agent_name=parent.agent_name,
        agent_version=f"openai-gepa-policy-g{generation}-{token}",
        parent_id=parent.candidate_id,
        generation=generation,
        kind="openai_policy",
        description=f"GEPA-generated policy child of {parent.candidate_id}.",
        payload={
            "system_instruction": child_instruction,
            "optimizer_metadata": {
                "mutation_id": mutation_id,
                "analysis": proposal.analysis,
                "source_run_ids": list(source_run_ids),
                "created_at": created_at.isoformat(),
                "parent_instruction_sha256": _sha256(parent_instruction),
                "child_instruction_sha256": _sha256(child_instruction),
            },
        },
    )


def reflect_and_create_child(
    parent: Candidate,
    bundle: ReflectionBundle,
    reflection_client: ReflectionClient,
    *,
    mutation_id_factory: MutationIDFactory = lambda: uuid4().hex,
    clock: Clock = lambda: datetime.now(timezone.utc),
) -> MutationResult:
    if bundle.parent_candidate_id != parent.candidate_id:
        raise ValueError("Reflection bundle parent must match the candidate.")
    mutation_id = mutation_id_factory()
    if not isinstance(mutation_id, str) or not mutation_id.strip():
        raise ValueError("Mutation ID factory must return a non-empty string.")
    mutation_id = mutation_id.strip()

    try:
        response_text = reflection_client.reflect(bundle)
    except Exception as exc:  # pragma: no cover - live SDK exception types vary.
        return _failed_mutation(
            mutation_id,
            parent,
            bundle,
            "reflection_error",
            str(exc),
        )

    try:
        proposal = parse_mutation_proposal(response_text)
    except ValueError as exc:
        return _failed_mutation(
            mutation_id,
            parent,
            bundle,
            "invalid_response",
            str(exc),
        )

    try:
        _validate_instruction(
            bundle.parent_system_instruction,
            proposal.system_instruction,
            _optimizer_only_identifiers(bundle),
        )
        child = create_child_candidate(
            parent,
            proposal,
            source_run_ids=bundle.source_run_ids,
            mutation_id=mutation_id,
            created_at=clock(),
        )
    except _MutationValidationError as exc:
        return MutationResult(
            mutation_id=mutation_id,
            parent_candidate_id=parent.candidate_id,
            source_run_ids=bundle.source_run_ids,
            proposal=proposal,
            child=None,
            error=MutationError(exc.error_type, str(exc)),
        )

    return MutationResult(
        mutation_id=mutation_id,
        parent_candidate_id=parent.candidate_id,
        source_run_ids=bundle.source_run_ids,
        proposal=proposal,
        child=child,
        error=None,
    )


def _reflection_example(record: Any) -> ReflectionExample:
    evaluation = record.evaluation
    if not isinstance(evaluation, dict):
        raise ValueError("Reflection record evaluation must be an object.")
    passed = evaluation.get("passed")
    score = evaluation.get("score")
    failure_tags = evaluation.get("failure_tags")
    feedback_text = evaluation.get("feedback_text")
    trace_excerpt = evaluation.get("trace_excerpt")
    if not isinstance(passed, bool):
        raise ValueError("Reflection evaluation passed must be boolean.")
    if (
        not isinstance(score, int | float)
        or isinstance(score, bool)
    ):
        raise ValueError("Reflection evaluation score must be numeric.")
    if not isinstance(failure_tags, list) or not all(
        isinstance(tag, str) for tag in failure_tags
    ):
        raise ValueError("Reflection failure_tags must be a string list.")
    if not isinstance(feedback_text, str):
        raise ValueError("Reflection feedback_text must be a string.")
    if not isinstance(trace_excerpt, list) or not all(
        isinstance(item, str) for item in trace_excerpt
    ):
        raise ValueError("Reflection trace_excerpt must be a string list.")
    if not isinstance(record.final_response, str):
        raise ValueError("Reflection final_response must be a string.")
    return ReflectionExample(
        run_id=record.run_id,
        scenario_id=record.scenario_id,
        passed=passed,
        score=float(score),
        failure_tags=tuple(failure_tags),
        feedback_text=feedback_text,
        trace_excerpt=tuple(trace_excerpt),
        final_response=record.final_response,
    )


def _score(record: Any) -> float:
    evaluation = record.evaluation
    if not isinstance(evaluation, dict):
        raise ValueError("Reflection record evaluation must be an object.")
    score = evaluation.get("score")
    if not isinstance(score, int | float) or isinstance(score, bool):
        raise ValueError("Reflection evaluation score must be numeric.")
    return float(score)


def _parent_instruction(parent: Candidate) -> str:
    if parent.kind != "openai_policy":
        raise ValueError("Only openai_policy candidates can be reflected.")
    instruction = parent.payload.get("system_instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("Mutable candidate must have a system_instruction.")
    return instruction.strip()


def _validate_instruction(
    parent_instruction: str,
    child_instruction: str,
    forbidden_identifiers: tuple[str, ...],
) -> None:
    normalized = child_instruction.strip()
    if not normalized:
        raise _MutationValidationError(
            "empty_instruction",
            "Mutated system instruction must be non-empty.",
        )
    if normalized == parent_instruction.strip():
        raise _MutationValidationError(
            "unchanged_instruction",
            "Mutated system instruction must differ from the parent.",
        )
    if len(normalized) > MAX_SYSTEM_INSTRUCTION_LENGTH:
        raise _MutationValidationError(
            "instruction_too_long",
            f"Mutated system instruction exceeds {MAX_SYSTEM_INSTRUCTION_LENGTH} characters.",
        )
    lowered = normalized.casefold()
    memorized = sorted(
        identifier
        for identifier in forbidden_identifiers
        if identifier and _contains_exact_identifier(lowered, identifier.casefold())
    )
    if memorized:
        raise _MutationValidationError(
            "identifier_memorization",
            f"Mutated instruction contains optimizer-only identifiers: {memorized}",
        )


def _contains_exact_identifier(text: str, identifier: str) -> bool:
    return bool(
        re.search(
            rf"(?<![a-zA-Z0-9_]){re.escape(identifier)}(?![a-zA-Z0-9_])",
            text,
        )
    )


def _failed_mutation(
    mutation_id: str,
    parent: Candidate,
    bundle: ReflectionBundle,
    error_type: str,
    message: str,
) -> MutationResult:
    return MutationResult(
        mutation_id=mutation_id,
        parent_candidate_id=parent.candidate_id,
        source_run_ids=bundle.source_run_ids,
        proposal=None,
        child=None,
        error=MutationError(error_type, message),
    )


def _optimizer_only_identifiers(bundle: ReflectionBundle) -> tuple[str, ...]:
    identifiers = {
        *bundle.source_run_ids,
        *(example.scenario_id for example in bundle.examples),
    }
    for example in bundle.examples:
        source_text = "\n".join(
            (
                example.feedback_text,
                *example.trace_excerpt,
                example.final_response,
            )
        )
        identifiers.update(RECORD_IDENTIFIER_PATTERN.findall(source_text))
    return tuple(sorted(identifiers))


def _identifier_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")
    if not token:
        raise ValueError("Mutation ID must contain an identifier character.")
    return token[:48]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _response_value(response: Any, name: str) -> Any:
    if isinstance(response, dict):
        return response.get(name)
    return getattr(response, name, None)
