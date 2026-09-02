"""Stage 4: does the artifact behave as specified?"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from decidable.models import (
    Artifact,
    Evidence,
    EvidenceValue,
    Stage,
    Status,
    Verdict,
    VerifierRef,
)
from decidable.verifiers.base import error_verdict
from decidable.verifiers.python._process import PYTHON, run, truncate, workspace

TESTS_FILENAME = "test_properties.py"

ALL_PASSED = 0
TESTS_FAILED = 1
COLLECTION_INTERRUPTED = 2
NO_TESTS_COLLECTED = 5


class PytestVerifier:
    """Run property tests against the artifact with pytest.

    The tests are supplied when the verifier is constructed, which is what keeps
    :meth:`verify` a function of the artifact alone. They import the artifact by
    module name::

        PytestVerifier("from solution import fizzbuzz\\n\\ndef test_three(): ...")

    Collecting no tests is an ``ERROR``, not a ``PASS``. An empty test run
    decides nothing about the agent, and reporting it as success would be the
    most flattering lie the harness could tell.
    """

    name = "pytest"
    stage = Stage.BEHAVIOURAL

    def __init__(
        self,
        tests: str,
        *,
        module_name: str = "solution",
        timeout_s: float = 60.0,
    ) -> None:
        self.tests = tests
        self.module_name = module_name
        self.timeout_s = timeout_s

    def verify(self, artifact: Artifact, /) -> Verdict:
        me = VerifierRef(name=self.name, stage=self.stage)
        try:
            tool_version = version("pytest")
        except PackageNotFoundError as exc:
            return error_verdict(
                me,
                exc,
                evidence=Evidence(
                    summary="pytest is not installed: "
                    "install it, or the decidable[python] extra"
                ),
            )

        with workspace(artifact, filename=f"{self.module_name}.py") as root:
            (root / TESTS_FILENAME).write_text(self.tests, encoding="utf-8")
            completed = run(
                [
                    PYTHON,
                    "-m",
                    "pytest",
                    "-q",
                    "--no-header",
                    "--tb=short",
                    "-p",
                    "no:cacheprovider",
                    TESTS_FILENAME,
                ],
                cwd=root,
                timeout_s=self.timeout_s,
            )

        context: dict[str, EvidenceValue] = {"pytest_version": tool_version}
        report = truncate(completed.stdout or completed.stderr)

        if completed.timed_out:
            return Verdict(
                status=Status.FAIL,
                verifier=me,
                evidence=Evidence(
                    summary=f"tests did not finish within {self.timeout_s}s",
                    detail=report,
                    data={**context, "timed_out": True, "timeout_s": self.timeout_s},
                ),
            )

        if completed.exit_code == ALL_PASSED:
            return Verdict(
                status=Status.PASS,
                verifier=me,
                evidence=Evidence(
                    summary="all property tests passed",
                    data={**context, "exit_code": completed.exit_code},
                ),
            )

        if completed.exit_code == TESTS_FAILED:
            return Verdict(
                status=Status.FAIL,
                verifier=me,
                evidence=Evidence(
                    summary="property tests failed",
                    detail=report,
                    data={**context, "exit_code": completed.exit_code},
                ),
            )

        if completed.exit_code == COLLECTION_INTERRUPTED and _blames_artifact(
            report, self.module_name
        ):
            return Verdict(
                status=Status.FAIL,
                verifier=me,
                evidence=Evidence(
                    summary="the property tests could not import the artifact",
                    detail=report,
                    data={**context, "exit_code": completed.exit_code},
                ),
            )

        return _cannot_decide(me, completed.exit_code, report, context)


def _blames_artifact(report: str | None, module_name: str) -> bool:
    """Did collection fail because of the artifact, or because of the tests?

    pytest exits 2 for any collection error, but the two causes belong on
    opposite sides of the ERROR/FAIL line: an artifact that cannot be imported
    is the agent's failure, while property tests that do not themselves import
    are ours. The distinction has to come from the report, so it keys on the
    artifact module appearing in the traceback pytest printed.
    """
    if report is None:
        return False
    return f"{module_name}.py" in report or f"from '{module_name}'" in report


def _cannot_decide(
    me: VerifierRef,
    exit_code: int,
    report: str | None,
    context: dict[str, EvidenceValue],
) -> Verdict:
    """pytest neither passed nor failed the artifact, so nothing was decided."""
    if exit_code == NO_TESTS_COLLECTED:
        reason = "pytest collected no tests, so nothing about the agent was decided"
    elif exit_code == COLLECTION_INTERRUPTED:
        reason = "the property tests could not be collected"
    else:
        reason = f"pytest exited {exit_code} without running the tests"
    return error_verdict(
        me,
        RuntimeError(reason),
        evidence=Evidence(
            summary=reason,
            detail=report,
            data={**context, "exit_code": exit_code},
        ),
    )
