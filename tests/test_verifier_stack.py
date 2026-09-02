"""Stack ordering, short-circuiting, and the ERROR/FAIL distinction under composition."""

from __future__ import annotations

import pytest

from decidable.models import (
    Artifact,
    Evidence,
    HarnessError,
    Stage,
    Status,
    Verdict,
    VerifierRef,
)
from decidable.verifiers.base import VerifierStack

ARTIFACT = "def fizzbuzz(n: int) -> str: ...\n"


class FakeVerifier:
    """Records its invocation and returns a scripted verdict.

    Milestone 1 has no real verifiers yet, and the stack's contract is about
    composition, not about any particular check.
    """

    def __init__(
        self,
        name: str,
        stage: Stage,
        *,
        status: Status = Status.PASS,
        calls: list[str] | None = None,
        raises: Exception | None = None,
        attributed_to: VerifierRef | None = None,
    ) -> None:
        self.name = name
        self.stage = stage
        self.seen: list[Artifact] = []
        self._status = status
        self._calls = [] if calls is None else calls
        self._raises = raises
        self._attributed_to = attributed_to

    def verify(self, artifact: Artifact, /) -> Verdict:
        self._calls.append(self.name)
        self.seen.append(artifact)
        if self._raises is not None:
            raise self._raises
        error = (
            HarnessError(
                exception_type="CalledProcessError",
                message="mypy exited 2",
                traceback="(reported by the verifier, not raised)",
            )
            if self._status is Status.ERROR
            else None
        )
        return Verdict(
            status=self._status,
            verifier=self._attributed_to
            or VerifierRef(name=self.name, stage=self.stage),
            evidence=Evidence(summary=f"{self.name}: {self._status.value}"),
            error=error,
        )


def test_verifiers_run_in_declared_order() -> None:
    calls: list[str] = []
    stack = VerifierStack(
        [
            FakeVerifier("parse", Stage.SYNTACTIC, calls=calls),
            FakeVerifier("mypy", Stage.STATIC, calls=calls),
            FakeVerifier("pytest", Stage.BEHAVIOURAL, calls=calls),
        ]
    )

    result = stack.run(ARTIFACT)

    assert calls == ["parse", "mypy", "pytest"]
    assert [v.verifier.name for v in result.verdicts] == ["parse", "mypy", "pytest"]
    assert result.skipped == ()
    assert result.status is Status.PASS


def test_the_artifact_reaches_every_verifier() -> None:
    parse = FakeVerifier("parse", Stage.SYNTACTIC)
    mypy = FakeVerifier("mypy", Stage.STATIC)
    VerifierStack([parse, mypy]).run(ARTIFACT)

    assert parse.seen == [ARTIFACT]
    assert mypy.seen == [ARTIFACT]


def test_fail_short_circuits_and_records_what_was_skipped() -> None:
    calls: list[str] = []
    stack = VerifierStack(
        [
            FakeVerifier("parse", Stage.SYNTACTIC, calls=calls),
            FakeVerifier("mypy", Stage.STATIC, status=Status.FAIL, calls=calls),
            FakeVerifier("execute", Stage.DYNAMIC, calls=calls),
            FakeVerifier("pytest", Stage.BEHAVIOURAL, calls=calls),
        ]
    )

    result = stack.run(ARTIFACT)

    assert calls == ["parse", "mypy"]
    assert [v.status for v in result.verdicts] == [Status.PASS, Status.FAIL]
    assert result.skipped == (
        VerifierRef(name="execute", stage=Stage.DYNAMIC),
        VerifierRef(name="pytest", stage=Stage.BEHAVIOURAL),
    )
    assert result.status is Status.FAIL


def test_error_short_circuits_and_stays_an_error() -> None:
    """A verifier that could not run tells us nothing about the ones after it."""
    calls: list[str] = []
    stack = VerifierStack(
        [
            FakeVerifier("parse", Stage.SYNTACTIC, calls=calls),
            FakeVerifier("mypy", Stage.STATIC, status=Status.ERROR, calls=calls),
            FakeVerifier("pytest", Stage.BEHAVIOURAL, calls=calls),
        ]
    )

    result = stack.run(ARTIFACT)

    assert calls == ["parse", "mypy"]
    assert result.status is Status.ERROR
    assert result.skipped == (VerifierRef(name="pytest", stage=Stage.BEHAVIOURAL),)


def test_a_crashing_verifier_yields_error_never_fail() -> None:
    calls: list[str] = []
    stack = VerifierStack(
        [
            FakeVerifier(
                "mypy",
                Stage.STATIC,
                calls=calls,
                raises=FileNotFoundError("mypy: command not found"),
            ),
            FakeVerifier("pytest", Stage.BEHAVIOURAL, calls=calls),
        ]
    )

    result = stack.run(ARTIFACT)

    assert calls == ["mypy"]
    (crashed,) = result.verdicts
    assert crashed.status is Status.ERROR
    assert crashed.verifier == VerifierRef(name="mypy", stage=Stage.STATIC)
    assert crashed.evidence.summary == "mypy raised FileNotFoundError"

    assert crashed.error is not None
    assert crashed.error.exception_type == "FileNotFoundError"
    assert crashed.error.message == "mypy: command not found"
    assert "FileNotFoundError: mypy: command not found" in crashed.error.traceback
    assert "in verify" in crashed.error.traceback


def test_a_crashing_verifier_does_not_abort_the_stack_machinery() -> None:
    """The exception is converted, not propagated: the run still returns a result."""
    stack = VerifierStack(
        [FakeVerifier("boom", Stage.SYNTACTIC, raises=RuntimeError())]
    )
    assert stack.run(ARTIFACT).status is Status.ERROR


def test_every_verdict_is_stamped_with_a_duration() -> None:
    stack = VerifierStack(
        [
            FakeVerifier("parse", Stage.SYNTACTIC),
            FakeVerifier("mypy", Stage.STATIC, raises=RuntimeError("boom")),
        ]
    )

    for produced in stack.run(ARTIFACT).verdicts:
        assert produced.duration_s is not None
        assert produced.duration_s >= 0.0


def test_a_stack_must_be_ordered_cheap_to_expensive() -> None:
    with pytest.raises(ValueError, match="cheap to expensive"):
        VerifierStack(
            [
                FakeVerifier("pytest", Stage.BEHAVIOURAL),
                FakeVerifier("parse", Stage.SYNTACTIC),
            ]
        )


def test_a_stack_may_repeat_a_stage() -> None:
    stack = VerifierStack(
        [
            FakeVerifier("mypy", Stage.STATIC),
            FakeVerifier("ruff", Stage.STATIC),
        ]
    )
    assert [v.name for v in stack.verifiers] == ["mypy", "ruff"]


def test_an_empty_stack_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one verifier"):
        VerifierStack([])


def test_a_misattributed_verdict_is_refused() -> None:
    """A verdict filed under the wrong stage would corrupt the failure taxonomy."""
    liar = FakeVerifier(
        "mypy",
        Stage.STATIC,
        attributed_to=VerifierRef(name="parse", stage=Stage.SYNTACTIC),
    )

    with pytest.raises(ValueError, match="misattributed"):
        VerifierStack([liar]).run(ARTIFACT)
