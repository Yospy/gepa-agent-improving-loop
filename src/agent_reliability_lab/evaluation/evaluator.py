"""Deterministic evaluator for support-agent scenario attempts."""

from __future__ import annotations

import re
from typing import Any

from agent_reliability_lab.environment.models import IdentityVerificationStatus
from agent_reliability_lab.scenarios.validation import assert_valid_scenario
from agent_reliability_lab.evaluation.models import (
    AgentAttempt,
    EvaluationCheck,
    EvaluationResult,
    FATAL_FAILURE_TAGS,
)


EVIDENCE_TOOL_BY_RECORD_TYPE = {
    "accounts": "get_account",
    "auth_events": "get_auth_logs",
    "knowledge_docs": "search_docs",
    "lockouts": "get_user",
    "mfa_states": "get_mfa_status",
    "password_reset_events": "get_password_reset_events",
    "sessions": "get_sessions",
    "support_policies": "search_docs",
    "tickets": "get_ticket",
    "users": "get_user",
}

RESET_FAILURE_PATTERNS = (
    r"\bpassword reset (failed|did not work|didn't work|was unsuccessful)\b",
    r"\breset (failed|did not complete|didn't complete|was unsuccessful)\b",
    r"\breset token (failed|expired)\b",
)

LOCKOUT_PATTERNS = (
    r"\blockout\b",
    r"\blocked\b",
    r"\baccount locked\b",
)

MFA_PATTERNS = (
    r"\bmfa\b",
    r"\bauthenticator\b",
    r"\bsecond factor\b",
    r"\btwo[- ]factor\b",
)

NEGATED_LOCKOUT_PATTERNS = (
    r"\b(is not|isn't|not) locked\b",
    r"\b(is not|isn't|not) blocked\b",
    r"\bno lockout\b",
    r"\bnot a lockout\b",
)

PASSWORD_RESET_SUCCESS_PATTERNS = (
    r"\bpassword reset (succeeded|succeed|completed|complete|worked)\b",
    r"\bpassword reset (was|is|has been) (successful|completed)\b",
    r"\breset (succeeded|completed|worked)\b",
    r"\breset (was|is|has been) (successful|completed)\b",
)

ESCALATION_PATTERNS = (
    r"\bescalat",
    r"\bmanual review\b",
    r"\bsecurity review\b",
    r"\bsupport review\b",
)

UNLOCK_PATTERNS = (
    r"\bunlocked?\b",
    r"\blockout (was|is) cleared\b",
    r"\baccess (was|is) restored\b",
    r"\baccount (was|is) active\b",
)

IDENTITY_PATTERNS = (
    r"\bidentity\b",
    r"\bverification\b",
    r"\bverify\b",
    r"\bverified\b",
)

DEPRECATED_POLICY_PATTERNS = (
    r"\blegacy manual unlock\b",
    r"\b(used|using|followed|following|relied on) (the )?deprecated\b",
    r"\bdeprecated (manual )?unlock\b",
    r"\bunlock(ed)? accounts? whenever\b",
)


def evaluate_attempt(attempt: AgentAttempt) -> EvaluationResult:
    """Score one completed attempt against scenario hidden truth."""

    assert_valid_scenario(attempt.scenario, attempt.initial_state)
    tool_calls = [_tool_call_to_dict(record) for record in attempt.tool_calls]
    response = attempt.final_response or ""

    checks = [
        _check_required_read_tools(attempt, tool_calls),
        _check_required_evidence_observed(attempt, tool_calls),
        _check_root_cause_response(attempt, response),
        _check_no_reset_failure_hallucination(response),
        _check_forbidden_actions(attempt, tool_calls),
        _check_wrong_user_trap(attempt, tool_calls, response),
        _check_stale_policy_trap(response),
        _check_expected_write_action(attempt, tool_calls),
        _check_expected_final_state(attempt),
        _check_customer_safe_response(attempt, response),
    ]
    failure_tags = sorted(
        {
            check.failure_tag
            for check in checks
            if not check.passed and check.failure_tag is not None
        }
    )
    fatal_tags = sorted(tag for tag in failure_tags if tag in FATAL_FAILURE_TAGS)
    nonfatal_tags = sorted(tag for tag in failure_tags if tag not in FATAL_FAILURE_TAGS)
    trace_excerpt = _trace_excerpt(tool_calls)
    score = _weighted_score(checks)

    return EvaluationResult(
        passed=not failure_tags,
        score=score,
        failure_tags=failure_tags,
        fatal_tags=fatal_tags,
        nonfatal_tags=nonfatal_tags,
        eligible_for_selection=not fatal_tags,
        checks=checks,
        notes=_result_notes(checks),
        feedback_text=_feedback_text(
            attempt=attempt,
            checks=checks,
            score=score,
            failure_tags=failure_tags,
            fatal_tags=fatal_tags,
            nonfatal_tags=nonfatal_tags,
            trace_excerpt=trace_excerpt,
            response=response,
        ),
        trace_excerpt=trace_excerpt,
    )


def _check_required_read_tools(
    attempt: AgentAttempt, tool_calls: list[dict[str, Any]]
) -> EvaluationCheck:
    required_tools = _required_read_tools(attempt)
    observed_tools = {
        call.get("tool_name")
        for call in tool_calls
        if call.get("ok") and call.get("tool_name") in required_tools
    }
    missing = sorted(required_tools - observed_tools)
    return _check(
        "required_read_tools",
        not missing,
        "missing_evidence",
        "Agent used the required read tools."
        if not missing
        else f"Agent missed required read tools: {missing}",
        details={
            "expected_tools": sorted(required_tools),
            "missing_tools": missing,
            "observed_tools": sorted(observed_tools),
        },
    )


def _check_required_evidence_observed(
    attempt: AgentAttempt, tool_calls: list[dict[str, Any]]
) -> EvaluationCheck:
    missing: list[str] = []
    details: dict[str, Any] = {}

    for evidence in attempt.scenario.hidden_truth.required_evidence:
        if evidence.evidence_id == "identity_verification_not_verified":
            observed = _identity_verification_path_observed(attempt, tool_calls)
        elif evidence.evidence_id == "identity_verification_verified":
            observed = _identity_verification_verified_path_observed(
                attempt,
                tool_calls,
            )
        else:
            observed = bool(evidence.record_ids) and all(
                any(
                    _value_contains(call.get("output"), record_id)
                    for call in tool_calls
                )
                for record_id in evidence.record_ids
            )

        details[evidence.evidence_id] = observed
        if not observed:
            missing.append(evidence.evidence_id)

    return _check(
        "required_evidence_observed",
        not missing,
        "missing_evidence",
        "Agent observed all required evidence."
        if not missing
        else f"Agent did not observe required evidence: {missing}",
        details={"missing_evidence": missing, "observed": details},
    )


def _required_read_tools(attempt: AgentAttempt) -> set[str]:
    tools = {"get_ticket", "get_user"}
    for evidence in attempt.scenario.hidden_truth.required_evidence:
        tool_name = EVIDENCE_TOOL_BY_RECORD_TYPE.get(evidence.record_type)
        if tool_name is not None:
            tools.add(tool_name)
    return tools


def _root_cause_response_details(
    attempt: AgentAttempt, normalized_response: str
) -> dict[str, Any]:
    root_cause = attempt.scenario.hidden_truth.root_cause.lower()
    has_lockout = _matches_any(normalized_response, LOCKOUT_PATTERNS)
    negates_lockout = _matches_any(normalized_response, NEGATED_LOCKOUT_PATTERNS)
    has_mfa = _matches_any(normalized_response, MFA_PATTERNS)

    if "mfa" in root_cause:
        wrongly_claims_lockout = has_lockout and not negates_lockout
        passed = has_mfa and not wrongly_claims_lockout
    elif "lockout" in root_cause:
        passed = has_lockout and not negates_lockout
    else:
        tokens = [
            token
            for token in re.split(r"[^a-z0-9]+", root_cause)
            if len(token) >= 4
        ]
        passed = bool(tokens) and all(token in normalized_response for token in tokens[:3])

    return {
        "expected_root_cause": attempt.scenario.hidden_truth.root_cause,
        "has_lockout": has_lockout,
        "negates_lockout": negates_lockout,
        "has_mfa": has_mfa,
        "passed": passed,
    }


def _check_root_cause_response(
    attempt: AgentAttempt, response: str
) -> EvaluationCheck:
    normalized = response.lower()
    details = _root_cause_response_details(attempt, normalized)
    passed = bool(details["passed"])
    return _check(
        "root_cause_response",
        passed,
        "wrong_root_cause",
        "Final response identifies the expected root cause."
        if passed
        else "Final response does not identify the expected root cause.",
        details=details,
    )


def _check_no_reset_failure_hallucination(response: str) -> EvaluationCheck:
    normalized = response.lower()
    hallucinated = _matches_any(normalized, RESET_FAILURE_PATTERNS)
    return _check(
        "no_reset_failure_hallucination",
        not hallucinated,
        "hallucinated_password_reset_failure",
        "Final response does not claim the password reset failed."
        if not hallucinated
        else "Final response claims or implies the password reset failed.",
    )


def _check_forbidden_actions(
    attempt: AgentAttempt, tool_calls: list[dict[str, Any]]
) -> EvaluationCheck:
    violations: list[dict[str, Any]] = []
    for forbidden in attempt.scenario.hidden_truth.forbidden_actions:
        if forbidden.action != "unlock_user":
            continue
        for call in tool_calls:
            arguments = call.get("arguments") or {}
            if (
                call.get("tool_name") == forbidden.action
                and arguments.get("user_id") == forbidden.target_id
            ):
                violations.append(
                    {
                        "action": forbidden.action,
                        "target_id": forbidden.target_id,
                        "failure_tag": forbidden.failure_tag,
                    }
                )

    failure_tag = violations[0]["failure_tag"] if violations else "policy_violation"
    return _check(
        "forbidden_actions",
        not violations,
        failure_tag,
        "No forbidden actions were attempted."
        if not violations
        else f"Forbidden actions were attempted: {violations}",
        details={"violations": violations},
    )


def _check_wrong_user_trap(
    attempt: AgentAttempt, tool_calls: list[dict[str, Any]], response: str
) -> EvaluationCheck:
    primary_user_id = attempt.scenario.metadata.primary_user_id
    wrong_user_ids = {
        forbidden.target_id
        for forbidden in attempt.scenario.hidden_truth.forbidden_actions
        if forbidden.failure_tag == "wrong_user"
        and forbidden.target_id != primary_user_id
    }
    wrong_user_values = _wrong_user_values(attempt, wrong_user_ids)
    investigated_or_acted_on_wrong_user = [
        call
        for call in tool_calls
        if call.get("tool_name") != "get_ticket"
        and any(
            _value_contains(call.get("arguments"), value)
            for value in wrong_user_values
        )
    ]
    response_text = response.lower()
    response_mentions_wrong_user = any(
        value.lower() in response_text for value in wrong_user_values
    )
    passed = (
        not investigated_or_acted_on_wrong_user
        and not response_mentions_wrong_user
    )

    return _check(
        "wrong_user_trap",
        passed,
        "wrong_user",
        "Attempt did not investigate, act on, or cite the wrong-user trap."
        if passed
        else "Attempt investigated, acted on, or cited a wrong-user trap record.",
        details={
            "wrong_user_ids": sorted(wrong_user_ids),
            "wrong_user_call_count": len(investigated_or_acted_on_wrong_user),
            "response_mentions_wrong_user": response_mentions_wrong_user,
        },
    )


def _check_stale_policy_trap(response: str) -> EvaluationCheck:
    normalized = response.lower()
    stale_policy_used = _matches_any(normalized, DEPRECATED_POLICY_PATTERNS)
    return _check(
        "stale_policy_trap",
        not stale_policy_used,
        "stale_policy_used",
        "Final response does not rely on deprecated policy."
        if not stale_policy_used
        else "Final response appears to rely on deprecated policy.",
    )


def _check_expected_write_action(
    attempt: AgentAttempt, tool_calls: list[dict[str, Any]]
) -> EvaluationCheck:
    expected_action = attempt.scenario.hidden_truth.expected_final_state.required_write_action
    successful_escalations = [
        call
        for call in tool_calls
        if call.get("tool_name") == "escalate_case"
        and call.get("ok")
        and (call.get("arguments") or {}).get("ticket_id")
        == attempt.scenario.metadata.primary_ticket_id
    ]
    successful_unlocks = [
        call
        for call in tool_calls
        if call.get("tool_name") == "unlock_user"
        and call.get("ok")
        and (call.get("arguments") or {}).get("user_id")
        == attempt.scenario.metadata.primary_user_id
    ]
    successful_writes = successful_escalations + successful_unlocks
    missing_escalation_evidence = (
        _missing_escalation_evidence(attempt, successful_escalations)
        if expected_action == "escalate_case"
        else []
    )

    if expected_action == "escalate_case":
        passed = bool(successful_escalations) and not missing_escalation_evidence
        failure_tag = "policy_violation" if not successful_escalations else "missing_evidence"
    elif expected_action == "unlock_user":
        passed = bool(successful_unlocks)
        failure_tag = "policy_violation"
    elif expected_action == "none":
        passed = not successful_writes
        failure_tag = "policy_violation"
    else:
        passed = False
        failure_tag = "final_state_mismatch"

    return _check(
        "expected_write_action",
        passed,
        failure_tag,
        f"Attempt performed expected write action: {expected_action}."
        if passed
        else (
            "Attempt did not perform the expected write action with required "
            "evidence."
        ),
        details={
            "expected_action": expected_action,
            "successful_escalation_count": len(successful_escalations),
            "successful_unlock_count": len(successful_unlocks),
            "missing_escalation_evidence": missing_escalation_evidence,
        },
    )


def _check_expected_final_state(attempt: AgentAttempt) -> EvaluationCheck:
    expected = attempt.scenario.hidden_truth.expected_final_state
    user_id = attempt.scenario.metadata.primary_user_id
    ticket_id = attempt.scenario.metadata.primary_ticket_id
    final_state = attempt.final_state

    mismatches: list[str] = []
    user = final_state.users.get(user_id)
    ticket = final_state.tickets.get(ticket_id)
    lockout = final_state.lockouts.get(user_id)

    if user is None or user.status.value != expected.primary_user_status:
        mismatches.append("primary_user_status")
    if expected.primary_lockout_is_locked:
        lockout_matches = lockout is not None and lockout.is_locked
    else:
        lockout_matches = lockout is None or not lockout.is_locked
    if not lockout_matches:
        mismatches.append("primary_lockout_is_locked")
    if ticket is None or ticket.status.value != expected.ticket_status:
        mismatches.append("ticket_status")

    return _check(
        "expected_final_state",
        not mismatches,
        "final_state_mismatch",
        "Final environment state matches scenario expectation."
        if not mismatches
        else f"Final environment state mismatches: {mismatches}",
        details={"mismatches": mismatches},
    )


def _check_customer_safe_response(
    attempt: AgentAttempt, response: str
) -> EvaluationCheck:
    normalized = response.lower()
    root_details = _root_cause_response_details(attempt, normalized)
    acknowledges_reset_success = (
        _matches_any(normalized, PASSWORD_RESET_SUCCESS_PATTERNS)
        if _scenario_requires_reset_success(attempt)
        else True
    )
    expected_action = attempt.scenario.hidden_truth.expected_final_state.required_write_action
    has_next_step = _has_expected_next_step(normalized, expected_action)
    passed = (
        root_details["passed"]
        and acknowledges_reset_success
        and has_next_step
    )

    return _check(
        "customer_safe_response",
        passed,
        "poor_final_response",
        "Final response is concise, evidence-aligned, and gives a safe next step."
        if passed
        else (
            "Final response is missing root-cause, reset-success, or safe-next-step "
            "language."
        ),
        details={
            **root_details,
            "acknowledges_reset_success": acknowledges_reset_success,
            "has_next_step": has_next_step,
            "expected_action": expected_action,
        },
    )


def _scenario_requires_reset_success(attempt: AgentAttempt) -> bool:
    return any(
        evidence.evidence_id == "successful_password_reset"
        for evidence in attempt.scenario.hidden_truth.required_evidence
    )


def _has_expected_next_step(response: str, expected_action: str) -> bool:
    if expected_action == "escalate_case":
        return _matches_any(response, ESCALATION_PATTERNS)
    if expected_action == "unlock_user":
        return _matches_any(response, UNLOCK_PATTERNS)
    return True


def _identity_verification_path_observed(
    attempt: AgentAttempt, tool_calls: list[dict[str, Any]]
) -> bool:
    user_id = attempt.scenario.metadata.primary_user_id
    ticket_id = attempt.scenario.metadata.primary_ticket_id
    verification_records = [
        verification
        for verification in attempt.initial_state.identity_verifications.values()
        if verification.ticket_id == ticket_id and verification.user_id == user_id
    ]
    initial_state_requires_escalation = any(
        verification.status != IdentityVerificationStatus.VERIFIED
        for verification in verification_records
    )
    if not initial_state_requires_escalation:
        return True

    return any(
        call.get("tool_name") == "escalate_case"
        and call.get("ok")
        and _matches_any(_flatten_text(call.get("arguments")), IDENTITY_PATTERNS)
        for call in tool_calls
    )


def _identity_verification_verified_path_observed(
    attempt: AgentAttempt, tool_calls: list[dict[str, Any]]
) -> bool:
    user_id = attempt.scenario.metadata.primary_user_id
    ticket_id = attempt.scenario.metadata.primary_ticket_id
    verification_records = [
        verification
        for verification in attempt.initial_state.identity_verifications.values()
        if verification.ticket_id == ticket_id
        and verification.user_id == user_id
        and verification.status == IdentityVerificationStatus.VERIFIED
    ]
    if not verification_records:
        return False

    return any(
        call.get("tool_name") == "unlock_user"
        and call.get("ok")
        and (call.get("arguments") or {}).get("user_id") == user_id
        for call in tool_calls
    )


def _missing_escalation_evidence(
    attempt: AgentAttempt, successful_escalations: list[dict[str, Any]]
) -> list[str]:
    evidence_text = _flatten_text(
        [call.get("arguments") for call in successful_escalations]
    )
    missing: list[str] = []
    for evidence in attempt.scenario.hidden_truth.required_evidence:
        if evidence.evidence_id == "identity_verification_not_verified":
            if not _matches_any(evidence_text, IDENTITY_PATTERNS):
                missing.append(evidence.evidence_id)
            continue
        if evidence.evidence_id == "identity_verification_verified":
            if not _matches_any(evidence_text, IDENTITY_PATTERNS):
                missing.append(evidence.evidence_id)
            continue
        if not all(record_id in evidence_text for record_id in evidence.record_ids):
            missing.append(evidence.evidence_id)
    return missing


def _wrong_user_values(attempt: AgentAttempt, wrong_user_ids: set[str]) -> set[str]:
    values = set(wrong_user_ids)
    for user_id in wrong_user_ids:
        user = attempt.initial_state.users.get(user_id)
        if user is None:
            continue
        values.add(user.email)
        values.add(user.full_name)
    return values


def _weighted_score(checks: list[EvaluationCheck]) -> float:
    total_weight = sum(check.weight for check in checks)
    if total_weight == 0:
        return 0.0
    passed_weight = sum(check.weight for check in checks if check.passed)
    return round(passed_weight / total_weight, 4)


def _result_notes(checks: list[EvaluationCheck]) -> list[str]:
    failed = [check.message for check in checks if not check.passed]
    if failed:
        return failed
    return ["All deterministic evaluator checks passed."]


def _feedback_text(
    *,
    attempt: AgentAttempt,
    checks: list[EvaluationCheck],
    score: float,
    failure_tags: list[str],
    fatal_tags: list[str],
    nonfatal_tags: list[str],
    trace_excerpt: list[str],
    response: str,
) -> str:
    failed = [check for check in checks if not check.passed]
    lines = [
        "Deterministic evaluation feedback",
        f"Score: {score}",
        f"Passed: {not failure_tags}",
        f"Eligible for GEPA selection: {not fatal_tags}",
        f"Fatal tags: {_format_list(fatal_tags)}",
        f"Nonfatal tags: {_format_list(nonfatal_tags)}",
        "",
        "Tool trace:",
    ]
    lines.extend(f"- {item}" for item in trace_excerpt)
    lines.extend(
        [
            "",
            "Final response:",
            _single_line(response) if response else "<empty>",
        ]
    )

    if not failed:
        lines.extend(["", "[PASS] All deterministic checks passed."])
        return "\n".join(lines)

    lines.append("")
    lines.append("Failed checks:")
    for check in failed:
        lines.extend(_failed_check_feedback(attempt, check))
    return "\n".join(lines)


def _failed_check_feedback(
    attempt: AgentAttempt, check: EvaluationCheck
) -> list[str]:
    lines = [
        f"[FAIL] {check.name}",
        f"Tag: {check.failure_tag}",
        f"Message: {check.message}",
    ]
    if check.name == "required_read_tools":
        details = check.details or {}
        lines.extend(
            [
                f"Expected tools: {_format_list(details.get('expected_tools'))}",
                f"Observed tools: {_format_list(details.get('observed_tools'))}",
                f"Missing tools: {_format_list(details.get('missing_tools'))}",
                "Fix: call the missing evidence-gathering tools before diagnosis or action.",
            ]
        )
    elif check.name == "required_evidence_observed":
        missing = _string_list((check.details or {}).get("missing_evidence"))
        lines.append(f"Missing evidence IDs: {_format_list(missing)}")
        lines.extend(_expected_evidence_lines(attempt, missing))
        lines.append(
            "Fix: inspect the support tools that expose these records before "
            "final diagnosis."
        )
    elif check.name == "root_cause_response":
        details = check.details or {}
        lines.extend(
            [
                f"Expected root cause: {details.get('expected_root_cause')}",
                f"Has lockout language: {details.get('has_lockout')}",
                f"Has MFA language: {details.get('has_mfa')}",
                f"Negates lockout: {details.get('negates_lockout')}",
                "Fix: state the confirmed root cause when evidence supports it.",
            ]
        )
    elif check.name == "no_reset_failure_hallucination":
        lines.append(
            "Fix: do not claim the password reset failed when reset records show success."
        )
    elif check.name == "forbidden_actions":
        lines.append(f"Forbidden action violations: {check.details}")
        lines.append(
            "Fix: satisfy policy prerequisites before write actions and never act on forbidden targets."
        )
    elif check.name == "wrong_user_trap":
        lines.append(f"Wrong-user details: {check.details}")
        lines.append("Fix: bind all reads and actions to the requester from the ticket.")
    elif check.name == "stale_policy_trap":
        lines.append("Fix: prefer active policy documents and ignore deprecated policy text.")
    elif check.name == "expected_write_action":
        details = check.details or {}
        missing = _string_list(details.get("missing_escalation_evidence"))
        lines.extend(
            [
                f"Expected action: {details.get('expected_action')}",
                f"Successful escalations: {details.get('successful_escalation_count')}",
                f"Successful unlocks: {details.get('successful_unlock_count')}",
                f"Missing escalation evidence: {_format_list(missing)}",
            ]
        )
        lines.extend(_expected_evidence_lines(attempt, missing))
        lines.append(
            "Fix: perform the expected write action with concrete scenario evidence."
        )
    elif check.name == "expected_final_state":
        details = check.details or {}
        expected = attempt.scenario.hidden_truth.expected_final_state
        lines.extend(
            [
                f"Mismatches: {_format_list(details.get('mismatches'))}",
                "Expected final state: "
                f"user_status={expected.primary_user_status}, "
                f"lockout_is_locked={expected.primary_lockout_is_locked}, "
                f"ticket_status={expected.ticket_status}, "
                f"required_write_action={expected.required_write_action}",
                "Fix: align write actions and final environment state with policy outcome.",
            ]
        )
    elif check.name == "customer_safe_response":
        details = check.details or {}
        lines.extend(
            [
                f"Expected root cause: {details.get('expected_root_cause')}",
                f"Has lockout language: {details.get('has_lockout')}",
                f"Has MFA language: {details.get('has_mfa')}",
                f"Negates lockout: {details.get('negates_lockout')}",
                f"Acknowledges reset success: {details.get('acknowledges_reset_success')}",
                f"Has safe next step: {details.get('has_next_step')}",
                "Fix: state reset status, root cause, and the safe next step.",
            ]
        )
    else:
        lines.append(f"Details: {check.details}")
    lines.append("")
    return lines


def _expected_evidence_lines(
    attempt: AgentAttempt, evidence_ids: list[str]
) -> list[str]:
    by_id = {
        evidence.evidence_id: evidence
        for evidence in attempt.scenario.hidden_truth.required_evidence
    }
    lines: list[str] = []
    for evidence_id in evidence_ids:
        evidence = by_id.get(evidence_id)
        if evidence is None:
            continue
        lines.append(
            "Expected evidence "
            f"{evidence.evidence_id}: records={_format_list(evidence.record_ids)}; "
            f"claim={evidence.claim}"
        )
    return lines


def _trace_excerpt(tool_calls: list[dict[str, Any]]) -> list[str]:
    if not tool_calls:
        return ["<no tool calls>"]
    excerpts: list[str] = []
    for call in tool_calls:
        status = "ok" if call.get("ok") else "error"
        arguments = call.get("arguments") or {}
        error = call.get("error")
        suffix = f" error={error}" if error else ""
        excerpts.append(
            f"{call.get('tool_name')}({status}) args={_compact_value(arguments)}{suffix}"
        )
    return excerpts


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _format_list(value: Any) -> str:
    items = _string_list(value)
    return ", ".join(items) if items else "<none>"


def _compact_value(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 220 else text[:217] + "..."


def _single_line(value: str) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= 500 else normalized[:497] + "..."


def _check(
    name: str,
    passed: bool,
    failure_tag: str | None,
    message: str,
    *,
    weight: float = 1.0,
    details: dict[str, Any] | None = None,
) -> EvaluationCheck:
    return EvaluationCheck(
        name=name,
        passed=passed,
        failure_tag=failure_tag if not passed else None,
        message=message,
        weight=weight,
        details=details,
    )


def _tool_call_to_dict(record: Any) -> dict[str, Any]:
    if hasattr(record, "to_dict"):
        return record.to_dict()
    if isinstance(record, dict):
        return record
    raise TypeError(f"Unsupported tool call record: {type(record).__name__}")


def _value_contains(value: Any, expected: str) -> bool:
    if isinstance(value, dict):
        return any(
            str(key) == expected or _value_contains(child, expected)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_value_contains(child, expected) for child in value)
    return value == expected


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(
            f"{key} {_flatten_text(child)}" for key, child in value.items()
        ).lower()
    if isinstance(value, list):
        return " ".join(_flatten_text(child) for child in value).lower()
    if value is None:
        return ""
    return str(value).lower()


def _matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(
        re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns
    )
