"""Stage 3: running the artifact. Here a timeout is the artifact's fault."""

from __future__ import annotations

from decidable.models import Stage, Status
from decidable.verifiers.python import ExecuteVerifier


def test_a_clean_run_passes() -> None:
    verdict = ExecuteVerifier().verify("print('hello')\n")

    assert verdict.status is Status.PASS
    assert (verdict.verifier.name, verdict.verifier.stage) == (
        "python_execute",
        Stage.DYNAMIC,
    )
    assert verdict.evidence.data["exit_code"] == 0
    assert verdict.evidence.detail == "hello"


def test_a_crash_fails_with_the_exception_line() -> None:
    verdict = ExecuteVerifier().verify("raise ValueError('boom')\n")

    assert verdict.status is Status.FAIL
    assert verdict.error is None
    assert verdict.evidence.data["exit_code"] == 1
    assert "ValueError: boom" in verdict.evidence.summary
    assert verdict.evidence.detail is not None
    assert "Traceback" in verdict.evidence.detail


def test_a_nonzero_exit_fails() -> None:
    verdict = ExecuteVerifier().verify("import sys\n\nsys.exit(3)\n")

    assert verdict.status is Status.FAIL
    assert verdict.evidence.data["exit_code"] == 3


def test_code_that_never_terminates_fails() -> None:
    """The artifact did not finish, which is a fact about the artifact."""
    verdict = ExecuteVerifier(timeout_s=1.0).verify("while True:\n    pass\n")

    assert verdict.status is Status.FAIL
    assert verdict.error is None
    assert verdict.evidence.data["timed_out"] is True
    assert verdict.evidence.data["timeout_s"] == 1.0


def test_the_artifact_runs_in_its_own_directory() -> None:
    """It should not see the decidable checkout it happens to be verified from."""
    verdict = ExecuteVerifier().verify(
        "import pathlib\n"
        "\n"
        "assert not (pathlib.Path.cwd() / 'pyproject.toml').exists()\n"
        "print(sorted(p.name for p in pathlib.Path.cwd().iterdir()))\n"
    )

    assert verdict.status is Status.PASS
    assert verdict.evidence.detail == "['solution.py']"
