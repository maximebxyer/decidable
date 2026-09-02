"""The verifier stack for Python code generation, cheap to expensive.

    >>> VerifierStack([
    ...     ParseVerifier(),
    ...     MypyVerifier(),
    ...     RuffVerifier(),
    ...     ExecuteVerifier(),
    ...     PytestVerifier(tests),
    ... ])

None of these call a model. Each decides by parsing, type-checking, linting or
running the artifact, and reports what it saw.
"""

from decidable.verifiers.python.execute import ExecuteVerifier
from decidable.verifiers.python.parse import ParseVerifier
from decidable.verifiers.python.properties import PytestVerifier
from decidable.verifiers.python.static import MypyVerifier, RuffVerifier

__all__ = [
    "ExecuteVerifier",
    "MypyVerifier",
    "ParseVerifier",
    "PytestVerifier",
    "RuffVerifier",
]
