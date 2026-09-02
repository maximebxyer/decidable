"""Stage 2: does the artifact type-check and lint?

Both verifiers here pin their tool to a generated, empty configuration, so the
configuration of whatever project decidable happens to be running inside can
never leak into a verdict. A verdict that depends on the current directory is
not reproducible.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

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
from decidable.verifiers.python._process import (
    PYTHON,
    CompletedRun,
    run,
    truncate,
    workspace,
)

CLEAN = 0
VIOLATIONS_FOUND = 1

_MISSING_TOOL_HINT = "install it, or the decidable[python] extra"


class MypyVerifier:
    """Type-check the artifact with mypy."""

    name = "mypy"
    stage = Stage.STATIC

    def __init__(self, *, strict: bool = True, timeout_s: float = 120.0) -> None:
        self.strict = strict
        self.timeout_s = timeout_s
        # Resolved once: the version is both what verdicts report and part of
        # what makes a cached verdict from an older mypy invalid.
        self._version = _tool_version("mypy")
        self.fingerprint = (
            f"mypy/{_label(self._version)}/strict={strict}/timeout={timeout_s}"
        )

    def verify(self, artifact: Artifact, /) -> Verdict:
        me = VerifierRef(name=self.name, stage=self.stage, fingerprint=self.fingerprint)
        tool_version = self._version
        if isinstance(tool_version, PackageNotFoundError):
            return _missing_tool(me, "mypy", tool_version)

        with workspace(artifact) as root:
            config = root / "mypy.ini"
            config.write_text("[mypy]\n", encoding="utf-8")
            argv = [
                PYTHON,
                "-m",
                "mypy",
                f"--config-file={config}",
                f"--cache-dir={root / '.mypy_cache'}",
                "--output=json",
                "--no-error-summary",
                "--no-color-output",
            ]
            if self.strict:
                argv.append("--strict")
            argv.append("solution.py")
            completed = run(argv, cwd=root, timeout_s=self.timeout_s)

        context: dict[str, EvidenceValue] = {
            "mypy_version": tool_version,
            "strict": self.strict,
        }
        if completed.timed_out:
            return _tool_timeout(me, "mypy", self.timeout_s, context)
        if completed.exit_code == CLEAN:
            return Verdict(
                status=Status.PASS,
                verifier=me,
                evidence=Evidence(summary="type-checks clean", data=context),
            )
        if completed.exit_code != VIOLATIONS_FOUND:
            return _tool_failed(me, "mypy", completed, context)

        diagnostics = _parse_json_lines(completed.stdout)
        if diagnostics is None:
            return _tool_failed(me, "mypy", completed, context)

        codes = _distinct_codes(diagnostics, "code")
        return Verdict(
            status=Status.FAIL,
            verifier=me,
            evidence=Evidence(
                summary=_summarise("type error", diagnostics),
                detail=truncate(completed.stdout),
                data={**context, "error_count": len(diagnostics), "codes": codes},
            ),
        )


class RuffVerifier:
    """Lint the artifact with ruff, on ruff's default rule set."""

    name = "ruff"
    stage = Stage.STATIC

    def __init__(self, *, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s
        self._version = _tool_version("ruff")
        self.fingerprint = f"ruff/{_label(self._version)}/timeout={timeout_s}"

    def verify(self, artifact: Artifact, /) -> Verdict:
        me = VerifierRef(name=self.name, stage=self.stage, fingerprint=self.fingerprint)
        tool_version = self._version
        if isinstance(tool_version, PackageNotFoundError):
            return _missing_tool(me, "ruff", tool_version)

        with workspace(artifact) as root:
            completed = run(
                [
                    PYTHON,
                    "-m",
                    "ruff",
                    "check",
                    "--isolated",
                    "--no-cache",
                    "--output-format=json",
                    "solution.py",
                ],
                cwd=root,
                timeout_s=self.timeout_s,
            )

        context: dict[str, EvidenceValue] = {"ruff_version": tool_version}
        if completed.timed_out:
            return _tool_timeout(me, "ruff", self.timeout_s, context)
        if completed.exit_code == CLEAN:
            return Verdict(
                status=Status.PASS,
                verifier=me,
                evidence=Evidence(summary="no lint violations", data=context),
            )
        if completed.exit_code != VIOLATIONS_FOUND:
            return _tool_failed(me, "ruff", completed, context)

        diagnostics = _parse_json_array(completed.stdout)
        if diagnostics is None:
            return _tool_failed(me, "ruff", completed, context)

        codes = _distinct_codes(diagnostics, "code")
        return Verdict(
            status=Status.FAIL,
            verifier=me,
            evidence=Evidence(
                summary=_summarise("lint violation", diagnostics),
                detail=truncate(_render(diagnostics)),
                data={**context, "violation_count": len(diagnostics), "codes": codes},
            ),
        )


def _tool_version(distribution: str) -> str | PackageNotFoundError:
    """The installed version, or the exception explaining why there isn't one.

    Resolved at construction so a missing tool never crashes on import, only
    ever produces an honest ERROR verdict when the verifier is asked to decide.
    """
    try:
        return version(distribution)
    except PackageNotFoundError as exc:
        return exc


def _label(tool_version: str | PackageNotFoundError) -> str:
    return "absent" if isinstance(tool_version, PackageNotFoundError) else tool_version


def _missing_tool(me: VerifierRef, tool: str, exc: PackageNotFoundError) -> Verdict:
    return error_verdict(
        me,
        exc,
        evidence=Evidence(summary=f"{tool} is not installed: {_MISSING_TOOL_HINT}"),
    )


def _tool_timeout(
    me: VerifierRef, tool: str, timeout_s: float, context: dict[str, EvidenceValue]
) -> Verdict:
    """A stalled tool is our problem, not the agent's."""
    exc = TimeoutError(f"{tool} did not finish within {timeout_s}s")
    return error_verdict(
        me,
        exc,
        evidence=Evidence(summary=str(exc), data={**context, "timeout_s": timeout_s}),
    )


def _tool_failed(
    me: VerifierRef,
    tool: str,
    completed: CompletedRun,
    context: dict[str, EvidenceValue],
) -> Verdict:
    """The tool exited in a way that says nothing about the artifact."""
    exc = RuntimeError(f"{tool} exited {completed.exit_code} without a usable report")
    return error_verdict(
        me,
        exc,
        evidence=Evidence(
            summary=str(exc),
            detail=truncate(completed.stderr or completed.stdout),
            data={**context, "exit_code": completed.exit_code},
        ),
    )


def _parse_json_lines(output: str) -> list[dict[str, Any]] | None:
    """mypy --output=json emits one JSON object per line."""
    diagnostics: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            diagnostics.append(json.loads(line))
        except json.JSONDecodeError:
            return None
    return diagnostics or None


def _parse_json_array(output: str) -> list[dict[str, Any]] | None:
    """ruff --output-format=json emits a single JSON array."""
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    return parsed


def _distinct_codes(diagnostics: Sequence[dict[str, Any]], key: str) -> tuple[str, ...]:
    """Sorted distinct codes: the field that aggregates across a whole suite."""
    return tuple(sorted({str(d[key]) for d in diagnostics if d.get(key)}))


def _summarise(noun: str, diagnostics: Sequence[dict[str, Any]]) -> str:
    count = len(diagnostics)
    plural = "" if count == 1 else "s"
    first = str(diagnostics[0].get("message", "")).splitlines()[0]
    return f"{count} {noun}{plural}: {first}"


def _render(diagnostics: Sequence[dict[str, Any]]) -> str:
    """ruff's JSON, flattened back into something a human reads."""
    lines = []
    for d in diagnostics:
        location = d.get("location") or {}
        row = location.get("row", "?")
        column = location.get("column", "?")
        lines.append(
            f"{Path(str(d.get('filename', '?'))).name}:{row}:{column} "
            f"{d.get('code', '?')} {d.get('message', '')}"
        )
    return "\n".join(lines)
