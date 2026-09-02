"""Stage 1: does the artifact parse as Python at all?"""

from __future__ import annotations

import ast
import platform

from decidable.models import Artifact, Evidence, Stage, Status, Verdict, VerifierRef

FILENAME = "solution.py"


class ParseVerifier:
    """Parse the artifact with :func:`ast.parse`.

    The cheapest check there is, and the one that decides whether anything after
    it is worth running. Source that does not parse is a ``FAIL`` and never an
    ``ERROR``: catching exactly that is what this stage is for.
    """

    name = "python_parse"
    stage = Stage.SYNTACTIC

    def verify(self, artifact: Artifact, /) -> Verdict:
        me = VerifierRef(name=self.name, stage=self.stage)
        try:
            ast.parse(artifact, filename=FILENAME)
        except SyntaxError as exc:
            return Verdict(
                status=Status.FAIL,
                verifier=me,
                evidence=Evidence(
                    summary=_summarise(exc),
                    detail=_offending_source(exc),
                    data={
                        "line": exc.lineno,
                        "column": exc.offset,
                        "error": exc.msg,
                    },
                ),
            )
        except ValueError as exc:
            # Source containing a null byte, which never reaches SyntaxError.
            return Verdict(
                status=Status.FAIL,
                verifier=me,
                evidence=Evidence(
                    summary=f"cannot be parsed: {exc}",
                    data={"error": str(exc)},
                ),
            )
        return Verdict(
            status=Status.PASS,
            verifier=me,
            evidence=Evidence(
                summary="parses as Python",
                data={"python_version": platform.python_version()},
            ),
        )


def _summarise(exc: SyntaxError) -> str:
    if exc.lineno is None:
        return f"syntax error: {exc.msg}"
    return f"syntax error on line {exc.lineno}: {exc.msg}"


def _offending_source(exc: SyntaxError) -> str | None:
    """The source line with a caret under the offending column, if we have it."""
    if exc.text is None:
        return None
    line = exc.text.rstrip("\n")
    if exc.offset is None:
        return line
    return f"{line}\n{' ' * max(exc.offset - 1, 0)}^"
