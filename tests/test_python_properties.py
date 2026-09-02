"""Stage 4: behaviour. An empty test run decides nothing and must not pass."""

from __future__ import annotations

from decidable.models import Stage, Status, VerifierRef
from decidable.verifiers.python import PytestVerifier

PYTEST = VerifierRef(name="pytest", stage=Stage.BEHAVIOURAL)

TESTS = """
from solution import fizzbuzz


def test_multiples_of_three():
    assert fizzbuzz(3) == "fizz"


def test_plain_numbers():
    assert fizzbuzz(1) == "1"
"""

CORRECT = """
def fizzbuzz(n: int) -> str:
    return "fizz" if n % 3 == 0 else str(n)
"""

WRONG = """
def fizzbuzz(n: int) -> str:
    return str(n)
"""


def test_passing_properties_pass() -> None:
    verdict = PytestVerifier(TESTS).verify(CORRECT)

    assert verdict.status is Status.PASS
    assert verdict.verifier == PYTEST
    assert verdict.evidence.data["pytest_version"]
    assert verdict.evidence.summary == "all property tests passed"


def test_a_failing_property_fails_with_the_assertion() -> None:
    verdict = PytestVerifier(TESTS).verify(WRONG)

    assert verdict.status is Status.FAIL
    assert verdict.error is None
    assert verdict.evidence.detail is not None
    assert "test_multiples_of_three" in verdict.evidence.detail
    assert "assert" in verdict.evidence.detail


def test_an_artifact_that_does_not_import_is_a_failure() -> None:
    """pytest exits 2 here, but the artifact is what could not be imported."""
    verdict = PytestVerifier(TESTS).verify("def not_fizzbuzz() -> None: ...\n")

    assert verdict.status is Status.FAIL
    assert verdict.error is None
    assert verdict.evidence.detail is not None
    assert "ImportError" in verdict.evidence.detail


def test_an_artifact_that_raises_on_import_is_a_failure() -> None:
    verdict = PytestVerifier(TESTS).verify("raise RuntimeError('boom')\n")

    assert verdict.status is Status.FAIL
    assert verdict.evidence.detail is not None
    assert "boom" in verdict.evidence.detail


def test_property_tests_that_do_not_collect_are_an_error() -> None:
    """The same exit code as above, but this time the breakage is ours."""
    verdict = PytestVerifier("def test_broken(:\n").verify(CORRECT)

    assert verdict.status is Status.ERROR
    assert verdict.error is not None
    assert "could not be collected" in verdict.evidence.summary


def test_collecting_no_tests_is_an_error_not_a_pass() -> None:
    """Vacuous success is the most flattering lie the harness could tell."""
    verdict = PytestVerifier("# no tests here\n").verify(CORRECT)

    assert verdict.status is Status.ERROR
    assert verdict.error is not None
    assert verdict.evidence.data["exit_code"] == 5
    assert "collected no tests" in verdict.evidence.summary


def test_the_module_name_is_configurable() -> None:
    verdict = PytestVerifier(
        "from candidate import answer\n\n\ndef test_answer():\n    assert answer() == 42\n",
        module_name="candidate",
    ).verify("def answer() -> int:\n    return 42\n")

    assert verdict.status is Status.PASS


def test_hanging_tests_fail() -> None:
    verdict = PytestVerifier(
        "from solution import spin\n\n\ndef test_spin():\n    spin()\n",
        timeout_s=2.0,
    ).verify("def spin() -> None:\n    while True:\n        pass\n")

    assert verdict.status is Status.FAIL
    assert verdict.evidence.data["timed_out"] is True
