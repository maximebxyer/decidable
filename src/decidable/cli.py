"""`decidable run` — the command line over the library.

It adds no formatting and no logic of its own: it loads a suite, resolves an
agent, calls :func:`decidable.runner.run`, and renders through
:mod:`decidable.report`. The one thing it decides is the exit code, and it
decides it the way everything else in this project resolves a status — `ERROR`
dominates `FAIL` dominates `PASS` — so a CI job can tell "the agent got worse"
from "the harness broke" without parsing a word of output.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Annotated

import typer
from rich.console import Console

from decidable.models import Agent, Artifact, Report, Task
from decidable.report import render_json, render_terminal, summarise
from decidable.runner import run as run_suite
from decidable.suite_file import SuiteFileError, load

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ERRORED = 2

app = typer.Typer(
    add_completion=False,
    help="Evaluate agents whose outputs can be verified by execution.",
)


@app.callback()
def main() -> None:
    """Keeps `run` a subcommand: typer would otherwise collapse a lone command
    into the root, and `decidable run suite.yaml` would read `run` as the suite.
    """


@app.command()
def run(
    suite_path: Annotated[
        Path,
        typer.Argument(
            metavar="SUITE",
            exists=True,
            dir_okay=False,
            help="A YAML suite file.",
        ),
    ],
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            metavar="SPEC",
            help="The agent to evaluate, as module:callable or path/to/file.py:callable.",
        ),
    ] = None,
    artifacts: Annotated[
        Path | None,
        typer.Option(
            "--artifacts",
            exists=True,
            file_okay=False,
            help="A directory of already-generated artifacts, named <task id>.py.",
        ),
    ] = None,
    cache_dir: Annotated[
        Path | None,
        typer.Option(
            "--cache-dir",
            help="Reuse verdicts for unchanged artifacts and verifiers. Off by default.",
        ),
    ] = None,
    json_path: Annotated[
        Path | None,
        typer.Option("--json", metavar="PATH", help="Also write the report as JSON."),
    ] = None,
    quiet: Annotated[
        bool, typer.Option("--quiet", help="Suppress the terminal report.")
    ] = False,
) -> None:
    """Run a suite against an agent and report where it broke.

    Exits 0 if every task passed, 1 if any failed, and 2 if any errored — an
    error being the harness failing rather than the agent.
    """
    console = Console(stderr=True)

    if (agent is None) == (artifacts is None):
        _complain(console, "Give exactly one of --agent or --artifacts.")
        raise typer.Exit(EXIT_ERRORED)

    try:
        loaded = load(suite_path)
        callable_agent, agent_name = (
            _artifacts_agent(artifacts)
            if artifacts is not None
            else _import_agent(str(agent))
        )
    except SuiteFileError as exc:
        _complain(console, str(exc))
        raise typer.Exit(EXIT_ERRORED) from exc

    report = run_suite(
        loaded.suite,
        callable_agent,
        stack_for=loaded.stack_for,
        agent_name=agent_name,
        cache_dir=cache_dir,
    )

    if not quiet:
        render_terminal(report)
    if json_path is not None:
        json_path.write_text(render_json(report), encoding="utf-8")

    raise typer.Exit(exit_code(report))


def _complain(console: Console, message: str) -> None:
    """Print a diagnostic that survives being read by a machine.

    ``soft_wrap`` keeps it on one line: wrapping a table for a human is right,
    but breaking an error message in the middle means nobody can grep a CI log
    for it. ``markup=False`` because these messages interpolate file paths and
    YAML keys, and a path containing a bracket would otherwise be parsed as rich
    markup and mangled.
    """
    console.print(message, style="red", markup=False, soft_wrap=True)


def exit_code(report: Report) -> int:
    """``ERROR`` dominates ``FAIL`` dominates ``PASS``, as everywhere else."""
    summary = summarise(report)
    if summary.errored:
        return EXIT_ERRORED
    if summary.failed:
        return EXIT_FAILED
    return EXIT_OK


def _artifacts_agent(directory: Path) -> tuple[Agent, str]:
    """Read artifacts someone already generated.

    This is an agent like any other, which is the point: a missing file raises,
    and the runner turns that into an ERROR on that task. Nothing was produced,
    so nothing about the agent was decided — that is not a FAIL.
    """

    def from_directory(task: Task) -> Artifact:
        return (directory / f"{task.id}.py").read_text(encoding="utf-8")

    return from_directory, f"artifacts:{directory}"


def _import_agent(spec: str) -> tuple[Agent, str]:
    """Resolve `module:callable` or `path/to/file.py:callable`."""
    module_part, separator, attribute = spec.rpartition(":")
    if not separator or not module_part or not attribute:
        msg = f"--agent must look like module:callable or path/to/file.py:callable, not {spec!r}"
        raise SuiteFileError(msg)

    module = (
        _module_from_file(Path(module_part))
        if module_part.endswith(".py")
        else _module_from_name(module_part)
    )

    resolved = getattr(module, attribute, None)
    if resolved is None:
        msg = f"{module_part} has no attribute {attribute!r}"
        raise SuiteFileError(msg)
    if not callable(resolved):
        msg = f"{spec} is not callable"
        raise SuiteFileError(msg)
    return resolved, spec


def _module_from_name(name: str) -> ModuleType:
    # The working directory goes on the path so a checkout's own modules resolve,
    # as pytest and uvicorn do.
    if sys.path and sys.path[0] != "":
        sys.path.insert(0, "")
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        msg = f"cannot import {name}: {exc}"
        raise SuiteFileError(msg) from exc


def _module_from_file(path: Path) -> ModuleType:
    if not path.is_file():
        msg = f"no such file: {path}"
        raise SuiteFileError(msg)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        msg = f"cannot load a module from {path}"
        raise SuiteFileError(msg)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        msg = f"{path} raised while being imported: {exc}"
        raise SuiteFileError(msg) from exc
    return module
