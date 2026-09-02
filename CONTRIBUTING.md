# Contributing to decidable

Thanks for looking. This project has a narrow thesis and a small surface area, and the
guidance below is mostly about keeping it that way.

Read [CLAUDE.md](CLAUDE.md) first — it is the project spec, and it is short.

## Setup

Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```
git clone https://github.com/maximebxyer/decidable
cd decidable
uv sync
```

## The checks

All four must be clean before a pull request is ready. There is no CI yet, so please run
them locally.

```
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict
uv run pytest -q
```

Two notes:

- **`ruff` runs on its default configuration, on purpose.** There is no `[tool.ruff]`
  section in `pyproject.toml` and adding one is not the fix. If a rule fires, change the
  code. If a rule is genuinely wrong for a specific line, a targeted `# noqa` with a
  comment explaining why is fine — see the blanket `except Exception` in
  `src/decidable/verifiers/base.py`, where the breadth is the whole point.
- **`mypy --strict` covers `src` and `tests`.** Tests are held to the same standard as the
  library; the harness should be tested with the rigour it measures.

The README's Python blocks are executed by `tests/test_readme.py`. If you change an
example, it has to still run — including its assertions. Snippets that are illustrative
rather than runnable should use a non-`python` fence.

## Writing a verifier

A verifier is a pure function from artifact to verdict. The protocol lives in
[src/decidable/verifiers/base.py](src/decidable/verifiers/base.py):

```python
class Verifier(Protocol):
    name: str
    stage: Stage

    def verify(self, artifact: Artifact, /) -> Verdict: ...
```

The contract, in full:

- **Never call a model.** This is the thesis. A verifier that needs a model is not a
  verifier, and a pull request that adds one will be declined regardless of how well it
  works.
- **Set `name` and `stage`.** Pick the cheapest stage that honestly describes the check.
  The stage is what the failure taxonomy is built on.
- **Attribute the verdict to yourself.** Build a `VerifierRef(name=self.name,
  stage=self.stage)` and put it on every verdict you return. The stack raises if a verdict
  comes back attributed to a different verifier — a misattributed verdict silently
  corrupts the breakdown, so it is caught loudly instead.
- **Return `FAIL` for a bad artifact. Let your own breakage raise.** Do not catch a
  missing tool or a broken fixture and report it as `FAIL`. Let the exception escape: the
  stack converts it to `ERROR` with the traceback attached. If you can detect your own
  breakage cleanly, return `ERROR` with a `HarnessError` explicitly.
- **Always populate `Evidence.summary`**, non-empty and one line. It is what gets printed.
  Put aggregatable facts in `Evidence.data` (flat scalars and scalar tuples) and long
  output — tracebacks, diffs, tool stdout — in `Evidence.detail`.
- **Do not time yourself.** The stack stamps `duration_s` on every verdict, so timing is
  measured consistently and cannot be forgotten.
- **Be deterministic.** Same artifact, same verdict. Record versions, seeds and timeouts
  in the evidence where they matter.

Everything a verifier needs in order to decide — expected output, a fixture path, a
property test — is supplied when it is constructed. That is what keeps `verify` a function
of the artifact alone.

## Design rules a pull request is judged against

These come from the spec, and they are the reason to say no to otherwise good code:

- No model calls inside a verifier, ever.
- No plugin system, config layer, or abstraction added "for later". Add it when a second
  real use case demands it.
- No model provider SDK as a dependency. Example adapters use `httpx` directly and live in
  `examples/`.
- Every new public API is one we have to keep. Prefer composition over configuration
  flags, and say why a new name earns its place.
- `ERROR` and `FAIL` stay distinct in types, storage and reporting.
- Do not introduce synonyms for Task, Agent, Verifier, Verdict, Suite, Run, or Report.
- Do not make the report pretty before it is correct.

## Commits and pull requests

- Imperative subject line, no scope prefixes: `Add the parse verifier`, not
  `feat(verifiers): add parse verifier`.
- Small commits, with a working tree at each step — the four checks should pass at every
  commit, not just at the end of the branch.
- Tests alongside the code they cover, in the same commit.
- In the pull request description, say what the change decides and what it deliberately
  leaves out.

## Where help is most useful

Milestones land in order, so the useful work is at the front of the queue. See the status
table in the [README](README.md#status).

**Milestone 2 — the Python verifier stack** is the natural first contribution, and it
splits into four independent pieces, each testable on its own:

| Stage | Verifier | Notes |
|-------|----------|-------|
| `SYNTACTIC` | `ast.parse` | source position into `Evidence.data` |
| `STATIC` | `mypy`, `ruff` | error codes into `Evidence.data` so they aggregate |
| `DYNAMIC` | subprocess execution with a timeout | not a security boundary; say so |
| `BEHAVIOURAL` | `pytest` property tests | failing assertion into `Evidence.detail` |

Each of these is a self-contained pull request. Taking one and doing it well is more
useful than taking all four.

After that: the runner with caching and reproducibility metadata (3), the report with its
failure breakdown by stage (4), then the CLI and YAML suite format (5). Milestone 5 comes
last on purpose — a good library with no CLI is useful, a CLI over a weak core is not.

## Questions

Open an issue at
[github.com/maximebxyer/decidable/issues](https://github.com/maximebxyer/decidable/issues).
If you are unsure whether a change fits the thesis, ask before building it — it is a
cheaper conversation than a declined pull request.
