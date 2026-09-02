"""The Verifier protocol and its composition into an ordered, short-circuiting stack.

The load-bearing rule of this module: an exception escaping a verifier becomes an
``ERROR`` verdict, never a ``FAIL``. A verifier that crashes has told us nothing
about the agent, and reporting that as agent failure produces dishonest numbers.
"""

from __future__ import annotations

import itertools
import time
import traceback
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from decidable.models import (
    Artifact,
    Evidence,
    HarnessError,
    Stage,
    Status,
    Verdict,
    VerifierRef,
    roll_up,
)


class Verifier(Protocol):
    """A pure function from artifact to verdict. It never calls a model.

    Whatever a verifier needs in order to decide — expected output, a fixture
    path, a property test — is supplied when the verifier is constructed, which
    is what keeps :meth:`verify` a function of the artifact alone.
    """

    name: str
    stage: Stage

    def verify(self, artifact: Artifact, /) -> Verdict: ...


class StackResult(BaseModel):
    """What one stack execution produced, including what it did not reach."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdicts: tuple[Verdict, ...]
    skipped: tuple[VerifierRef, ...] = ()

    @property
    def status(self) -> Status:
        return roll_up(self.verdicts)


class VerifierStack:
    """An ordered composition of verifiers that stops at the first non-``PASS``.

    Ordering cheap-to-expensive is the point: it turns a pass rate into a failure
    taxonomy, so the stack refuses to be built out of order.
    """

    def __init__(self, verifiers: Sequence[Verifier]) -> None:
        if not verifiers:
            msg = "a verifier stack needs at least one verifier"
            raise ValueError(msg)
        for earlier, later in itertools.pairwise(verifiers):
            if later.stage.rank < earlier.stage.rank:
                msg = (
                    f"verifiers must be ordered cheap to expensive: "
                    f"{later.name!r} ({later.stage.value}) follows "
                    f"{earlier.name!r} ({earlier.stage.value})"
                )
                raise ValueError(msg)
        self._verifiers = tuple(verifiers)

    @property
    def verifiers(self) -> tuple[Verifier, ...]:
        return self._verifiers

    def run(self, artifact: Artifact, /) -> StackResult:
        """Run verifiers in order until one does not pass.

        Verifiers after the first non-``PASS`` are reported in
        :attr:`StackResult.skipped`, never as a verdict: "not reached" is
        represented by absence so that :class:`Status` stays a strict triad.
        """
        verdicts: list[Verdict] = []
        for index, verifier in enumerate(self._verifiers):
            verdict = _run_one(verifier, artifact)
            verdicts.append(verdict)
            if verdict.status is not Status.PASS:
                skipped = tuple(_ref(v) for v in self._verifiers[index + 1 :])
                return StackResult(verdicts=tuple(verdicts), skipped=skipped)
        return StackResult(verdicts=tuple(verdicts))


def _ref(verifier: Verifier) -> VerifierRef:
    return VerifierRef(name=verifier.name, stage=verifier.stage)


def _run_one(verifier: Verifier, artifact: Artifact) -> Verdict:
    ref = _ref(verifier)
    started = time.perf_counter()
    try:
        verdict = verifier.verify(artifact)
    except Exception as exc:  # noqa: BLE001 - see below; the breadth is the point
        # A crashing verifier has told us nothing about the agent, so every
        # exception it can raise must become ERROR rather than escape and be
        # mistaken for FAIL further up. BaseException still propagates.
        return _error_verdict(ref, exc, time.perf_counter() - started)
    duration_s = time.perf_counter() - started
    if verdict.verifier != ref:
        msg = (
            f"verifier {ref.name!r} returned a verdict attributed to "
            f"{verdict.verifier.name!r} ({verdict.verifier.stage.value}); "
            f"a misattributed verdict corrupts the failure taxonomy"
        )
        raise ValueError(msg)
    return verdict.model_copy(update={"duration_s": duration_s})


def _error_verdict(ref: VerifierRef, exc: Exception, duration_s: float) -> Verdict:
    return Verdict(
        status=Status.ERROR,
        verifier=ref,
        evidence=Evidence(summary=f"{ref.name} raised {type(exc).__name__}"),
        error=HarnessError(
            exception_type=type(exc).__name__,
            message=str(exc),
            traceback="".join(traceback.format_exception(exc)),
        ),
        duration_s=duration_s,
    )
