"""The core vocabulary of the harness: Task, Agent, Verdict, Report.

Two invariants are enforced here rather than left to convention:

- ``ERROR`` is never ``FAIL``. A verdict carries a :class:`HarnessError` if and
  only if its status is ``ERROR``, so harness breakage cannot be mistaken for
  agent failure by anything downstream.
- Every verdict carries evidence, and every piece of evidence carries a non-empty
  one-line summary. A bare boolean is a bug.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Protocol, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

Artifact: TypeAlias = str
"""What an agent produces. v0.1 verifies generated Python source, so: text."""

EvidenceScalar: TypeAlias = str | int | float | bool | None
EvidenceValue: TypeAlias = EvidenceScalar | tuple[EvidenceScalar, ...]
"""Values admissible in structured evidence: JSON scalars and flat tuples of them.

Deliberately not recursive. Structured evidence exists to be aggregated across a
run — counting mypy error codes, say — and nested blobs do not aggregate. Long
unstructured output belongs in ``Evidence.detail``.
"""

Summary: TypeAlias = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]


class Status(str, Enum):
    """The three-way outcome of a verification. There is no fourth value.

    ``ERROR`` means the verifier itself could not run. It is never folded into
    ``FAIL``, and "not reached" is represented by absence, not by a status.
    """

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


class Stage(str, Enum):
    """Verifier cost tiers, cheap to expensive. The order is the failure taxonomy."""

    SYNTACTIC = "syntactic"
    STATIC = "static"
    DYNAMIC = "dynamic"
    BEHAVIOURAL = "behavioural"

    @property
    def rank(self) -> int:
        """Position in declaration order. Used to validate that a stack is ordered."""
        return list(Stage).index(self)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Evidence(_Frozen):
    """Why a verdict is what it is. Never optional on a verdict.

    ``summary`` is the line the failure taxonomy prints. ``detail`` is whatever is
    needed to reproduce and understand the verdict: a traceback, a diff, a failing
    assertion. ``data`` holds whatever is structured enough to aggregate, and its
    shape is the business of each family of verifiers — a parse verifier records a
    source position, a subprocess verifier records an exit code.
    """

    summary: Summary
    detail: str | None = None
    data: Mapping[str, EvidenceValue] = {}


class HarnessError(_Frozen):
    """The harness broke. Present only on ``ERROR`` verdicts, never agent evidence."""

    exception_type: str
    message: str
    traceback: str


class VerifierRef(_Frozen):
    """A verifier's identity, carried into reports without holding the object.

    ``fingerprint`` records *which configuration* decided, not merely which
    verifier: the tool version, the settings, the property tests. A report whose
    verdicts do not say that cannot be re-derived, and a cache keyed without it
    would happily serve a verdict from a different mypy.
    """

    name: str
    stage: Stage
    fingerprint: str


class Verdict(_Frozen):
    """The result of running one verifier against one artifact."""

    status: Status
    verifier: VerifierRef
    evidence: Evidence
    error: HarnessError | None = None
    duration_s: float | None = None
    """Wall-clock time, stamped by the stack that ran the verifier."""

    @property
    def is_pass(self) -> bool:
        """True only for ``PASS``. Nothing else about a verdict is truthy."""
        return self.status is Status.PASS

    @model_validator(mode="after")
    def _error_iff_error_status(self) -> Self:
        if self.status is Status.ERROR and self.error is None:
            msg = "an ERROR verdict must carry a HarnessError"
            raise ValueError(msg)
        if self.status is not Status.ERROR and self.error is not None:
            msg = f"a {self.status.value.upper()} verdict must not carry a HarnessError"
            raise ValueError(msg)
        return self


def roll_up(verdicts: Sequence[Verdict]) -> Status:
    """Reduce verdicts to one status. ``ERROR`` dominates ``FAIL`` dominates ``PASS``.

    An empty sequence is ``ERROR``: nothing was decided, which is a harness
    condition and never an agent failure.
    """
    if not verdicts:
        return Status.ERROR
    if any(v.status is Status.ERROR for v in verdicts):
        return Status.ERROR
    if any(v.status is Status.FAIL for v in verdicts):
        return Status.FAIL
    return Status.PASS


class Task(_Frozen):
    """A single evaluation unit.

    Pure data. Verifiers are paired with a task by the caller running it, which
    keeps a task serializable and keeps this module free of a dependency on
    :mod:`decidable.verifiers.base`.
    """

    id: str
    prompt: str
    context: str | None = None
    fixtures: tuple[Path, ...] = ()


class Suite(_Frozen):
    """A set of tasks.

    Verifiers are not held here. The caller running a suite supplies a factory
    that builds a stack for each task, which is what lets property tests differ
    per task while keeping a suite pure data.
    """

    name: str
    tasks: tuple[Task, ...]

    @model_validator(mode="after")
    def _task_ids_are_unique(self) -> Self:
        ids = [task.id for task in self.tasks]
        duplicates = sorted({id_ for id_ in ids if ids.count(id_) > 1})
        if duplicates:
            msg = f"task ids must be unique; repeated: {', '.join(duplicates)}"
            raise ValueError(msg)
        return self


class Agent(Protocol):
    """Anything callable that maps a task to an artifact. User-supplied.

    No ``name`` attribute is required, so a plain function satisfies this. The
    agent's name is recorded in :class:`RunMetadata` by whoever runs it.
    """

    def __call__(self, task: Task, /) -> Artifact: ...


class TaskResult(_Frozen):
    """One task's verdicts, plus the verifiers that short-circuiting never reached."""

    task_id: str
    artifact_digest: str | None = None
    """sha256 of the artifact. ``None`` only when the agent produced none."""

    verdicts: tuple[Verdict, ...] = ()
    skipped: tuple[VerifierRef, ...] = ()
    error: HarnessError | None = None
    """Set when the *agent* failed, so there was never an artifact to verify."""

    @property
    def status(self) -> Status:
        """``ERROR`` when the agent failed: ``roll_up`` of no verdicts decides nothing."""
        return roll_up(self.verdicts)

    @model_validator(mode="after")
    def _an_agent_failure_has_no_artifact(self) -> Self:
        if self.error is not None and (self.verdicts or self.artifact_digest):
            msg = "an agent failure means no artifact was produced, so nothing was verified"
            raise ValueError(msg)
        if self.error is None and self.artifact_digest is None:
            msg = "a result without an agent failure must record its artifact digest"
            raise ValueError(msg)
        return self


class RunMetadata(_Frozen):
    """Enough about a run to re-derive it."""

    decidable_version: str
    python_version: str
    platform: str
    suite_name: str
    agent_name: str
    started_at: datetime
    finished_at: datetime
    cache_dir: str | None = None
    cache_hits: int = 0


class Report(_Frozen):
    """A suite executed against one agent."""

    metadata: RunMetadata
    results: tuple[TaskResult, ...]
