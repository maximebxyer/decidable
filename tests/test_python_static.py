"""Stage 2: a tool's findings are the agent's failure; a tool's absence is ours."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import pytest

from decidable.models import Stage, Status
from decidable.verifiers.python import MypyVerifier, RuffVerifier

CLEAN = 'def fizzbuzz(n: int) -> str:\n    return "fizz" if n % 3 == 0 else str(n)\n'
WRONG_RETURN_TYPE = "def fizzbuzz(n: int) -> str:\n    return n\n"
UNTYPED = "def fizzbuzz(n):\n    return str(n)\n"


def test_mypy_passes_clean_source() -> None:
    verdict = MypyVerifier().verify(CLEAN)

    assert verdict.status is Status.PASS
    assert (verdict.verifier.name, verdict.verifier.stage) == ("mypy", Stage.STATIC)
    assert verdict.evidence.data["mypy_version"]
    assert verdict.evidence.data["strict"] is True


def test_mypy_fails_a_type_error_with_its_code() -> None:
    verdict = MypyVerifier().verify(WRONG_RETURN_TYPE)

    assert verdict.status is Status.FAIL
    assert verdict.error is None
    assert verdict.evidence.data["error_count"] == 1
    assert verdict.evidence.data["codes"] == ("return-value",)
    assert verdict.evidence.detail is not None


def test_mypy_strictness_is_the_verifiers_own() -> None:
    """Untyped source fails under strict and passes without it.

    The point is that the verdict comes from how the verifier was constructed,
    not from whatever config happens to be lying around.
    """
    assert MypyVerifier(strict=True).verify(UNTYPED).status is Status.FAIL
    assert MypyVerifier(strict=False).verify(UNTYPED).status is Status.PASS


def test_mypy_ignores_the_ambient_project_config() -> None:
    """decidable's own pyproject sets mypy strict. It must not reach the artifact."""
    verdict = MypyVerifier(strict=False).verify(UNTYPED)

    assert verdict.status is Status.PASS


def test_a_missing_mypy_is_an_error_not_a_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def absent(_: str) -> str:
        raise PackageNotFoundError("mypy")

    monkeypatch.setattr("decidable.verifiers.python.static.version", absent)
    verdict = MypyVerifier().verify(CLEAN)

    assert verdict.status is Status.ERROR
    assert verdict.error is not None
    assert verdict.error.exception_type == "PackageNotFoundError"
    assert "decidable[python]" in verdict.evidence.summary


def test_ruff_passes_clean_source() -> None:
    verdict = RuffVerifier().verify(CLEAN)

    assert verdict.status is Status.PASS
    assert (verdict.verifier.name, verdict.verifier.stage) == ("ruff", Stage.STATIC)
    assert verdict.evidence.data["ruff_version"]


def test_ruff_fails_a_violation_with_its_rule_code() -> None:
    verdict = RuffVerifier().verify("import os\n")

    assert verdict.status is Status.FAIL
    assert verdict.error is None
    codes = verdict.evidence.data["codes"]
    assert isinstance(codes, tuple)
    assert "F401" in codes
    assert verdict.evidence.detail is not None
    assert "F401" in verdict.evidence.detail


def test_a_missing_ruff_is_an_error_not_a_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def absent(_: str) -> str:
        raise PackageNotFoundError("ruff")

    monkeypatch.setattr("decidable.verifiers.python.static.version", absent)
    verdict = RuffVerifier().verify(CLEAN)

    assert verdict.status is Status.ERROR
    assert verdict.error is not None
