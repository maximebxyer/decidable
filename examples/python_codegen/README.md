# python_codegen

The worked example. Six Python code-generation tasks, run against a canned agent
whose answers break at six different points.

```
uv run decidable run examples/python_codegen/suite.yaml \
  --agent examples/python_codegen/agent.py:agent
```

It exits 1, because five of the six tasks fail on purpose. That is the point: a
worked example where everything passes demonstrates nothing.

## What each answer gets wrong

| Task | Stage it reaches | What is wrong with the answer |
|------|------------------|-------------------------------|
| `fizzbuzz` | passes everything | nothing — the control case |
| `roman` | fails `SYNTACTIC` | an unterminated dict literal; it never parses |
| `anagram` | fails `STATIC` (mypy) | returns `str` from a function declared `-> bool` |
| `primes` | fails `STATIC` (ruff) | imports `os` and never uses it |
| `balanced` | fails `DYNAMIC` | type-checks and lints, then divides by zero at import |
| `rle` | fails `BEHAVIOURAL` | parses, type-checks, lints, runs — and returns the wrong answer |

The last row is the one that makes the case for this project. `rle` is code that
passes every check short of running the tests, and only a behavioural verifier
can tell you it is wrong. No judge model is needed, or wanted, to decide it.

## The agent

[agent.py](agent.py) is a dict lookup. A real agent would call a model; the
harness does not care, because an `Agent` is anything callable that maps a task
to an artifact. Keeping it canned means no API key, no network, and a
reproduction that is byte-identical on every machine — which is what makes it a
reproduction.

## The tests

[tests/](tests/) holds one property-test module per task. They import the
artifact by module name:

```python
from solution import fizzbuzz
```

`PytestVerifier` writes the artifact to `solution.py` in a temporary directory
and runs the tests beside it. Each task names its own file in
[suite.yaml](suite.yaml), which is why the test content is hashed into that
verifier's fingerprint: editing a test must invalidate the cached verdict.
