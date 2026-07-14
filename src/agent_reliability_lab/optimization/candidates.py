"""Local candidate pool for deterministic optimizer experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from agent_reliability_lab.agents.baseline import (
    BASELINE_AGENT_NAME,
    BASELINE_AGENT_VERSION,
)
from agent_reliability_lab.agents.openai_runner import (
    DEGRADED_SYSTEM_INSTRUCTION,
    OPENAI_DEGRADED_AGENT_VERSION,
    OPENAI_POLICY_AGENT_NAME,
)


BASELINE_CANDIDATE_ID = "cand_baseline_v1"


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    agent_name: str
    agent_version: str
    parent_id: str | None
    generation: int
    kind: str
    description: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CandidatePool:
    """Immutable candidate registry keyed by stable candidate ID."""

    def __init__(self, candidates: Iterable[Candidate]) -> None:
        ordered = tuple(candidates)
        by_id: dict[str, Candidate] = {}
        by_version: dict[str, Candidate] = {}
        for candidate in ordered:
            if candidate.candidate_id in by_id:
                raise ValueError(f"Duplicate candidate_id: {candidate.candidate_id}")
            if candidate.agent_version in by_version:
                raise ValueError(
                    f"Duplicate agent_version: {candidate.agent_version}"
                )
            if candidate.generation < 0:
                raise ValueError(
                    f"Candidate generation must be non-negative: {candidate.candidate_id}"
                )
            by_id[candidate.candidate_id] = candidate
            by_version[candidate.agent_version] = candidate

        missing_parents = sorted(
            candidate.parent_id
            for candidate in ordered
            if candidate.parent_id is not None and candidate.parent_id not in by_id
        )
        if missing_parents:
            raise ValueError(f"Unknown candidate parent_id values: {missing_parents}")

        self._candidates = ordered
        self._by_id = by_id
        self._by_version = by_version

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        return self._candidates

    def get(self, candidate_id: str) -> Candidate | None:
        return self._by_id.get(candidate_id)

    def require(self, candidate_id: str) -> Candidate:
        candidate = self.get(candidate_id)
        if candidate is None:
            raise KeyError(f"Unknown candidate_id: {candidate_id}")
        return candidate

    def find_by_agent_version(self, agent_version: str) -> Candidate | None:
        return self._by_version.get(agent_version)

    def with_candidate(self, candidate: Candidate) -> CandidatePool:
        """Return a validated pool containing one additional candidate."""

        return CandidatePool((*self._candidates, candidate))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self._candidates],
        }


DEFAULT_CANDIDATE_POOL = CandidatePool(
    (
        Candidate(
            candidate_id=BASELINE_CANDIDATE_ID,
            agent_name=BASELINE_AGENT_NAME,
            agent_version=BASELINE_AGENT_VERSION,
            parent_id=None,
            generation=0,
            kind="baseline",
            description="Deterministic passing baseline support agent.",
            payload={"workflow": "full_evidence_then_escalate"},
        ),
        Candidate(
            candidate_id="cand_missing_auth_logs_v1",
            agent_name="missing_auth_logs_support_agent",
            agent_version="candidate-missing-auth-logs-v1",
            parent_id=BASELINE_CANDIDATE_ID,
            generation=1,
            kind="missing_auth_logs",
            description="Synthetic variant that skips auth-log evidence.",
            payload={"failure_mode": "missing_required_auth_log_evidence"},
        ),
        Candidate(
            candidate_id="cand_reset_failure_v1",
            agent_name="reset_failure_support_agent",
            agent_version="candidate-reset-failure-v1",
            parent_id=BASELINE_CANDIDATE_ID,
            generation=1,
            kind="reset_failure",
            description="Synthetic variant that hallucinates reset failure.",
            payload={"failure_mode": "hallucinated_password_reset_failure"},
        ),
        Candidate(
            candidate_id="cand_unsafe_unlock_v1",
            agent_name="unsafe_unlock_support_agent",
            agent_version="candidate-unsafe-unlock-v1",
            parent_id=BASELINE_CANDIDATE_ID,
            generation=1,
            kind="unsafe_unlock",
            description="Synthetic variant that attempts unlock before verification.",
            payload={"failure_mode": "policy_unsafe_unlock_attempt"},
        ),
        Candidate(
            candidate_id="cand_openai_degraded_v1",
            agent_name=OPENAI_POLICY_AGENT_NAME,
            agent_version=OPENAI_DEGRADED_AGENT_VERSION,
            parent_id=None,
            generation=0,
            kind="openai_policy",
            description=(
                "Safety-gated OpenAI policy with reduced response QA for GEPA "
                "measurement."
            ),
            payload={
                "system_instruction": DEGRADED_SYSTEM_INSTRUCTION,
            },
        ),
    )
)
