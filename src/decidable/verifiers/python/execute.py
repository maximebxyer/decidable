"""Stage 3: does the artifact run to completion, inside a time budget?"""

from __future__ import annotations

import platform

from decidable.models import Artifact, Evidence, Stage, Status, Verdict, VerifierRef
from decidable.verifiers.python._process import (
    PYTHON,
    last_line,
    run,
    truncate,
    workspace,
)

EXIT_OK = 0


class ExecuteVerifier:
    """Run the artifact as a script and check that it exits cleanly.

    A timeout here is a ``FAIL``: code that does not terminate inside its budget
    is wrong code, and that is precisely the question this stage asks. Contrast
    the static verifiers, where a stalled *tool* is an ``ERROR``.

    This runs the artifact in a subprocess of the current interpreter. That is
    isolation enough to contain a crash or a runaway loop, and it is **not** a
    security boundary.
    """

    name = "python_execute"
    stage = Stage.DYNAMIC

    def __init__(self, *, timeout_s: float = 10.0) -> None:
        self.timeout_s = timeout_s
        # The timeout is part of the configuration: it decides verdicts.
        self.fingerprint = (
            f"python_execute/{platform.python_version()}/timeout={timeout_s}"
        )

    def verify(self, artifact: Artifact, /) -> Verdict:
        me = VerifierRef(name=self.name, stage=self.stage, fingerprint=self.fingerprint)
        with workspace(artifact) as root:
            completed = run([PYTHON, "solution.py"], cwd=root, timeout_s=self.timeout_s)

        if completed.timed_out:
            return Verdict(
                status=Status.FAIL,
                verifier=me,
                evidence=Evidence(
                    summary=f"did not finish within {self.timeout_s}s",
                    detail=truncate(completed.stdout),
                    data={"timed_out": True, "timeout_s": self.timeout_s},
                ),
            )

        if completed.exit_code != EXIT_OK:
            return Verdict(
                status=Status.FAIL,
                verifier=me,
                evidence=Evidence(
                    summary=_summarise(completed.exit_code, completed.stderr),
                    detail=truncate(completed.stderr),
                    data={"exit_code": completed.exit_code},
                ),
            )

        return Verdict(
            status=Status.PASS,
            verifier=me,
            evidence=Evidence(
                summary="ran to completion",
                detail=truncate(completed.stdout),
                data={"exit_code": completed.exit_code},
            ),
        )


def _summarise(exit_code: int, stderr: str) -> str:
    """For a crash, the exception line says far more than the exit code."""
    reason = last_line(stderr)
    if reason:
        return f"exited {exit_code}: {reason}"
    return f"exited {exit_code}"
