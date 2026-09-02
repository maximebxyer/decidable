"""The failure taxonomy: where agents break, and what was never attempted."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime

from rich.console import Console

from decidable.models import (
    Evidence,
    HarnessError,
    Report,
    RunMetadata,
    Stage,
    Status,
    TaskResult,
    Verdict,
    VerifierRef,
)
from decidable.report import breakdown, render_json, render_terminal, summarise

PARSE = VerifierRef(name="parse", stage=Stage.SYNTACTIC, fingerprint="parse/1")
TYPES = VerifierRef(name="mypy", stage=Stage.STATIC, fingerprint="mypy/1")
RUNS = VerifierRef(name="execute", stage=Stage.DYNAMIC, fingerprint="execute/1")
BEHAVES = VerifierRef(name="pytest", stage=Stage.BEHAVIOURAL, fingerprint="pytest/1")

STACK = (PARSE, TYPES, RUNS, BEHAVES)

BROKEN = HarnessError(
    exception_type="RuntimeError", message="the model API fell over", traceback="..."
)


def verdict(ref: VerifierRef, status: Status) -> Verdict:
    return Verdict(
        status=status,
        verifier=ref,
        evidence=Evidence(summary=f"{ref.name} says {status.value}"),
        error=BROKEN if status is Status.ERROR else None,
    )


def result(task_id: str, *statuses: Status) -> TaskResult:
    """A task that reached as many stages as it has statuses, skipping the rest."""
    return TaskResult(
        task_id=task_id,
        artifact_digest="0" * 64,
        verdicts=tuple(
            verdict(ref, status) for ref, status in zip(STACK, statuses, strict=False)
        ),
        skipped=STACK[len(statuses) :],
    )


def report_of(*results: TaskResult) -> Report:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    return Report(
        metadata=RunMetadata(
            decidable_version="0.1.0",
            python_version="3.12.7",
            platform="win32",
            suite_name="fizzbuzz",
            agent_name="echo",
            started_at=now,
            finished_at=now,
        ),
        results=results,
    )


P = Status.PASS
F = Status.FAIL
E = Status.ERROR


def test_the_breakdown_says_where_each_agent_broke() -> None:
    report = report_of(
        result("all-good", P, P, P, P),
        result("no-parse", F),
        result("no-types", P, F),
        result("wrong", P, P, P, F),
    )

    by_stage = {b.stage: b for b in breakdown(report)}

    assert by_stage[Stage.SYNTACTIC].passed == 3
    assert by_stage[Stage.SYNTACTIC].failed == 1
    assert by_stage[Stage.SYNTACTIC].not_reached == 0

    assert by_stage[Stage.STATIC].passed == 2
    assert by_stage[Stage.STATIC].failed == 1
    assert by_stage[Stage.STATIC].not_reached == 1

    assert by_stage[Stage.BEHAVIOURAL].passed == 1
    assert by_stage[Stage.BEHAVIOURAL].failed == 1
    assert by_stage[Stage.BEHAVIOURAL].not_reached == 2


def test_a_stage_with_two_verifiers_still_counts_each_task_once() -> None:
    """Otherwise a stage reports more passes than there are tasks."""
    ruff = VerifierRef(name="ruff", stage=Stage.STATIC, fingerprint="ruff/1")
    both_static = TaskResult(
        task_id="a",
        artifact_digest="0" * 64,
        verdicts=(verdict(PARSE, P), verdict(TYPES, P), verdict(ruff, P)),
    )

    by_stage = {b.stage: b for b in breakdown(report_of(both_static))}

    assert by_stage[Stage.STATIC].passed == 1
    assert by_stage[Stage.STATIC].attempted == 1


def test_a_task_counts_once_per_stage_by_its_worst_verdict() -> None:
    ruff = VerifierRef(name="ruff", stage=Stage.STATIC, fingerprint="ruff/1")
    mixed = TaskResult(
        task_id="a",
        artifact_digest="0" * 64,
        verdicts=(verdict(PARSE, P), verdict(TYPES, P), verdict(ruff, F)),
    )

    by_stage = {b.stage: b for b in breakdown(report_of(mixed))}

    assert by_stage[Stage.STATIC].failed == 1
    assert by_stage[Stage.STATIC].passed == 0


def test_not_reached_is_not_a_failure() -> None:
    """The whole point of `skipped`: it distinguishes failed from never attempted."""
    report = report_of(result("no-parse", F))

    by_stage = {b.stage: b for b in breakdown(report)}

    assert by_stage[Stage.STATIC].failed == 0
    assert by_stage[Stage.STATIC].errored == 0
    assert by_stage[Stage.STATIC].not_reached == 1
    assert by_stage[Stage.STATIC].attempted == 0


def test_an_error_is_counted_apart_from_a_failure() -> None:
    report = report_of(result("tool-broke", P, E))

    by_stage = {b.stage: b for b in breakdown(report)}

    assert by_stage[Stage.STATIC].errored == 1
    assert by_stage[Stage.STATIC].failed == 0


def test_the_breakdown_only_lists_stages_the_run_actually_had() -> None:
    report = report_of(
        TaskResult(
            task_id="a",
            artifact_digest="0" * 64,
            verdicts=(verdict(PARSE, P),),
        )
    )

    assert [b.stage for b in breakdown(report)] == [Stage.SYNTACTIC]


def test_an_agent_failure_belongs_to_no_stage() -> None:
    """The agent produced nothing, so no stage had a chance to decide anything."""
    report = report_of(
        result("fine", P, P, P, P),
        TaskResult(task_id="never-answered", error=BROKEN),
    )

    assert breakdown(report) == breakdown(report_of(result("fine", P, P, P, P)))

    summary = summarise(report)
    assert summary.agent_errors == 1
    assert summary.errored == 1
    assert summary.failed == 0
    assert summary.passed == 1


def test_the_summary_counts_tasks_not_verdicts() -> None:
    report = report_of(
        result("a", P, P, P, P),
        result("b", P, F),
        result("c", P, E),
    )

    summary = summarise(report)
    assert summary.tasks == 3
    assert (summary.passed, summary.failed, summary.errored) == (1, 1, 1)
    assert summary.pass_rate == 1 / 3


def test_an_empty_report_has_a_zero_pass_rate_and_does_not_divide_by_zero() -> None:
    assert summarise(report_of()).pass_rate == 0.0


def test_json_carries_the_derived_breakdown() -> None:
    report = report_of(result("a", P, F))

    payload = json.loads(render_json(report))

    assert payload["metadata"]["suite_name"] == "fizzbuzz"
    assert payload["summary"]["failed"] == 1
    # The skipped stages are present and marked never attempted, not omitted.
    assert [b["stage"] for b in payload["breakdown"]] == [
        "syntactic",
        "static",
        "dynamic",
        "behavioural",
    ]
    assert payload["breakdown"][1]["failed"] == 1
    assert payload["breakdown"][2]["not_reached"] == 1
    assert payload["results"][0]["task_id"] == "a"


def test_json_records_which_verifier_configuration_decided() -> None:
    payload = json.loads(render_json(report_of(result("a", P))))

    assert payload["results"][0]["verdicts"][0]["verifier"]["fingerprint"] == "parse/1"


def render(report: Report) -> str:
    """Render to a buffer wide enough that nothing we assert on gets wrapped away."""
    console = Console(file=io.StringIO(), width=200, record=True)
    render_terminal(report, console=console)
    return console.export_text()


def test_the_terminal_report_shows_every_stage_and_every_failure() -> None:
    report = report_of(
        result("all-good", P, P, P, P),
        result("no-types", P, F),
        TaskResult(task_id="never-answered", error=BROKEN),
    )

    printed = render(report)

    assert "fizzbuzz" in printed
    assert "echo" in printed
    for stage in Stage:
        assert stage.value in printed

    assert "no-types" in printed
    assert "mypy says fail" in printed
    assert "never-answered" in printed
    assert "the model API fell over" in printed
    assert "all-good" not in printed


def test_the_terminal_report_handles_a_run_with_nothing_in_it() -> None:
    assert "0 tasks" in render(report_of())
