"""The committed example, run end to end.

The README claims one command reproduces a taxonomy. This asserts that taxonomy,
so the claim is verified by execution like everything else, and so the example
cannot rot silently when a verifier changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from decidable.cli import exit_code
from decidable.models import Report, Stage, Status
from decidable.report import breakdown, summarise
from decidable.runner import run
from decidable.suite_file import load

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "python_codegen"

#: Each task fails at exactly the stage its answer was written to fail at.
EXPECTED = {
    "fizzbuzz": (Status.PASS, None),
    "roman": (Status.FAIL, Stage.SYNTACTIC),
    "anagram": (Status.FAIL, Stage.STATIC),
    "primes": (Status.FAIL, Stage.STATIC),
    "balanced": (Status.FAIL, Stage.DYNAMIC),
    "rle": (Status.FAIL, Stage.BEHAVIOURAL),
}


@pytest.fixture(scope="module")
def report() -> Report:
    import importlib.util

    spec = importlib.util.spec_from_file_location("example_agent", EXAMPLE / "agent.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    loaded = load(EXAMPLE / "suite.yaml")
    return run(
        loaded.suite,
        module.agent,
        stack_for=loaded.stack_for,
        agent_name="example",
    )


def test_every_task_breaks_where_it_was_written_to_break(report: Report) -> None:
    for result in report.results:
        expected_status, expected_stage = EXPECTED[result.task_id]
        assert result.status is expected_status, result.task_id

        terminal = result.verdicts[-1]
        actual_stage = terminal.verifier.stage if result.status is Status.FAIL else None
        assert actual_stage is expected_stage, (
            f"{result.task_id} failed at {actual_stage}, expected {expected_stage}: "
            f"{terminal.evidence.summary}"
        )


def test_the_example_produces_a_taxonomy_worth_showing(report: Report) -> None:
    """A worked example where everything passes demonstrates nothing."""
    summary = summarise(report)
    assert summary.tasks == 6
    assert summary.passed == 1
    assert summary.failed == 5
    assert summary.errored == 0

    failing_stages = {
        r.verdicts[-1].verifier.stage for r in report.results if r.status is Status.FAIL
    }
    assert failing_stages == set(Stage), "every stage should be demonstrated"


def test_the_breakdown_accounts_for_every_task_at_every_stage(report: Report) -> None:
    for row in breakdown(report):
        total = row.passed + row.failed + row.errored + row.not_reached
        assert total == 6, row.stage


def test_the_behavioural_failure_is_the_interesting_one(report: Report) -> None:
    """`rle` passes every check short of running the tests. That is the whole case."""
    (rle,) = [r for r in report.results if r.task_id == "rle"]

    assert [v.status for v in rle.verdicts[:-1]] == [Status.PASS] * 4
    assert rle.verdicts[-1].status is Status.FAIL
    assert rle.verdicts[-1].verifier.name == "pytest"
    assert rle.skipped == ()


def test_the_example_exits_one(report: Report) -> None:
    assert exit_code(report) == 1
