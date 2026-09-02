"""The one place the Python verifiers touch the outside world.

Every tool invocation goes through :func:`run`, so isolation, timeouts and output
truncation are decided once rather than per verifier. This is *not* a security
boundary — see the safety note in the README.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

TRUNCATION_LIMIT = 8000

#: Tools are invoked through the running interpreter rather than looked up on
#: PATH, so they resolve inside whatever environment decidable itself is in.
PYTHON = sys.executable


@dataclass(frozen=True, slots=True)
class CompletedRun:
    """What a tool invocation produced.

    A plain dataclass rather than a pydantic model: this never crosses a public
    boundary, and validating our own subprocess output would buy nothing.
    """

    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@contextmanager
def workspace(artifact: str, *, filename: str = "solution.py") -> Iterator[Path]:
    """A temporary directory holding the artifact, removed on exit."""
    with tempfile.TemporaryDirectory(prefix="decidable-") as directory:
        root = Path(directory)
        (root / filename).write_text(artifact, encoding="utf-8")
        yield root


def run(argv: Sequence[str], *, cwd: Path, timeout_s: float) -> CompletedRun:
    """Run a tool to completion, capturing output.

    A timeout is reported rather than raised, because whether it means ``FAIL``
    or ``ERROR`` depends on which stage asked — running the artifact is the
    agent's problem, running a type-checker is ours. A missing executable *is*
    raised, since the stack turns that into an honest ``ERROR``.
    """
    try:
        # argv is always built by us; the artifact only ever arrives as a file.
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        return CompletedRun(
            argv=tuple(argv),
            exit_code=-1,
            stdout=_decode(expired.stdout),
            stderr=_decode(expired.stderr),
            timed_out=True,
        )
    return CompletedRun(
        argv=tuple(argv),
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def truncate(text: str, limit: int = TRUNCATION_LIMIT) -> str | None:
    """Cap evidence at a readable length, marking that it was cut."""
    text = text.strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [truncated, {len(text) - limit} more characters]"


def last_line(text: str) -> str:
    """The last non-blank line, which for a traceback is the exception itself."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _environment() -> dict[str, str]:
    """The child's environment: the ambient one, made more deterministic.

    Not emptied. Starting from nothing breaks the interpreter on Windows and
    would buy no isolation we could honestly claim.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONSTARTUP", None)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _decode(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
