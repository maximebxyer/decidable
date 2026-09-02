"""The four stages composed: where each artifact breaks, and what is skipped.

This is the failure taxonomy the project exists to produce. Five artifacts, each
surviving one stage further than the last.
"""

from __future__ import annotations

import pytest

from decidable.models import Stage, Status
from decidable.verifiers import VerifierStack
from decidable.verifiers.python import (
    ExecuteVerifier,
    MypyVerifier,
    ParseVerifier,
    PytestVerifier,
    RuffVerifier,
)

TESTS = """
from solution import fizzbuzz


def test_multiples_of_three():
    assert fizzbuzz(3) == "fizz"


def test_plain_numbers():
    assert fizzbuzz(1) == "1"
"""

DOES_NOT_PARSE = "def fizzbuzz(:\n"

DOES_NOT_TYPE_CHECK = """
def fizzbuzz(n: int) -> str:
    return n
"""

DOES_NOT_LINT = """
import os


def fizzbuzz(n: int) -> str:
    return "fizz" if n % 3 == 0 else str(n)
"""

DOES_NOT_RUN = """
def fizzbuzz(n: int) -> str:
    return "fizz" if n % 3 == 0 else str(n)


fizzbuzz(1 // 0)
"""

WRONG_ANSWERS = """
def fizzbuzz(n: int) -> str:
    return str(n)
"""

CORRECT = """
def fizzbuzz(n: int) -> str:
    return "fizz" if n % 3 == 0 else str(n)
"""


@pytest.fixture(scope="module")
def stack() -> VerifierStack:
    return VerifierStack(
        [
            ParseVerifier(),
            MypyVerifier(),
            RuffVerifier(),
            ExecuteVerifier(timeout_s=10.0),
            PytestVerifier(TESTS),
        ]
    )


@pytest.mark.parametrize(
    ("artifact", "failing_verifier", "stage", "reached"),
    [
        (DOES_NOT_PARSE, "python_parse", Stage.SYNTACTIC, 1),
        (DOES_NOT_TYPE_CHECK, "mypy", Stage.STATIC, 2),
        (DOES_NOT_LINT, "ruff", Stage.STATIC, 3),
        (DOES_NOT_RUN, "python_execute", Stage.DYNAMIC, 4),
        (WRONG_ANSWERS, "pytest", Stage.BEHAVIOURAL, 5),
    ],
    ids=["parse", "types", "lint", "runtime", "behaviour"],
)
def test_each_artifact_fails_at_exactly_one_stage(
    stack: VerifierStack,
    artifact: str,
    failing_verifier: str,
    stage: Stage,
    reached: int,
) -> None:
    result = stack.run(artifact)

    assert result.status is Status.FAIL
    assert len(result.verdicts) == reached
    assert all(v.status is Status.PASS for v in result.verdicts[:-1])

    terminal = result.verdicts[-1]
    assert terminal.status is Status.FAIL
    assert terminal.verifier.name == failing_verifier
    assert terminal.verifier.stage is stage
    assert terminal.evidence.summary

    assert len(result.skipped) == 5 - reached
    assert failing_verifier not in [ref.name for ref in result.skipped]


def test_a_correct_artifact_passes_every_stage(stack: VerifierStack) -> None:
    result = stack.run(CORRECT)

    assert result.status is Status.PASS
    assert [v.verifier.name for v in result.verdicts] == [
        "python_parse",
        "mypy",
        "ruff",
        "python_execute",
        "pytest",
    ]
    assert result.skipped == ()
    assert all(v.duration_s is not None for v in result.verdicts)
