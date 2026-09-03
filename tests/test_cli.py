"""The CLI. Its one real decision is the exit code, and ERROR must not read as FAIL."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner, Result

from decidable.cli import app

runner = CliRunner()


def output_of(result: Result) -> str:
    """What the command said, with no regard for where the terminal broke a line.

    Rich wraps to the console width, so a substring assertion against raw output
    silently depends on how long a temp path happened to be. That made a positive
    assertion fail in CI, and worse, it could have let a negative one such as
    ``"by stage" not in output`` pass while a report was printed.
    """
    return " ".join(result.output.split())


SUITE = """
name: demo
verifiers:
  - parse
tasks:
  - id: alpha
    prompt: write alpha
  - id: beta
    prompt: write beta
"""

AGENT = '''\
"""A canned agent for the CLI tests."""

ANSWERS = {"alpha": "x = 1\\n", "beta": "y = 2\\n"}


def agent(task):
    return ANSWERS[task.id]
'''


def write_suite(root: Path, document: str = SUITE) -> Path:
    path = root / "suite.yaml"
    path.write_text(document, encoding="utf-8")
    return path


def write_artifacts(root: Path, **files: str) -> Path:
    directory = root / "artifacts"
    directory.mkdir(exist_ok=True)
    for name, body in files.items():
        (directory / f"{name}.py").write_text(body, encoding="utf-8")
    return directory


def test_a_passing_run_exits_zero(tmp_path: Path) -> None:
    suite = write_suite(tmp_path)
    artifacts = write_artifacts(tmp_path, alpha="x = 1\n", beta="y = 2\n")

    result = runner.invoke(app, ["run", str(suite), "--artifacts", str(artifacts)])

    assert result.exit_code == 0
    assert "2 tasks" in output_of(result)


def test_a_failing_run_exits_one(tmp_path: Path) -> None:
    suite = write_suite(tmp_path)
    artifacts = write_artifacts(tmp_path, alpha="x = 1\n", beta="def broken(:\n")

    result = runner.invoke(app, ["run", str(suite), "--artifacts", str(artifacts)])

    assert result.exit_code == 1
    assert "beta" in output_of(result)


def test_a_missing_artifact_errors_rather_than_fails(tmp_path: Path) -> None:
    """Nothing was produced, so nothing was decided. That is an ERROR, exit 2.

    The evidence is asserted against the JSON rather than the terminal table,
    because a narrow terminal legitimately elides a long cell. Rendering is for
    people and is allowed to abbreviate; JSON is the surface that must not.
    """
    suite = write_suite(tmp_path)
    artifacts = write_artifacts(tmp_path, alpha="x = 1\n")
    destination = tmp_path / "report.json"

    result = runner.invoke(
        app,
        ["run", str(suite), "--artifacts", str(artifacts), "--json", str(destination)],
    )

    assert result.exit_code == 2
    assert "beta" in output_of(result)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    beta = payload["results"][1]
    assert beta["task_id"] == "beta"
    assert beta["error"]["exception_type"] == "FileNotFoundError"
    assert beta["verdicts"] == []
    assert beta["artifact_digest"] is None
    assert payload["summary"]["errored"] == 1
    assert payload["summary"]["failed"] == 0


def test_an_agent_by_file_path(tmp_path: Path) -> None:
    suite = write_suite(tmp_path)
    (tmp_path / "canned.py").write_text(AGENT, encoding="utf-8")

    result = runner.invoke(
        app, ["run", str(suite), "--agent", f"{tmp_path / 'canned.py'}:agent"]
    )

    assert result.exit_code == 0


def test_an_agent_by_dotted_path(tmp_path: Path) -> None:
    (tmp_path / "canned_agent.py").write_text(AGENT, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        result = runner.invoke(
            app, ["run", str(write_suite(tmp_path)), "--agent", "canned_agent:agent"]
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("canned_agent", None)

    assert result.exit_code == 0


def test_neither_agent_nor_artifacts_is_a_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(write_suite(tmp_path))])

    assert result.exit_code == 2
    assert "exactly one" in output_of(result)


def test_both_agent_and_artifacts_is_a_usage_error(tmp_path: Path) -> None:
    suite = write_suite(tmp_path)
    artifacts = write_artifacts(tmp_path, alpha="x = 1\n", beta="y = 2\n")
    (tmp_path / "canned.py").write_text(AGENT, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            str(suite),
            "--artifacts",
            str(artifacts),
            "--agent",
            f"{tmp_path / 'canned.py'}:agent",
        ],
    )

    assert result.exit_code == 2
    assert "exactly one" in output_of(result)


def test_an_unresolvable_agent_exits_two_without_running(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["run", str(write_suite(tmp_path)), "--agent", "no.such.module:agent"]
    )

    assert result.exit_code == 2
    assert "cannot import" in output_of(result)
    assert "2 tasks" not in output_of(result)


def test_a_malformed_agent_spec_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["run", str(write_suite(tmp_path)), "--agent", "nocolon"]
    )

    assert result.exit_code == 2
    assert "module:callable" in output_of(result)


def test_a_malformed_suite_exits_two_with_no_report(tmp_path: Path) -> None:
    suite = write_suite(tmp_path, "name: demo\nverifiers:\n  - pyright\ntasks: []\n")
    artifacts = write_artifacts(tmp_path, alpha="x = 1\n")

    result = runner.invoke(app, ["run", str(suite), "--artifacts", str(artifacts)])

    assert result.exit_code == 2
    assert "no verifier named 'pyright'" in output_of(result)
    assert "by stage" not in output_of(result)


def test_a_diagnostic_is_not_broken_across_lines(tmp_path: Path) -> None:
    """An error nobody can grep for is most of an error wasted.

    Forty columns is narrower than any real terminal, and narrower than the
    width at which CI first wrapped this message mid-sentence.
    """
    suite = write_suite(tmp_path, "name: demo\nverifiers:\n  - pyright\ntasks: []\n")
    artifacts = write_artifacts(tmp_path, alpha="x = 1\n")

    result = runner.invoke(
        app,
        ["run", str(suite), "--artifacts", str(artifacts)],
        env={"COLUMNS": "40"},
    )

    assert result.exit_code == 2
    assert "no verifier named 'pyright'" in result.output


def test_json_output_carries_the_breakdown(tmp_path: Path) -> None:
    suite = write_suite(tmp_path)
    artifacts = write_artifacts(tmp_path, alpha="x = 1\n", beta="def broken(:\n")
    destination = tmp_path / "report.json"

    result = runner.invoke(
        app,
        [
            "run",
            str(suite),
            "--artifacts",
            str(artifacts),
            "--json",
            str(destination),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["summary"]["failed"] == 1
    assert payload["breakdown"][0]["stage"] == "syntactic"
    assert [r["task_id"] for r in payload["results"]] == ["alpha", "beta"]


def test_quiet_suppresses_the_report_but_not_the_exit_code(tmp_path: Path) -> None:
    suite = write_suite(tmp_path)
    artifacts = write_artifacts(tmp_path, alpha="x = 1\n", beta="def broken(:\n")

    result = runner.invoke(
        app, ["run", str(suite), "--artifacts", str(artifacts), "--quiet"]
    )

    assert result.exit_code == 1
    assert "by stage" not in output_of(result)


def test_the_cache_is_used_when_asked_for(tmp_path: Path) -> None:
    suite = write_suite(tmp_path)
    artifacts = write_artifacts(tmp_path, alpha="x = 1\n", beta="y = 2\n")
    cache = tmp_path / "cache"

    for _ in range(2):
        result = runner.invoke(
            app,
            [
                "run",
                str(suite),
                "--artifacts",
                str(artifacts),
                "--cache-dir",
                str(cache),
            ],
        )
        assert result.exit_code == 0

    assert list(cache.glob("*.json"))
