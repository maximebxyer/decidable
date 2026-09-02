"""Stage 1: source that does not parse is the agent's failure, never ours."""

from __future__ import annotations

from decidable.models import Stage, Status
from decidable.verifiers.python import ParseVerifier


def test_valid_source_passes() -> None:
    verdict = ParseVerifier().verify(
        "def fizzbuzz(n: int) -> str:\n    return str(n)\n"
    )

    assert verdict.status is Status.PASS
    assert (verdict.verifier.name, verdict.verifier.stage) == (
        "python_parse",
        Stage.SYNTACTIC,
    )
    assert verdict.evidence.summary == "parses as Python"
    assert verdict.evidence.data["python_version"]


def test_a_syntax_error_fails_with_its_position() -> None:
    verdict = ParseVerifier().verify("def fizzbuzz(:\n    return 1\n")

    assert verdict.status is Status.FAIL
    assert verdict.error is None
    assert verdict.evidence.data["line"] == 1
    assert verdict.evidence.data["column"] is not None
    assert "syntax error on line 1" in verdict.evidence.summary


def test_the_offending_line_is_shown_with_a_caret() -> None:
    verdict = ParseVerifier().verify("x = (1 +\n")

    assert verdict.status is Status.FAIL
    assert verdict.evidence.detail is not None
    assert "^" in verdict.evidence.detail


def test_a_null_byte_fails_rather_than_errors() -> None:
    """ast.parse raises ValueError here, but it is still the artifact's problem."""
    verdict = ParseVerifier().verify("x = 1\x00\n")

    assert verdict.status is Status.FAIL
    assert verdict.error is None


def test_an_empty_artifact_parses() -> None:
    """Empty source is valid Python. Deciding it is useless is a later stage's job."""
    assert ParseVerifier().verify("").status is Status.PASS
