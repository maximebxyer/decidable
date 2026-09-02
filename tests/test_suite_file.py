"""Loading a suite from YAML. A malformed suite fails here, never as ERROR verdicts."""

from __future__ import annotations

from pathlib import Path

import pytest

from decidable.models import Stage
from decidable.suite_file import SuiteFileError, load

SUITE = """
name: demo
verifiers:
  - parse
  - mypy:
      strict: false
  - ruff
  - execute:
      timeout_s: 5
  - pytest
tasks:
  - id: alpha
    prompt: write alpha
    tests: tests/alpha.py
  - id: beta
    prompt: write beta
    context: some extra material
    tests: tests/beta.py
"""


def write_suite(root: Path, document: str = SUITE, **tests: str) -> Path:
    (root / "tests").mkdir(exist_ok=True)
    for name, body in (
        tests or {"alpha": "def test_a(): pass", "beta": "def test_b(): pass"}
    ).items():
        (root / "tests" / f"{name}.py").write_text(body, encoding="utf-8")
    path = root / "suite.yaml"
    path.write_text(document, encoding="utf-8")
    return path


def test_a_suite_loads_with_its_tasks_and_stack(tmp_path: Path) -> None:
    loaded = load(write_suite(tmp_path))

    assert loaded.suite.name == "demo"
    assert [t.id for t in loaded.suite.tasks] == ["alpha", "beta"]
    assert loaded.suite.tasks[1].context == "some extra material"

    stack = loaded.stack_for(loaded.suite.tasks[0])
    assert [v.name for v in stack.verifiers] == [
        "python_parse",
        "mypy",
        "ruff",
        "python_execute",
        "pytest",
    ]
    assert [v.stage for v in stack.verifiers] == [
        Stage.SYNTACTIC,
        Stage.STATIC,
        Stage.STATIC,
        Stage.DYNAMIC,
        Stage.BEHAVIOURAL,
    ]


def test_options_reach_the_verifier(tmp_path: Path) -> None:
    loaded = load(write_suite(tmp_path))
    stack = loaded.stack_for(loaded.suite.tasks[0])

    assert "strict=False" in stack.verifiers[1].fingerprint
    assert "timeout=5.0" in stack.verifiers[3].fingerprint


def test_each_task_gets_its_own_property_tests(tmp_path: Path) -> None:
    """Different tests must mean different fingerprints, or the cache would collide."""
    path = write_suite(
        tmp_path,
        alpha="def test_a():\n    assert True",
        beta="def test_b():\n    assert False",
    )
    loaded = load(path)

    alpha, beta = (loaded.stack_for(t).verifiers[-1] for t in loaded.suite.tasks)
    assert alpha.fingerprint != beta.fingerprint


def test_an_unknown_verifier_names_the_built_ins(tmp_path: Path) -> None:
    document = SUITE.replace("  - ruff\n", "  - pyright\n")

    with pytest.raises(SuiteFileError, match="no verifier named 'pyright'") as caught:
        load(write_suite(tmp_path, document))

    assert "parse, mypy, ruff, execute, pytest" in str(caught.value)
    assert "Python" in str(caught.value)


def test_an_unknown_option_is_named(tmp_path: Path) -> None:
    document = SUITE.replace("      strict: false", "      strictt: false")

    with pytest.raises(SuiteFileError, match="strictt"):
        load(write_suite(tmp_path, document))


def test_an_ill_typed_option_is_refused(tmp_path: Path) -> None:
    document = SUITE.replace("      timeout_s: 5", "      timeout_s: soon")

    with pytest.raises(SuiteFileError, match="timeout_s"):
        load(write_suite(tmp_path, document))


def test_pytest_without_tests_is_a_load_error(tmp_path: Path) -> None:
    document = SUITE.replace("    tests: tests/beta.py\n", "")

    with pytest.raises(SuiteFileError, match="needs a 'tests' path"):
        load(write_suite(tmp_path, document))


def test_tests_that_do_not_exist_are_a_load_error(tmp_path: Path) -> None:
    document = SUITE.replace("tests/beta.py", "tests/missing.py")

    with pytest.raises(SuiteFileError, match="cannot be read"):
        load(write_suite(tmp_path, document))


def test_paths_resolve_against_the_suite_file(tmp_path: Path) -> None:
    """Not against the working directory, which the CLI has no control over."""
    nested = tmp_path / "suites"
    nested.mkdir()
    path = write_suite(nested)

    loaded = load(path)

    assert (
        loaded.suite.tasks[0].fixtures[0] == (nested / "tests" / "alpha.py").resolve()
    )


def test_verifiers_out_of_stage_order_are_refused(tmp_path: Path) -> None:
    document = """
name: demo
verifiers:
  - execute
  - parse
tasks:
  - id: alpha
    prompt: write alpha
"""

    with pytest.raises(SuiteFileError, match="cheap to expensive"):
        load(write_suite(tmp_path, document))


def test_a_suite_with_no_tasks_is_refused(tmp_path: Path) -> None:
    """An empty suite would exit 0 having decided nothing."""
    document = "name: demo\nverifiers:\n  - parse\ntasks: []\n"

    with pytest.raises(SuiteFileError, match="at least one task"):
        load(write_suite(tmp_path, document))


def test_duplicate_task_ids_are_refused(tmp_path: Path) -> None:
    document = """
name: demo
verifiers:
  - parse
tasks:
  - id: alpha
    prompt: one
  - id: alpha
    prompt: two
"""

    with pytest.raises(SuiteFileError, match="unique"):
        load(write_suite(tmp_path, document))


def test_an_unknown_task_key_is_refused(tmp_path: Path) -> None:
    document = """
name: demo
verifiers:
  - parse
tasks:
  - id: alpha
    prompt: one
    temperature: 0.7
"""

    with pytest.raises(SuiteFileError, match="temperature"):
        load(write_suite(tmp_path, document))


def test_malformed_yaml_says_so(tmp_path: Path) -> None:
    with pytest.raises(SuiteFileError, match="not valid YAML"):
        load(write_suite(tmp_path, "name: [demo\n"))


def test_a_missing_file_says_so(tmp_path: Path) -> None:
    with pytest.raises(SuiteFileError, match="cannot read suite file"):
        load(tmp_path / "nope.yaml")
