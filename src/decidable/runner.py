"""Executing a suite against an agent, and remembering what was already decided.

Two things here are more than a loop. The first is that an agent which fails is
recorded as a harness condition and never as a failing agent: no artifact was
produced, so nothing about the agent was decided. The second is caching, which
is only honest if the key covers everything that could change a verdict — hence
:attr:`decidable.verifiers.Verifier.fingerprint`.
"""

from __future__ import annotations

import platform
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from decidable import __version__
from decidable._digest import digest
from decidable.models import (
    Agent,
    HarnessError,
    Report,
    RunMetadata,
    Suite,
    Task,
    TaskResult,
)
from decidable.verifiers.base import StackResult, VerifierStack

StackFor = Callable[[Task], VerifierStack]


def run(
    suite: Suite,
    agent: Agent,
    *,
    stack_for: StackFor,
    agent_name: str | None = None,
    cache_dir: Path | None = None,
) -> Report:
    """Run every task in the suite against the agent and report what happened.

    ``stack_for`` builds the verifier stack for a task. It is a callable rather
    than a field on :class:`~decidable.models.Task` so that a task stays pure
    data while its property tests can still differ from every other task's.

    ``cache_dir`` is opt-in. Given one, a task whose artifact and verifier
    fingerprints match a previous run reuses that run's verdicts; given
    ``None``, nothing is read or written and every task is verified afresh.
    """
    started_at = datetime.now(UTC)
    cache = _Cache(cache_dir)
    results = tuple(_run_task(task, agent, stack_for, cache) for task in suite.tasks)
    return Report(
        metadata=RunMetadata(
            decidable_version=__version__,
            python_version=platform.python_version(),
            platform=sys.platform,
            suite_name=suite.name,
            agent_name=agent_name or _name_of(agent),
            started_at=started_at,
            finished_at=datetime.now(UTC),
            cache_dir=str(cache_dir) if cache_dir is not None else None,
            cache_hits=cache.hits,
        ),
        results=results,
    )


def _run_task(
    task: Task, agent: Agent, stack_for: StackFor, cache: _Cache
) -> TaskResult:
    try:
        artifact = agent(task)
        stack = stack_for(task)
    except Exception as exc:  # noqa: BLE001 - see below; the breadth is the point
        # The agent or the caller's own stack factory broke. That decides
        # nothing about the agent's output, and the rest of the suite still
        # deserves to run, so it is recorded rather than raised.
        return TaskResult(task_id=task.id, error=_harness_error(exc))

    artifact_digest = digest(artifact)
    fingerprints = tuple(v.fingerprint for v in stack.verifiers)
    key = _cache_key(artifact_digest, fingerprints)

    result = cache.get(key)
    if result is None:
        result = stack.run(artifact)
        cache.put(key, artifact_digest, fingerprints, result)

    return TaskResult(
        task_id=task.id,
        artifact_digest=artifact_digest,
        verdicts=result.verdicts,
        skipped=result.skipped,
    )


def _cache_key(artifact_digest: str, fingerprints: tuple[str, ...]) -> str:
    """What must match for a previous run's verdicts to still be true.

    The decidable version is in here because a verdict is only as reusable as
    the schema it was written in.
    """
    return digest("\n".join((__version__, artifact_digest, *fingerprints)))


class _CacheEntry(BaseModel):
    """A cached stack result, alongside the key's inputs for hand inspection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decidable_version: str
    artifact_digest: str
    fingerprints: tuple[str, ...]
    result: StackResult


class _Cache:
    """Verdicts remembered on disk. Never able to change one.

    Every failure mode here — no directory, unreadable file, corrupt JSON, a
    schema that no longer validates — is a miss. A cache is an optimisation, and
    an optimisation that can turn a PASS into an ERROR is a bug.
    """

    def __init__(self, directory: Path | None) -> None:
        self._directory = directory
        self.hits = 0

    def get(self, key: str) -> StackResult | None:
        if self._directory is None:
            return None
        try:
            entry = _CacheEntry.model_validate_json(
                (self._directory / f"{key}.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ValidationError):
            return None
        self.hits += 1
        return entry.result

    def put(
        self,
        key: str,
        artifact_digest: str,
        fingerprints: tuple[str, ...],
        result: StackResult,
    ) -> None:
        if self._directory is None:
            return
        entry = _CacheEntry(
            decidable_version=__version__,
            artifact_digest=artifact_digest,
            fingerprints=fingerprints,
            result=result,
        )
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            (self._directory / f"{key}.json").write_text(
                entry.model_dump_json(indent=2), encoding="utf-8"
            )
        except OSError:
            # An unwritable cache slows the next run down. It must not fail this one.
            return


def _harness_error(exc: Exception) -> HarnessError:
    return HarnessError(
        exception_type=type(exc).__name__,
        message=str(exc),
        traceback="".join(traceback.format_exception(exc)),
    )


def _name_of(agent: Agent) -> str:
    """A readable name for a plain function, a lambda, or a callable object."""
    return getattr(agent, "__name__", None) or type(agent).__name__
