"""Analyze persisted run records by evaluator failure tags."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class FailureBucket:
    key: str
    label: str
    aliases: tuple[str, ...]
    improvement_target: str


CANONICAL_FAILURE_BUCKETS = (
    FailureBucket(
        key="missing_evidence",
        label="missing evidence",
        aliases=("missing_evidence",),
        improvement_target=(
            "Tighten the evidence-gathering plan so required logs, policies, "
            "and identity state are observed before conclusion or action."
        ),
    ),
    FailureBucket(
        key="wrong_root_cause",
        label="wrong root cause",
        aliases=("wrong_root_cause",),
        improvement_target=(
            "Improve root-cause synthesis from tool observations, especially "
            "distinguishing reset success from lockout symptoms."
        ),
    ),
    FailureBucket(
        key="policy_violation",
        label="policy violation",
        aliases=("policy_violation",),
        improvement_target=(
            "Strengthen policy precondition checks before write actions, "
            "especially identity-verification requirements."
        ),
    ),
    FailureBucket(
        key="wrong_user",
        label="wrong user",
        aliases=("wrong_user",),
        improvement_target=(
            "Improve entity resolution and requester binding before reading, "
            "citing, or acting on user records."
        ),
    ),
    FailureBucket(
        key="stale_policy",
        label="stale policy",
        aliases=("stale_policy", "stale_policy_used"),
        improvement_target=(
            "Prefer active policy documents and explicitly ignore deprecated "
            "documents when policy records conflict."
        ),
    ),
    FailureBucket(
        key="poor_final_response",
        label="poor final response",
        aliases=("poor_final_response",),
        improvement_target=(
            "Improve final response grounding so it states the confirmed cause, "
            "acknowledges reset status, and gives the safe next step."
        ),
    ),
)

EXTRA_IMPROVEMENT_TARGETS = {
    "final_state_mismatch": (
        "Align write actions and ticket state changes with the expected "
        "scenario outcome."
    ),
    "hallucinated_password_reset_failure": (
        "Prevent unsupported reset-failure claims when reset records show "
        "success."
    ),
}


@dataclass(frozen=True)
class LoadedRunRecord:
    path: str
    record: dict[str, Any]

    @property
    def run_id(self) -> str:
        return _string_value(self.record.get("run_id"), default=self.path)

    @property
    def agent_version(self) -> str:
        return _string_value(self.record.get("agent_version"), default="unknown")

    @property
    def scenario_id(self) -> str:
        return _string_value(self.record.get("scenario_id"), default="unknown")

    @property
    def passed(self) -> bool:
        return bool(_evaluation(self.record).get("passed", False))

    @property
    def score(self) -> float:
        score = _evaluation(self.record).get("score", 0.0)
        if isinstance(score, int | float):
            return float(score)
        raise ValueError(f"Run {self.run_id} has non-numeric evaluation score.")

    @property
    def failure_tags(self) -> list[str]:
        return _failure_tags(self.record)


@dataclass(frozen=True)
class FailureSummary:
    failure: str
    label: str
    count: int
    run_ids: list[str]
    scenario_ids: list[str]
    agent_versions: list[str]
    suggested_improvement_target: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImprovementReportRow:
    run_id: str
    agent_version: str
    scenario_id: str
    passed: bool
    score: float
    failure_tags: list[str]
    suggested_improvement_targets: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FailureAnalysisReport:
    run_count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    average_score: float
    agent_versions: dict[str, dict[str, Any]]
    failure_summaries: list[FailureSummary]
    improvement_reports: list[ImprovementReportRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_count": self.run_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "pass_rate": self.pass_rate,
            "average_score": self.average_score,
            "agent_versions": self.agent_versions,
            "failure_summaries": [
                summary.to_dict() for summary in self.failure_summaries
            ],
            "improvement_reports": [
                report.to_dict() for report in self.improvement_reports
            ],
        }


@dataclass(frozen=True)
class RunSetComparison:
    baseline_label: str
    candidate_label: str
    baseline: dict[str, Any]
    candidate: dict[str, Any]
    deltas: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_run_records(path: Path | str) -> list[LoadedRunRecord]:
    """Load run record JSON files from one file or a directory tree."""

    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"Run path does not exist: {root}")

    files = [root] if root.is_file() else sorted(root.rglob("*.json"))
    records: list[LoadedRunRecord] = []
    for file_path in files:
        with file_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"Run record must be a JSON object: {file_path}")
        _assert_run_record_shape(payload, file_path)
        records.append(LoadedRunRecord(path=str(file_path), record=payload))
    return records


def analyze_runs(
    records: Iterable[LoadedRunRecord | dict[str, Any]],
) -> FailureAnalysisReport:
    loaded = [_ensure_loaded_run(record) for record in records]
    passed_count = sum(1 for record in loaded if record.passed)
    failed_records = [record for record in loaded if not record.passed]
    score_total = sum(record.score for record in loaded)
    run_count = len(loaded)

    return FailureAnalysisReport(
        run_count=run_count,
        passed_count=passed_count,
        failed_count=len(failed_records),
        pass_rate=_ratio(passed_count, run_count),
        average_score=round(score_total / run_count, 4) if run_count else 0.0,
        agent_versions=_agent_version_summary(loaded),
        failure_summaries=_build_failure_summaries(failed_records),
        improvement_reports=[
            _build_improvement_row(record) for record in loaded
        ],
    )


def compare_run_sets(
    baseline_records: Iterable[LoadedRunRecord | dict[str, Any]],
    candidate_records: Iterable[LoadedRunRecord | dict[str, Any]],
    *,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
) -> RunSetComparison:
    baseline = analyze_runs(baseline_records)
    candidate = analyze_runs(candidate_records)
    return _build_comparison(
        baseline,
        candidate,
        baseline_label=baseline_label,
        candidate_label=candidate_label,
    )


def compare_agent_versions(
    records: Iterable[LoadedRunRecord | dict[str, Any]],
    baseline_agent_version: str,
    candidate_agent_version: str,
) -> RunSetComparison:
    loaded = [_ensure_loaded_run(record) for record in records]
    baseline = [
        record
        for record in loaded
        if record.agent_version == baseline_agent_version
    ]
    candidate = [
        record
        for record in loaded
        if record.agent_version == candidate_agent_version
    ]
    if not baseline:
        raise ValueError(f"No records found for {baseline_agent_version!r}.")
    if not candidate:
        raise ValueError(f"No records found for {candidate_agent_version!r}.")
    return compare_run_sets(
        baseline,
        candidate,
        baseline_label=baseline_agent_version,
        candidate_label=candidate_agent_version,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze deterministic agent run failures."
    )
    parser.add_argument(
        "run_path",
        help="Run record JSON file or directory, usually .runs.",
    )
    parser.add_argument(
        "--compare-run-path",
        "--compare",
        dest="compare_run_path",
        help="Optional second run directory or file to compare against run_path.",
    )
    parser.add_argument(
        "--agent-version",
        help="Filter analysis to one agent version, or use as comparison baseline.",
    )
    parser.add_argument(
        "--compare-agent-version",
        help="Compare --agent-version with another version inside run_path.",
    )
    args = parser.parse_args(argv)

    records = load_run_records(args.run_path)
    if args.compare_agent_version:
        if not args.agent_version:
            parser.error("--compare-agent-version requires --agent-version")
        output = compare_agent_versions(
            records,
            args.agent_version,
            args.compare_agent_version,
        ).to_dict()
    else:
        filtered = _filter_agent_version(records, args.agent_version)
        report = analyze_runs(filtered)
        if args.compare_run_path:
            comparison_records = load_run_records(args.compare_run_path)
            output = compare_run_sets(
                filtered,
                comparison_records,
                baseline_label=args.run_path,
                candidate_label=args.compare_run_path,
            ).to_dict()
        else:
            output = report.to_dict()

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def _assert_run_record_shape(record: dict[str, Any], path: Path) -> None:
    required = {
        "run_id",
        "scenario_id",
        "agent_version",
        "evaluation",
    }
    missing = sorted(required - set(record))
    if missing:
        raise ValueError(f"Run record {path} is missing keys: {missing}")
    evaluation = record["evaluation"]
    if not isinstance(evaluation, dict):
        raise ValueError(f"Run record {path} has invalid evaluation payload.")
    for key in ("passed", "score"):
        if key not in evaluation:
            raise ValueError(f"Run record {path} evaluation missing {key!r}.")


def _ensure_loaded_run(
    record: LoadedRunRecord | dict[str, Any],
) -> LoadedRunRecord:
    if isinstance(record, LoadedRunRecord):
        return record
    _assert_run_record_shape(record, Path("<memory>"))
    return LoadedRunRecord(
        path=_string_value(record.get("run_id"), default="<memory>"),
        record=record,
    )


def _build_failure_summaries(
    failed_records: list[LoadedRunRecord],
) -> list[FailureSummary]:
    summaries: list[FailureSummary] = []
    for bucket in CANONICAL_FAILURE_BUCKETS:
        matching = [
            record
            for record in failed_records
            if any(alias in record.failure_tags for alias in bucket.aliases)
        ]
        summaries.append(
            FailureSummary(
                failure=bucket.key,
                label=bucket.label,
                count=len(matching),
                run_ids=sorted(record.run_id for record in matching),
                scenario_ids=sorted(
                    {record.scenario_id for record in matching}
                ),
                agent_versions=sorted(
                    {record.agent_version for record in matching}
                ),
                suggested_improvement_target=bucket.improvement_target,
            )
        )
    return summaries


def _build_improvement_row(record: LoadedRunRecord) -> ImprovementReportRow:
    return ImprovementReportRow(
        run_id=record.run_id,
        agent_version=record.agent_version,
        scenario_id=record.scenario_id,
        passed=record.passed,
        score=record.score,
        failure_tags=record.failure_tags,
        suggested_improvement_targets=_suggested_targets(record.failure_tags),
    )


def _suggested_targets(failure_tags: list[str]) -> list[str]:
    targets: list[str] = []
    for tag in failure_tags:
        target = _target_for_tag(tag)
        if target and target not in targets:
            targets.append(target)
    return targets


def _target_for_tag(tag: str) -> str:
    for bucket in CANONICAL_FAILURE_BUCKETS:
        if tag in bucket.aliases:
            return bucket.improvement_target
    return EXTRA_IMPROVEMENT_TARGETS.get(
        tag,
        f"Investigate evaluator failure tag `{tag}` and add a deterministic "
        "improvement target if it recurs.",
    )


def _agent_version_summary(
    records: list[LoadedRunRecord],
) -> dict[str, dict[str, Any]]:
    versions = sorted({record.agent_version for record in records})
    summary: dict[str, dict[str, Any]] = {}
    for version in versions:
        version_records = [
            record for record in records if record.agent_version == version
        ]
        passed_count = sum(1 for record in version_records if record.passed)
        summary[version] = {
            "run_count": len(version_records),
            "passed_count": passed_count,
            "failed_count": len(version_records) - passed_count,
            "pass_rate": _ratio(passed_count, len(version_records)),
            "average_score": round(
                sum(record.score for record in version_records)
                / len(version_records),
                4,
            ),
        }
    return summary


def _build_comparison(
    baseline: FailureAnalysisReport,
    candidate: FailureAnalysisReport,
    *,
    baseline_label: str,
    candidate_label: str,
) -> RunSetComparison:
    baseline_tags = _failure_count_by_tag(baseline)
    candidate_tags = _failure_count_by_tag(candidate)
    tags = sorted(set(baseline_tags) | set(candidate_tags))
    return RunSetComparison(
        baseline_label=baseline_label,
        candidate_label=candidate_label,
        baseline=_comparison_summary(baseline),
        candidate=_comparison_summary(candidate),
        deltas={
            "run_count": candidate.run_count - baseline.run_count,
            "passed_count": candidate.passed_count - baseline.passed_count,
            "failed_count": candidate.failed_count - baseline.failed_count,
            "pass_rate": round(candidate.pass_rate - baseline.pass_rate, 4),
            "average_score": round(
                candidate.average_score - baseline.average_score,
                4,
            ),
            "failure_counts": {
                tag: candidate_tags.get(tag, 0) - baseline_tags.get(tag, 0)
                for tag in tags
            },
        },
    )


def _comparison_summary(report: FailureAnalysisReport) -> dict[str, Any]:
    return {
        "run_count": report.run_count,
        "passed_count": report.passed_count,
        "failed_count": report.failed_count,
        "pass_rate": report.pass_rate,
        "average_score": report.average_score,
        "failure_counts": _failure_count_by_tag(report),
    }


def _failure_count_by_tag(report: FailureAnalysisReport) -> dict[str, int]:
    return {
        summary.failure: summary.count
        for summary in report.failure_summaries
        if summary.count
    }


def _filter_agent_version(
    records: list[LoadedRunRecord],
    agent_version: str | None,
) -> list[LoadedRunRecord]:
    if agent_version is None:
        return records
    filtered = [
        record for record in records if record.agent_version == agent_version
    ]
    if not filtered:
        raise ValueError(f"No records found for {agent_version!r}.")
    return filtered


def _evaluation(record: dict[str, Any]) -> dict[str, Any]:
    evaluation = record.get("evaluation", {})
    if not isinstance(evaluation, dict):
        raise ValueError(
            f"Run {record.get('run_id', '<unknown>')} has invalid evaluation."
        )
    return evaluation


def _failure_tags(record: dict[str, Any]) -> list[str]:
    evaluation = _evaluation(record)
    tags = evaluation.get("failure_tags", [])
    if tags is None:
        tags = []
    if not isinstance(tags, list) or not all(
        isinstance(tag, str) for tag in tags
    ):
        raise ValueError(
            f"Run {record.get('run_id', '<unknown>')} has invalid failure_tags."
        )
    if tags:
        return sorted(set(tags))

    checks = evaluation.get("checks", [])
    if not isinstance(checks, list):
        return []
    derived = [
        check.get("failure_tag")
        for check in checks
        if isinstance(check, dict)
        and not check.get("passed", True)
        and isinstance(check.get("failure_tag"), str)
    ]
    return sorted(set(derived))


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _string_value(value: Any, *, default: str) -> str:
    return value if isinstance(value, str) and value else default


if __name__ == "__main__":
    raise SystemExit(main())
