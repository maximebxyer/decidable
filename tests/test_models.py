"""Verdict semantics: the ERROR/FAIL distinction, required evidence, roll-up."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from decidable.models import (
    Evidence,
    HarnessError,
    Report,
    RunMetadata,
    Stage,
    Status,
    Task,
    TaskResult,
    Verdict,
    VerifierRef,
    roll_up,
)

PARSE = VerifierRef(name="ast_parse", stage=Stage.SYNTACTIC)
TYPES = VerifierRef(name="mypy", stage=Stage.STATIC)

BROKEN = HarnessError(
    exception_type="FileNotFoundError",
    message="mypy: command not found",
    traceback="Traceback (most recent call last):\n  ...\n",
)


def verdict(status: Status, *, error: HarnessError | None = None) -> Verdict:
    return Verdict(
        status=status,
        verifier=PARSE,
        evidence=Evidence(summary=f"{status.value} for testing"),
        error=error,
    )


def test_the_three_statuses_are_distinct() -> None:
    assert {s.value for s in Status} == {"pass", "fail", "error"}


@pytest.mark.parametrize(
    ("status", "expected"),
    [(Status.PASS, True), (Status.FAIL, False), (Status.ERROR, False)],
)
def test_only_pass_is_truthy(status: Status, expected: bool) -> None:
    error = BROKEN if status is Status.ERROR else None
    assert verdict(status, error=error).is_pass is expected


def test_stage_rank_increases_cheap_to_expensive() -> None:
    ranks = [stage.rank for stage in Stage]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)
    assert Stage.SYNTACTIC.rank < Stage.STATIC.rank < Stage.DYNAMIC.rank
    assert Stage.DYNAMIC.rank < Stage.BEHAVIOURAL.rank


def test_evidence_summary_is_required_and_non_empty() -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate({})
    with pytest.raises(ValidationError):
        Evidence(summary="")
    with pytest.raises(ValidationError):
        Evidence(summary="   ")


def test_verdict_cannot_be_constructed_without_evidence() -> None:
    with pytest.raises(ValidationError):
        Verdict.model_validate({"status": Status.FAIL, "verifier": PARSE})


def test_evidence_data_accepts_scalars_and_flat_tuples() -> None:
    evidence = Evidence(
        summary="2 type errors",
        data={"count": 2, "codes": ("arg-type", "return-value"), "clean": False},
    )
    assert evidence.data["codes"] == ("arg-type", "return-value")
    assert evidence.data["clean"] is False


def test_evidence_data_rejects_nested_structures() -> None:
    """Structured evidence exists to be aggregated, and nested blobs do not aggregate."""
    with pytest.raises(ValidationError):
        Evidence.model_validate({"summary": "nested", "data": {"errors": {"line": 3}}})


def test_error_verdict_must_carry_a_harness_error() -> None:
    with pytest.raises(ValidationError):
        verdict(Status.ERROR)


@pytest.mark.parametrize("status", [Status.PASS, Status.FAIL])
def test_non_error_verdict_must_not_carry_a_harness_error(status: Status) -> None:
    """A FAIL is about the agent; harness breakage on one is a category error."""
    with pytest.raises(ValidationError):
        verdict(status, error=BROKEN)


def test_verdicts_are_frozen() -> None:
    result = verdict(Status.PASS)
    with pytest.raises(ValidationError):
        result.status = Status.FAIL


def test_roll_up_lets_error_dominate_fail() -> None:
    assert roll_up([verdict(Status.PASS), verdict(Status.PASS)]) is Status.PASS
    assert roll_up([verdict(Status.PASS), verdict(Status.FAIL)]) is Status.FAIL
    assert roll_up([verdict(Status.ERROR, error=BROKEN)]) is Status.ERROR
    mixed = [verdict(Status.FAIL), verdict(Status.ERROR, error=BROKEN)]
    assert roll_up(mixed) is Status.ERROR


def test_roll_up_of_nothing_is_error_not_pass() -> None:
    """Nothing was decided. That is a harness condition, never a passing agent."""
    assert roll_up([]) is Status.ERROR


def task_result(*verdicts: Verdict) -> TaskResult:
    return TaskResult(
        task_id="fizzbuzz",
        artifact_digest="0" * 64,
        verdicts=verdicts,
    )


def test_task_result_status_rolls_up() -> None:
    assert task_result(verdict(Status.PASS)).status is Status.PASS
    assert task_result(verdict(Status.PASS), verdict(Status.FAIL)).status is Status.FAIL
    errored = task_result(verdict(Status.PASS), verdict(Status.ERROR, error=BROKEN))
    assert errored.status is Status.ERROR


def test_task_result_records_what_was_never_reached() -> None:
    result = TaskResult(
        task_id="fizzbuzz",
        artifact_digest="0" * 64,
        verdicts=(verdict(Status.FAIL),),
        skipped=(TYPES,),
    )
    assert result.skipped == (TYPES,)
    assert [v.verifier for v in result.verdicts] == [PARSE]


def test_report_round_trips_through_json() -> None:
    """A report that cannot be re-read cannot be re-derived."""
    report = Report(
        metadata=RunMetadata(
            decidable_version="0.1.0",
            python_version="3.12.0",
            platform="win32",
            agent_name="echo",
            started_at=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
            finished_at=datetime(2026, 9, 2, 12, 0, 1, tzinfo=UTC),
        ),
        results=(
            task_result(verdict(Status.PASS)),
            TaskResult(
                task_id="broken",
                artifact_digest="1" * 64,
                verdicts=(
                    Verdict(
                        status=Status.ERROR,
                        verifier=TYPES,
                        evidence=Evidence(
                            summary="mypy raised FileNotFoundError",
                            detail="could not execute mypy",
                            data={"codes": ("arg-type",), "count": 1},
                        ),
                        error=BROKEN,
                        duration_s=0.25,
                    ),
                ),
                skipped=(PARSE,),
            ),
        ),
    )

    assert Report.model_validate_json(report.model_dump_json()) == report


def test_task_is_pure_data() -> None:
    task = Task(id="fizzbuzz", prompt="write fizzbuzz")
    assert Task.model_validate_json(task.model_dump_json()) == task
    assert "verifiers" not in Task.model_fields
