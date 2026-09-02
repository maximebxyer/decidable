"""The README claims code runs. Verify that by execution, like everything else.

Every ```python block in README.md is executed here. Snippets that are meant to
be illustrative rather than runnable use a different fence language.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"

_BLOCK = re.compile(r"^```python\n(.*?)^```", re.DOTALL | re.MULTILINE)


def python_blocks() -> list[str]:
    return _BLOCK.findall(README.read_text(encoding="utf-8"))


def test_the_readme_still_has_python_examples() -> None:
    """Guards against this file quietly passing over a README that lost its examples."""
    assert python_blocks()


@pytest.mark.parametrize(
    "block",
    python_blocks(),
    ids=[f"block{i}" for i, _ in enumerate(python_blocks())],
)
def test_every_python_block_in_the_readme_runs(block: str) -> None:
    namespace: dict[str, object] = {"__name__": "readme_example"}
    exec(compile(block, str(README), "exec"), namespace)  # noqa: S102
