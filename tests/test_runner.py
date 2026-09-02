"""Running a suite: agent failure stays a harness condition, and the cache never lies."""

from __future__ import annotations

from pathlib import Path

import pytest

from decidable.models import (
    Artifact,
    Evidence,
    Stage,
    Status,
    Suite,
    Task,
    Verdict,
    VerifierRef,
)
from decidable.runner import run
from decidable.verifiers import VerifierStack


class CountingVerifier:
    """Passes or fails on demand, and remembers how often it was actually asked."""

    name = "counter"
    stage = Stage.SYNTACTIC

    def __init__(self, *, setting: str = "a", passes: bool = True) -> None:
        self.fingerprint = f"counter/{setting}"
        self.calls = 0
        self._passes = passes

    def verify(self, artifact: Artifact, /) -> Verdict:
        self.calls += 1
        return Verdict(
            status=Status.PASS if self._passes else Status.FAIL,
            verifier=VerifierRef(
                name=self.name, stage=self.stage, fingerprint=self.fingerprint
            ),
            evidence=Evidence(summary=f"saw {len(artifact)} characters"),
        )


def suite_of(*ids: str) -> Suite:
    return Suite(
        name="fizzbuzz",
        tasks=tuple(Task(id=i, prompt=f"write {i}") for i in ids),
    )


def echo(task: Task) -> Artifact:
    return f"# {task.id}\n"


def test_every_task_is_run_in_order() -> None:
    verifier = CountingVerifier()
    report = run(
        suite_of("a", "b", "c"), echo, stack_for=lambda _: VerifierStack([verifier])
    )

    assert [r.task_id for r in report.results] == ["a", "b", "c"]
    assert all(r.status is Status.PASS for r in report.results)
    assert verifier.calls == 3


def test_metadata_records_enough_to_re_derive_the_run() -> None:
    report = run(
        suite_of("a"),
        echo,
        stack_for=lambda _: VerifierStack([CountingVerifier()]),
    )

    metadata = report.metadata
    assert metadata.suite_name == "fizzbuzz"
    assert metadata.agent_name == "echo"
    assert metadata.decidable_version
    assert metadata.python_version
    assert metadata.platform
    assert metadata.finished_at >= metadata.started_at
    assert metadata.cache_dir is None
    assert metadata.cache_hits == 0


def test_the_artifact_digest_ties_a_result_to_what_produced_it() -> None:
    report = run(
        suite_of("a"), echo, stack_for=lambda _: VerifierStack([CountingVerifier()])
    )

    (result,) = report.results
    assert result.artifact_digest is not None
    assert len(result.artifact_digest) == 64


def test_an_agent_that_raises_is_an_error_and_stops_nothing() -> None:
    """Nothing was decided about the agent, and the rest of the suite still runs."""

    def flaky(task: Task) -> Artifact:
        if task.id == "b":
            raise RuntimeError("the model API fell over")
        return f"# {task.id}\n"

    report = run(
        suite_of("a", "b", "c"),
        flaky,
        stack_for=lambda _: VerifierStack([CountingVerifier()]),
    )

    a, b, c = report.results
    assert a.status is Status.PASS
    assert c.status is Status.PASS

    assert b.status is Status.ERROR
    assert b.error is not None
    assert b.error.exception_type == "RuntimeError"
    assert b.error.message == "the model API fell over"
    assert b.verdicts == ()
    assert b.artifact_digest is None


def test_a_stack_factory_that_raises_is_also_an_error() -> None:
    def broken(task: Task) -> VerifierStack:
        raise FileNotFoundError("fixtures/missing.py")

    report = run(suite_of("a"), echo, stack_for=broken)

    (result,) = report.results
    assert result.status is Status.ERROR
    assert result.error is not None
    assert result.error.exception_type == "FileNotFoundError"


def test_agent_name_can_be_given_when_the_callable_has_no_useful_one() -> None:
    report = run(
        suite_of("a"),
        lambda task: "x = 1\n",
        stack_for=lambda _: VerifierStack([CountingVerifier()]),
        agent_name="gpt-fake-1",
    )

    assert report.metadata.agent_name == "gpt-fake-1"


def test_without_a_cache_dir_nothing_is_remembered() -> None:
    verifier = CountingVerifier()
    for _ in range(2):
        run(suite_of("a"), echo, stack_for=lambda _: VerifierStack([verifier]))

    assert verifier.calls == 2


def test_a_second_identical_run_verifies_nothing_again(tmp_path: Path) -> None:
    first = CountingVerifier()
    run(
        suite_of("a", "b"),
        echo,
        stack_for=lambda _: VerifierStack([first]),
        cache_dir=tmp_path,
    )
    assert first.calls == 2

    second = CountingVerifier()
    report = run(
        suite_of("a", "b"),
        echo,
        stack_for=lambda _: VerifierStack([second]),
        cache_dir=tmp_path,
    )

    assert second.calls == 0
    assert report.metadata.cache_hits == 2
    assert all(r.status is Status.PASS for r in report.results)


def test_a_changed_fingerprint_invalidates_the_cache(tmp_path: Path) -> None:
    """The cache must never serve a verdict from a differently configured verifier."""
    original = CountingVerifier(setting="strict", passes=True)
    run(
        suite_of("a"),
        echo,
        stack_for=lambda _: VerifierStack([original]),
        cache_dir=tmp_path,
    )
    assert original.calls == 1

    reconfigured = CountingVerifier(setting="lenient", passes=False)
    report = run(
        suite_of("a"),
        echo,
        stack_for=lambda _: VerifierStack([reconfigured]),
        cache_dir=tmp_path,
    )

    assert reconfigured.calls == 1
    assert report.metadata.cache_hits == 0
    assert report.results[0].status is Status.FAIL


def test_a_different_artifact_invalidates_the_cache(tmp_path: Path) -> None:
    verifier = CountingVerifier()
    for artifact in ("x = 1\n", "x = 2\n"):
        run(
            suite_of("a"),
            lambda _, source=artifact: source,
            stack_for=lambda _: VerifierStack([verifier]),
            cache_dir=tmp_path,
        )

    assert verifier.calls == 2


def test_a_corrupt_cache_entry_is_a_miss_not_a_crash(tmp_path: Path) -> None:
    """A cache is an optimisation. One that can change a verdict is a bug."""
    first = CountingVerifier()
    run(
        suite_of("a"),
        echo,
        stack_for=lambda _: VerifierStack([first]),
        cache_dir=tmp_path,
    )

    (entry,) = list(tmp_path.glob("*.json"))
    entry.write_text("{ not json at all", encoding="utf-8")

    second = CountingVerifier()
    report = run(
        suite_of("a"),
        echo,
        stack_for=lambda _: VerifierStack([second]),
        cache_dir=tmp_path,
    )

    assert second.calls == 1
    assert report.metadata.cache_hits == 0
    assert report.results[0].status is Status.PASS


def test_a_cache_entry_records_the_inputs_of_its_key(tmp_path: Path) -> None:
    """A stale cache directory should be inspectable by hand."""
    run(
        suite_of("a"),
        echo,
        stack_for=lambda _: VerifierStack([CountingVerifier()]),
        cache_dir=tmp_path,
    )

    (entry,) = list(tmp_path.glob("*.json"))
    written = entry.read_text(encoding="utf-8")
    assert "counter/a" in written
    assert "decidable_version" in written


def test_a_suite_refuses_duplicate_task_ids() -> None:
    with pytest.raises(ValueError, match="unique"):
        suite_of("a", "b", "a")
