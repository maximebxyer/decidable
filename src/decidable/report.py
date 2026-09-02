"""Turning verdicts into a failure taxonomy.

A pass rate is uninformative. The breakdown below says *where* an agent breaks,
which is the only number that tells you what to fix. Two columns carry most of
that meaning: ``not_reached``, which distinguishes "type-checking failed" from
"type-checking was never attempted", and the separate count of agent errors,
which keeps harness breakage out of the agent's score entirely.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict
from rich.console import Console
from rich.table import Table

from decidable.models import Report, Stage, Status, TaskResult, roll_up

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class StageBreakdown(BaseModel):
    """What happened at one stage, across every task in a run."""

    model_config = _FROZEN

    stage: Stage
    passed: int = 0
    failed: int = 0
    errored: int = 0
    not_reached: int = 0
    """Short-circuited: an earlier stage did not pass, so this was never tried."""

    @property
    def attempted(self) -> int:
        return self.passed + self.failed + self.errored


class RunSummary(BaseModel):
    """A run's headline numbers, with harness breakage kept separate."""

    model_config = _FROZEN

    tasks: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    agent_errors: int = 0
    """Tasks where the agent produced nothing. Never counted as failures."""

    @property
    def pass_rate(self) -> float:
        return self.passed / self.tasks if self.tasks else 0.0


def summarise(report: Report) -> RunSummary:
    statuses = [result.status for result in report.results]
    return RunSummary(
        tasks=len(report.results),
        passed=sum(s is Status.PASS for s in statuses),
        failed=sum(s is Status.FAIL for s in statuses),
        errored=sum(s is Status.ERROR for s in statuses),
        agent_errors=sum(result.error is not None for result in report.results),
    )


def breakdown(report: Report) -> tuple[StageBreakdown, ...]:
    """Per-stage counts, in stage order, for every stage any task reached.

    Counts **tasks, not verdicts**. A stage with two verifiers in it — `mypy`
    and `ruff` both being static — would otherwise report more passes than there
    are tasks, and the stages would stop being comparable with each other. A
    task counts once per stage, by the roll-up of its verdicts there, so `ERROR`
    dominates `FAIL` dominates `PASS` exactly as everywhere else.

    A task whose agent failed contributes to no stage: there was no artifact, so
    no stage ever had a chance to decide anything about it.
    """
    counts: dict[Stage, dict[str, int]] = {
        stage: {"passed": 0, "failed": 0, "errored": 0, "not_reached": 0}
        for stage in Stage
    }
    seen: set[Stage] = set()

    for result in report.results:
        skipped_stages = {ref.stage for ref in result.skipped}
        for stage in Stage:
            at_stage = [v for v in result.verdicts if v.verifier.stage is stage]
            if at_stage:
                seen.add(stage)
                counts[stage][_COLUMN[roll_up(at_stage)]] += 1
            elif stage in skipped_stages:
                seen.add(stage)
                counts[stage]["not_reached"] += 1

    return tuple(
        StageBreakdown(stage=stage, **counts[stage]) for stage in Stage if stage in seen
    )


_COLUMN = {
    Status.PASS: "passed",
    Status.FAIL: "failed",
    Status.ERROR: "errored",
}


def render_json(report: Report) -> str:
    """The report plus its derived breakdown, so a consumer need not recompute it."""
    return json.dumps(
        {
            "metadata": report.metadata.model_dump(mode="json"),
            "summary": summarise(report).model_dump(mode="json"),
            "breakdown": [b.model_dump(mode="json") for b in breakdown(report)],
            "results": [r.model_dump(mode="json") for r in report.results],
        },
        indent=2,
    )


def render_terminal(report: Report, *, console: Console | None = None) -> None:
    """Print the summary, the per-stage breakdown, and every task that did not pass."""
    out = console or Console()
    summary = summarise(report)

    out.print(
        f"{report.metadata.suite_name}: {summary.tasks} tasks against "
        f"{report.metadata.agent_name}"
    )
    out.print(
        f"passed {summary.passed}  failed {summary.failed}  "
        f"errored {summary.errored}  ({summary.pass_rate:.0%} pass rate)"
    )
    if summary.agent_errors:
        out.print(
            f"{summary.agent_errors} of those errors are the agent producing nothing"
        )

    out.print(_stage_table(report))

    failures = [r for r in report.results if r.status is not Status.PASS]
    if failures:
        out.print(_failure_table(failures))


def _stage_table(report: Report) -> Table:
    table = Table(title="by stage")
    table.add_column("stage")
    table.add_column("passed", justify="right")
    table.add_column("failed", justify="right")
    table.add_column("errored", justify="right")
    table.add_column("not reached", justify="right")
    for row in breakdown(report):
        table.add_row(
            row.stage.value,
            str(row.passed),
            str(row.failed),
            str(row.errored),
            str(row.not_reached),
        )
    return table


def _failure_table(failures: list[TaskResult]) -> Table:
    table = Table(title="what did not pass")
    table.add_column("task")
    table.add_column("status")
    table.add_column("stage")
    table.add_column("why")
    for result in failures:
        table.add_row(result.task_id, result.status.value, *_reason(result))
    return table


def _reason(result: TaskResult) -> tuple[str, str]:
    """Where it broke and what the evidence said."""
    if result.error is not None:
        return "agent", f"{result.error.exception_type}: {result.error.message}"
    if not result.verdicts:
        return "-", "no verdicts"
    terminal = result.verdicts[-1]
    return terminal.verifier.stage.value, terminal.evidence.summary
