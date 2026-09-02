"""Reading a suite from YAML.

Naming verifiers in a file means a registry, and a registry is the closest this
project comes to a plugin system. So this one knows **only the five shipped
verifiers**: a suite file cannot name user code, which means it cannot import or
execute any. The :class:`~decidable.verifiers.Verifier` protocol was always the
extension point for custom verifiers, and it still is — write one in Python.

Everything a malformed suite could get wrong is caught here, at load, rather than
surfacing later as a run full of ERROR verdicts. A broken configuration is not a
result about an agent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from decidable.models import Suite, Task
from decidable.verifiers.base import Verifier, VerifierStack
from decidable.verifiers.python import (
    ExecuteVerifier,
    MypyVerifier,
    ParseVerifier,
    PytestVerifier,
    RuffVerifier,
)

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class SuiteFileError(ValueError):
    """A suite file that cannot be loaded. Always raised before anything runs."""


@dataclass(frozen=True, slots=True)
class LoadedSuite:
    """A suite and how to verify it: exactly the pair :func:`decidable.runner.run` needs."""

    suite: Suite
    stack_for: Callable[[Task], VerifierStack]


class ParseOptions(BaseModel):
    model_config = _FROZEN


class MypyOptions(BaseModel):
    model_config = _FROZEN

    strict: bool = True
    timeout_s: float = 120.0


class RuffOptions(BaseModel):
    model_config = _FROZEN

    timeout_s: float = 60.0


class ExecuteOptions(BaseModel):
    model_config = _FROZEN

    timeout_s: float = 10.0


class PytestOptions(BaseModel):
    model_config = _FROZEN

    module_name: str = "solution"
    timeout_s: float = 60.0


BUILT_INS = ("parse", "mypy", "ruff", "execute", "pytest")
"""Every verifier a suite file may name. Anything else is an error."""


def load(path: Path) -> LoadedSuite:
    """Read a suite file, or explain exactly why it cannot be read."""
    document = _read_yaml(path)
    name = _require_str(document, "name", path)
    specs = _verifier_specs(document, path)
    tasks = _tasks(document, path, needs_tests="pytest" in {n for n, _ in specs})

    stacks = {
        task.id: _stack(specs, tests=_tests_for(task, path)) for task in tasks.values()
    }
    return LoadedSuite(
        suite=Suite(name=name, tasks=tuple(tasks.values())),
        stack_for=lambda task: stacks[task.id],
    )


def _read_yaml(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read suite file {path}: {exc}"
        raise SuiteFileError(msg) from exc
    try:
        document = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        msg = f"{path} is not valid YAML: {exc}"
        raise SuiteFileError(msg) from exc
    if not isinstance(document, dict):
        msg = f"{path} must contain a mapping with keys name, verifiers and tasks"
        raise SuiteFileError(msg)
    return document


def _require_str(document: Mapping[str, Any], key: str, path: Path) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{path}: '{key}' is required and must be a non-empty string"
        raise SuiteFileError(msg)
    return value


def _verifier_specs(
    document: Mapping[str, Any], path: Path
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    """Normalise `- parse` and `- mypy: {strict: true}` into (name, options) pairs."""
    entries = document.get("verifiers")
    if not isinstance(entries, list) or not entries:
        msg = f"{path}: 'verifiers' is required and must be a non-empty list"
        raise SuiteFileError(msg)

    specs: list[tuple[str, Mapping[str, Any]]] = []
    for entry in entries:
        if isinstance(entry, str):
            specs.append((_known(entry, path), {}))
        elif isinstance(entry, dict) and len(entry) == 1:
            [(name, options)] = entry.items()
            if options is None:
                options = {}
            if not isinstance(name, str) or not isinstance(options, dict):
                msg = f"{path}: a verifier entry must be 'name' or 'name: {{options}}'"
                raise SuiteFileError(msg)
            specs.append((_known(name, path), options))
        else:
            msg = (
                f"{path}: a verifier entry must be a name or a single-key mapping of "
                f"name to options, not {entry!r}"
            )
            raise SuiteFileError(msg)
    return tuple(specs)


def _known(name: str, path: Path) -> str:
    if name not in BUILT_INS:
        msg = (
            f"{path}: no verifier named {name!r}. A suite file can name only the "
            f"built-ins: {', '.join(BUILT_INS)}. For your own verifier, compose a "
            f"VerifierStack in Python and call decidable.runner.run directly."
        )
        raise SuiteFileError(msg)
    return name


def _tasks(
    document: Mapping[str, Any], path: Path, *, needs_tests: bool
) -> dict[str, Task]:
    entries = document.get("tasks")
    if not isinstance(entries, list) or not entries:
        msg = (
            f"{path}: 'tasks' is required and must list at least one task. "
            f"An empty suite would report success without deciding anything."
        )
        raise SuiteFileError(msg)

    tasks: dict[str, Task] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            msg = f"{path}: each task must be a mapping, not {entry!r}"
            raise SuiteFileError(msg)
        task_id = _require_str(entry, "id", path)
        prompt = _require_str(entry, "prompt", path)
        tests = entry.get("tests")

        if needs_tests and not isinstance(tests, str):
            msg = (
                f"{path}: task {task_id!r} needs a 'tests' path because the suite's "
                f"verifiers include pytest"
            )
            raise SuiteFileError(msg)
        if tests is not None and not isinstance(tests, str):
            msg = f"{path}: task {task_id!r} has a 'tests' that is not a path"
            raise SuiteFileError(msg)

        unknown = set(entry) - {"id", "prompt", "context", "tests"}
        if unknown:
            msg = f"{path}: task {task_id!r} has unknown keys: {', '.join(sorted(unknown))}"
            raise SuiteFileError(msg)

        tasks[task_id] = Task(
            id=task_id,
            prompt=prompt,
            context=entry.get("context"),
            fixtures=(_resolve(tests, path),) if tests else (),
        )

    try:
        Suite(name="validation", tasks=tuple(tasks.values()))
    except ValidationError as exc:
        raise SuiteFileError(f"{path}: {exc}") from exc
    if len(tasks) != len(entries):
        msg = f"{path}: task ids must be unique"
        raise SuiteFileError(msg)
    return tasks


def _resolve(tests: str, path: Path) -> Path:
    """Relative to the suite file, not to wherever the command was run from."""
    return (path.parent / tests).resolve()


def _tests_for(task: Task, path: Path) -> str | None:
    if not task.fixtures:
        return None
    tests_path = task.fixtures[0]
    try:
        return tests_path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"{path}: task {task.id!r} points at tests that cannot be read: {exc}"
        raise SuiteFileError(msg) from exc


def _stack(
    specs: tuple[tuple[str, Mapping[str, Any]], ...], *, tests: str | None
) -> VerifierStack:
    verifiers = [_build(name, options, tests) for name, options in specs]
    try:
        return VerifierStack(verifiers)
    except ValueError as exc:
        raise SuiteFileError(str(exc)) from exc


def _build(name: str, options: Mapping[str, Any], tests: str | None) -> Verifier:
    try:
        return _CONSTRUCTORS[name](options, tests)
    except ValidationError as exc:
        msg = f"{name}: {exc}"
        raise SuiteFileError(msg) from exc


def _parse(options: Mapping[str, Any], _tests: str | None) -> Verifier:
    ParseOptions.model_validate(options)
    return ParseVerifier()


def _mypy(options: Mapping[str, Any], _tests: str | None) -> Verifier:
    settings = MypyOptions.model_validate(options)
    return MypyVerifier(strict=settings.strict, timeout_s=settings.timeout_s)


def _ruff(options: Mapping[str, Any], _tests: str | None) -> Verifier:
    settings = RuffOptions.model_validate(options)
    return RuffVerifier(timeout_s=settings.timeout_s)


def _execute(options: Mapping[str, Any], _tests: str | None) -> Verifier:
    settings = ExecuteOptions.model_validate(options)
    return ExecuteVerifier(timeout_s=settings.timeout_s)


def _pytest(options: Mapping[str, Any], tests: str | None) -> Verifier:
    settings = PytestOptions.model_validate(options)
    if tests is None:
        msg = "pytest needs a task's tests, which should have been required at load"
        raise SuiteFileError(msg)
    return PytestVerifier(
        tests,
        module_name=settings.module_name,
        timeout_s=settings.timeout_s,
    )


_CONSTRUCTORS: Mapping[str, Callable[[Mapping[str, Any], str | None], Verifier]] = {
    "parse": _parse,
    "mypy": _mypy,
    "ruff": _ruff,
    "execute": _execute,
    "pytest": _pytest,
}
