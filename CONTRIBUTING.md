# Contributing to decidable

Thanks for looking. This project has a narrow thesis and a small surface area, and the
guidance below is mostly about keeping it that way.

Read [CLAUDE.md](CLAUDE.md) first — it is the project spec, and it is short.

## Setup

Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```
git clone https://github.com/maximebxyer/decidable
cd decidable
uv sync --extra python
```

The `python` extra brings in `mypy`, `ruff` and `pytest` as tools the shipped verifiers
shell out to. You want it: without it, the Python verifier tests all return `ERROR`.

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
table in the [README](README.md#status). Milestones 1 and 2 are done.

**Milestone 3 — the runner** is next: execute a suite of tasks against an agent,
producing a `Report`. Two things make it more than a for-loop, and both are worth
discussing in an issue before building:

- **Caching.** Same suite, same artifacts, same verdicts. The cache key has to cover the
  artifact *and* everything about the verifier that could change its answer — a verdict
  restored from cache after a `mypy` upgrade would be a lie.
- **Reproducibility metadata.** `RunMetadata` is deliberately thin today. Milestone 3 is
  when seeds, timeouts and tool versions become real and get recorded.

There is also an open design question the runner forces: `Task` is pure data and holds no
verifiers, so something has to pair each task with its `VerifierStack`. Whatever shape
that takes is a new public name, so it deserves an argument.

After that: the report with its failure breakdown by stage (4), then the CLI and YAML
suite format (5), then the worked example (6). Milestone 5 comes late on purpose — a good
library with no CLI is useful, a CLI over a weak core is not.

Smaller contributions that need no coordination: more Python verifiers (a `pyright`
alternative to `mypy`, a docstring or complexity check), and better evidence from the
existing ones.

## Questions

Open an issue at
[github.com/maximebxyer/decidable/issues](https://github.com/maximebxyer/decidable/issues).
If you are unsure whether a change fits the thesis, ask before building it — it is a
cheaper conversation than a declined pull request.
