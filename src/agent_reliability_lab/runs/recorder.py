"""Run the baseline agent and persist auditable trajectories."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

from agent_reliability_lab.agents import (
    BaselineSupportAgent,
    DEFAULT_FIREWORKS_AGENT_MODEL,
    DEFAULT_MAX_STEPS,
    DEFAULT_TEMPERATURE,
    MissingAuthLogsSupportAgent,
    OpenAISupportAgent,
    ResetFailureSupportAgent,
    UnsafeUnlockSupportAgent,
)
from agent_reliability_lab.agents.openai_runner import ResponsesClient
from agent_reliability_lab.environment import (
    DEFAULT_ENVIRONMENT_PATH,
    EnvironmentStore,
    SupportToolService,
)
from agent_reliability_lab.evaluation import AgentAttempt, evaluate_attempt
from agent_reliability_lab.optimization.candidates import (
    BASELINE_CANDIDATE_ID,
    DEFAULT_CANDIDATE_POOL,
    Candidate,
    CandidatePool,
)
from agent_reliability_lab.scenarios import DEFAULT_SCENARIO_PATH, load_scenario
from agent_reliability_lab.runs.models import RunRecord


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN_OUTPUT_DIR = REPO_ROOT / ".runs"

Clock = Callable[[], datetime]


class AgentRunResult(Protocol):
    """Minimal shape shared by every candidate agent's `run()` result."""

    agent_name: str
    agent_version: str
    final_response: str


class RunRecorder:
    def __init__(self, output_dir: Path | str = DEFAULT_RUN_OUTPUT_DIR) -> None:
        self.output_dir = Path(output_dir)

    def record_path(self, record: RunRecord) -> Path:
        return self.output_dir / f"{record.run_id}.json"

    def save(self, record: RunRecord) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.record_path(record)
        with path.open("x", encoding="utf-8") as handle:
            json.dump(record.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
        return path


def run_baseline_scenario(
    *,
    scenario_path: Path | str = DEFAULT_SCENARIO_PATH,
    environment_path: Path | str = DEFAULT_ENVIRONMENT_PATH,
    output_dir: Path | str = DEFAULT_RUN_OUTPUT_DIR,
    clock: Clock | None = None,
    persist: bool = True,
) -> RunRecord:
    return run_candidate_scenario(
        candidate_id=BASELINE_CANDIDATE_ID,
        scenario_path=scenario_path,
        environment_path=environment_path,
        output_dir=output_dir,
        clock=clock,
        persist=persist,
    )


def run_candidate_scenario(
    candidate_id: str,
    *,
    scenario_path: Path | str = DEFAULT_SCENARIO_PATH,
    environment_path: Path | str = DEFAULT_ENVIRONMENT_PATH,
    output_dir: Path | str = DEFAULT_RUN_OUTPUT_DIR,
    candidate_pool: CandidatePool = DEFAULT_CANDIDATE_POOL,
    clock: Clock | None = None,
    persist: bool = True,
    responses_client: ResponsesClient | None = None,
) -> RunRecord:
    run_clock = clock or _utc_now
    started_at = run_clock()
    candidate = candidate_pool.require(candidate_id)

    store = EnvironmentStore.from_seed(environment_path)
    scenario = load_scenario(scenario_path, environment_state=store.snapshot())
    initial_state = store.snapshot()
    initial_state_hash = store.state_hash()

    tools = SupportToolService(
        store,
        actor_id=f"agent:{candidate.agent_name}",
        clock=run_clock,
    )
    agent_result = _run_candidate_agent(
        candidate,
        tools,
        scenario.to_agent_visible_dict(),
        responses_client=responses_client,
        clock=run_clock,
    )
    _assert_candidate_result_matches(candidate, agent_result)

    final_state = store.snapshot()
    final_state_hash = store.state_hash()
    evaluation = evaluate_attempt(
        AgentAttempt(
            scenario=scenario,
            initial_state=initial_state,
            final_state=final_state,
            tool_calls=tools.call_log,
            final_response=agent_result.final_response,
        )
    )
    completed_at = run_clock()

    record = RunRecord(
        run_id=_build_run_id(
            scenario.metadata.scenario_id,
            agent_result.agent_version,
            started_at,
        ),
        scenario_id=scenario.metadata.scenario_id,
        scenario_version=scenario.metadata.version,
        environment_id=scenario.metadata.environment_id,
        agent_name=agent_result.agent_name,
        agent_version=agent_result.agent_version,
        started_at=started_at,
        completed_at=completed_at,
        initial_state_hash=initial_state_hash,
        final_state_hash=final_state_hash,
        state_diff=summarize_state_diff(initial_state, final_state),
        agent_visible_scenario=scenario.to_agent_visible_dict(),
        tool_calls=tools.call_log_as_dicts(),
        final_response=agent_result.final_response,
        evaluation=evaluation.to_dict(),
        agent_visible_evaluation=evaluation.to_agent_visible_dict(),
        candidate_id=candidate.candidate_id,
        parent_candidate_id=candidate.parent_id,
        candidate_generation=candidate.generation,
        candidate_kind=candidate.kind,
        agent_trace=_agent_trace(agent_result),
        agent_failure_reason=_agent_failure_reason(agent_result),
    )

    if persist:
        RunRecorder(output_dir).save(record)
    return record


def _run_candidate_agent(
    candidate: Candidate,
    tools: SupportToolService,
    visible_scenario: dict[str, Any],
    *,
    responses_client: ResponsesClient | None,
    clock: Clock,
) -> AgentRunResult:
    if candidate.kind == "baseline":
        return BaselineSupportAgent(tools).run(visible_scenario)
    if candidate.kind == "missing_auth_logs":
        return MissingAuthLogsSupportAgent(
            tools,
            agent_name=candidate.agent_name,
            agent_version=candidate.agent_version,
        ).run(visible_scenario)
    if candidate.kind == "reset_failure":
        return ResetFailureSupportAgent(
            tools,
            agent_name=candidate.agent_name,
            agent_version=candidate.agent_version,
        ).run(visible_scenario)
    if candidate.kind == "unsafe_unlock":
        return UnsafeUnlockSupportAgent(
            tools,
            agent_name=candidate.agent_name,
            agent_version=candidate.agent_version,
        ).run(visible_scenario)
    if candidate.kind == "openai_policy":
        return OpenAISupportAgent(
            tools,
            system_instruction=_candidate_system_instruction(candidate),
            agent_name=candidate.agent_name,
            agent_version=candidate.agent_version,
            model=_fireworks_agent_model(),
            temperature=DEFAULT_TEMPERATURE,
            max_steps=DEFAULT_MAX_STEPS,
            responses_client=responses_client,
            clock=clock,
        ).run(visible_scenario)
    raise ValueError(f"Unsupported candidate kind: {candidate.kind}")


def _assert_candidate_result_matches(
    candidate: Candidate, result: AgentRunResult
) -> None:
    if result.agent_name != candidate.agent_name:
        raise ValueError(
            f"Candidate agent_name mismatch: {result.agent_name} != {candidate.agent_name}"
        )
    if result.agent_version != candidate.agent_version:
        raise ValueError(
            "Candidate agent_version mismatch: "
            f"{result.agent_version} != {candidate.agent_version}"
        )


def _candidate_system_instruction(candidate: Candidate) -> str:
    value = candidate.payload.get("system_instruction")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"OpenAI policy candidate missing system_instruction: {candidate.candidate_id}"
        )
    return value


def _fireworks_agent_model() -> str:
    env_model = os.environ.get("FIREWORKS_AGENT_MODEL")
    if env_model:
        return env_model
    return DEFAULT_FIREWORKS_AGENT_MODEL


def _agent_trace(agent_result: Any) -> list[dict[str, Any]] | None:
    trace_as_dicts = getattr(agent_result, "trace_as_dicts", None)
    if callable(trace_as_dicts):
        trace = trace_as_dicts()
        if isinstance(trace, list):
            return trace
    return None


def _agent_failure_reason(agent_result: Any) -> str | None:
    value = getattr(agent_result, "failure_reason", None)
    return value if isinstance(value, str) and value else None


def summarize_state_diff(before: Any, after: Any) -> dict[str, Any]:
    return {
        "changed_tickets": _changed_ids(before.tickets, after.tickets),
        "changed_users": _changed_ids(before.users, after.users),
        "changed_lockouts": _changed_ids(before.lockouts, after.lockouts),
        "added_audit_entries": _added_ids(before.audit_log, after.audit_log),
    }


def _changed_ids(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(
        record_id
        for record_id in set(before) & set(after)
        if _stable_value(before[record_id]) != _stable_value(after[record_id])
    )


def _added_ids(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(set(after) - set(before))


def _stable_value(value: Any) -> Any:
    if is_dataclass(value):
        return _stable_value(asdict(value))
    if isinstance(value, dict):
        return {key: _stable_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    return value


def _build_run_id(scenario_id: str, agent_version: str, started_at: datetime) -> str:
    timestamp = started_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = _slugify(f"{scenario_id}-{agent_version}")
    return f"run_{timestamp}_{slug}_{uuid4().hex}"


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_dotenv() -> None:
    """Load Fireworks credentials/model settings for live CLI runs."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(
        description="Run a support-agent scenario."
    )
    parser.add_argument(
        "--candidate-id",
        default=BASELINE_CANDIDATE_ID,
        help=(
            "Candidate to run. Use cand_openai_degraded_v1 for the live "
            "OpenAI policy agent."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_RUN_OUTPUT_DIR),
        help="Directory where the run record JSON is written.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Run and print the summary without writing a JSON record.",
    )
    args = parser.parse_args(argv)

    record = run_candidate_scenario(
        args.candidate_id,
        output_dir=args.output_dir,
        persist=not args.no_persist,
    )
    path = RunRecorder(args.output_dir).record_path(record)
    summary = {
        "run_id": record.run_id,
        "passed": record.evaluation["passed"],
        "score": record.evaluation["score"],
        "path": None if args.no_persist else str(path),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
