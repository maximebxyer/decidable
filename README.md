<p align="center">
  <img src="docs/banner.png" alt="decidable" width="100%">
</p>

# decidable

An evaluation harness for agents whose outputs can be **verified by execution**, not
judged by another model.

---

## Why this exists

Most agent evaluation today relies on LLM-as-judge. That approach is unfalsifiable,
non-reproducible, and expensive. It also throws away a fact that matters in the domains
where agents are actually deployed: **correctness is often decidable**.

If an agent emits Python, you can parse it, type-check it, run it, and test properties of
its behaviour. If it emits SQL, you can run it against a fixture database and compare
result sets. If it emits industrial control logic, you can check invariants. In all these
cases a judge model is not just unnecessary, it is strictly worse than executing the
artifact.

`decidable` answers a narrow question well: *did the agent produce an artifact that is
verifiably correct, and if not, exactly where did it break?*

## Status

**v0.1, early.** One of six milestones is built. This table is the honest picture, and
the README describes the design in full so contributors can see where the work is — not
because the unbuilt parts exist.

| # | Milestone | State |
|---|-----------|-------|
| 1 | Core models and the Verifier protocol | **shipped** |
| 2 | Python verifier stack (`ast.parse`, `mypy`/`ruff`, subprocess, `pytest`) | not built |
| 3 | Runner with caching and reproducibility metadata | not built |
| 4 | Report with failure breakdown by stage | not built |
| 5 | CLI and YAML suite format | not built |
| 6 | Worked example and one-command reproduction | not built |

**There is no `decidable` CLI yet**, and no Python verifiers ship with the package. What
exists today is the library: the core types, and a verifier stack you can compose your own
verifiers into. The [Quickstart](#quickstart) below runs against that, today.

## Core concepts

Four nouns carry the whole design. The codebase uses these words and no synonyms.

- **Task** — a single evaluation unit: a prompt, optional context and fixtures. A task is
  pure data, so it serializes and can be stored.
- **Agent** — anything callable that maps a Task to an artifact. Agents are user-supplied;
  the harness ships thin adapters, not integrations. A plain function satisfies it.
- **Verifier** — a pure function from artifact to Verdict. **It never calls a model.**
- **Verdict** — `PASS`, `FAIL`, or `ERROR`, plus structured evidence.

A **Suite** is a set of Tasks. A **Run** is a Suite executed against one Agent, producing
a **Report**.

An artifact is whatever the agent produced. In v0.1 that is text, because v0.1 verifies
generated Python source.

## The verifier stack

Verifiers are ordered cheap to expensive and short-circuit on the first non-pass:

| Stage | Question | Example |
|-------|----------|---------|
| `SYNTACTIC` | does it parse? | `ast.parse` |
| `STATIC` | does it type-check, lint, satisfy a schema? | `mypy`, `ruff` |
| `DYNAMIC` | does it execute without crashing, within a timeout? | subprocess run |
| `BEHAVIOURAL` | does it satisfy property tests, invariants, expected outputs? | `pytest` |

This ordering is the point: it turns a pass rate into a **failure taxonomy**. An agent
that scores 60% is uninformative. The same agent described this way is not:

```text
120 tasks

  syntactic     6 failed   ( 5%)   it did not parse
  static       36 failed   (30%)   it parsed but did not type-check
  dynamic       0 failed
  behavioural   6 failed   ( 5%)   it ran but gave wrong answers
  ------------------------------------------------
  passed       72          (60%)
```

Both agents "score 60%". Only the second tells you what to fix.

Because the ordering carries this meaning, `VerifierStack` refuses to be built out of
order — a `BEHAVIOURAL` verifier cannot precede a `SYNTACTIC` one. Repeating a stage is
fine; going backwards raises `ValueError`.

When a verifier does not pass, the verifiers after it are never run. They are recorded as
**skipped**, not as verdicts, so a report can distinguish "type-checking failed" from
"type-checking was never attempted".

## `ERROR` is not `FAIL`

This is the sharpest decision in the project, and it is enforced by the types rather than
by convention.

- **`FAIL`** means the agent produced a bad artifact.
- **`ERROR`** means *the verifier itself could not run* — `mypy` is not installed, a
  fixture is missing, the harness has a bug. It says nothing about the agent.

Folding one into the other produces dishonest numbers, so they are kept apart everywhere:

- A `Verdict` carries a `HarnessError` **if and only if** its status is `ERROR`. An
  `ERROR` without one is a validation error, and so is a `PASS` or `FAIL` that carries
  one. You cannot construct a misleading verdict.
- Any exception escaping a verifier is caught by the stack and converted into an `ERROR`
  verdict with the traceback attached. A crashing verifier can never surface as a `FAIL`.
- `ERROR` short-circuits the stack exactly like `FAIL`. If `mypy` could not run, the
  verdicts after it would not be trustworthy.
- Rolling up many verdicts, `ERROR` dominates `FAIL`, which dominates `PASS`. Rolling up
  *nothing* is `ERROR`: if no verdict was reached, nothing was decided, and that is a
  harness condition rather than a passing agent.

There is no fourth status. "Not reached" is represented by absence.

## Evidence, not scores

Every verdict carries evidence, and a bare boolean is treated as a bug. `Evidence` has
three fields:

- `summary` — required, non-empty, one line. This is what the failure taxonomy prints.
- `detail` — free text for reproducing and understanding: a traceback, a diff, a failing
  assertion.
- `data` — a flat map of scalars and scalar tuples, for whatever is structured enough to
  aggregate across a run (counting `mypy` error codes over a whole suite, say).

`data` is deliberately not recursive. It exists to be aggregated, and nested blobs do not
aggregate; long unstructured output belongs in `detail`.

The shape of `data` is each family of verifiers' own business. Process fields like exit
codes live there rather than on the base model, because a parse verifier has no exit code
— it has a source position.

## Install

Python 3.11+ and [uv](https://docs.astral.sh/uv/). The package is **not on PyPI yet**, so
clone it:

```
git clone https://github.com/maximebxyer/decidable
cd decidable
uv sync
```

## Quickstart

Two verifiers, composed into a stack, run against a string artifact. This is the whole
library as it exists today — and `tests/test_readme.py` executes this block, assertions
included, so it is true or the test suite fails.

```python
import ast

from decidable import Evidence, Stage, Status, Verdict, VerifierRef
from decidable.verifiers import VerifierStack


class ParsesAsPython:
    name = "ast_parse"
    stage = Stage.SYNTACTIC

    def verify(self, artifact: str) -> Verdict:
        me = VerifierRef(name=self.name, stage=self.stage)
        try:
            ast.parse(artifact)
        except SyntaxError as exc:
            return Verdict(
                status=Status.FAIL,
                verifier=me,
                evidence=Evidence(
                    summary=f"does not parse: {exc.msg}",
                    data={"line": exc.lineno, "offset": exc.offset},
                ),
            )
        return Verdict(
            status=Status.PASS,
            verifier=me,
            evidence=Evidence(summary="parses as Python"),
        )


class AnnotatesReturnTypes:
    name = "return_annotations"
    stage = Stage.STATIC

    def verify(self, artifact: str) -> Verdict:
        me = VerifierRef(name=self.name, stage=self.stage)
        bare = tuple(
            node.name
            for node in ast.walk(ast.parse(artifact))
            if isinstance(node, ast.FunctionDef) and node.returns is None
        )
        if bare:
            return Verdict(
                status=Status.FAIL,
                verifier=me,
                evidence=Evidence(
                    summary=f"{len(bare)} function(s) lack a return annotation",
                    data={"functions": bare},
                ),
            )
        return Verdict(
            status=Status.PASS,
            verifier=me,
            evidence=Evidence(summary="every function annotates its return type"),
        )


stack = VerifierStack([ParsesAsPython(), AnnotatesReturnTypes()])

# It parses, so stage 1 passes and stage 2 runs and fails.
result = stack.run("def fizzbuzz(n):\n    return str(n)\n")

assert result.status is Status.FAIL
assert result.verdicts[0].status is Status.PASS
assert result.verdicts[1].evidence.summary == "1 function(s) lack a return annotation"
assert result.verdicts[1].evidence.data["functions"] == ("fizzbuzz",)
assert result.skipped == ()

# It does not parse, so stage 2 is never attempted.
broken = stack.run("def fizzbuzz(:\n")

assert broken.status is Status.FAIL
assert len(broken.verdicts) == 1
assert broken.skipped[0].name == "return_annotations"


# A verifier that breaks is an ERROR, never a FAIL.
class BrokenVerifier:
    name = "needs_a_tool_that_is_missing"
    stage = Stage.STATIC

    def verify(self, artifact: str) -> Verdict:
        raise FileNotFoundError("mypy: command not found")


crashed = VerifierStack([BrokenVerifier()]).run("x = 1\n")

assert crashed.status is Status.ERROR
assert crashed.verdicts[0].error is not None
assert crashed.verdicts[0].error.exception_type == "FileNotFoundError"
assert "FileNotFoundError" in crashed.verdicts[0].error.traceback
```

Note what a verifier does *not* do: it does not time itself (the stack stamps
`duration_s`), and it does not catch its own breakage to report a `FAIL` (the stack turns
exceptions into `ERROR`).

## API as it stands today

Everything importable right now. This is the whole public surface; each entry is one we
intend to keep.

From `decidable`:

| Name | What it is |
|------|-----------|
| `Task` | id, prompt, optional context and fixtures |
| `Agent` | protocol: `__call__(task) -> Artifact` |
| `Verdict` | status, verifier, evidence, optional `HarnessError`, `duration_s` |
| `Status` | `PASS` / `FAIL` / `ERROR` |
| `Stage` | `SYNTACTIC` / `STATIC` / `DYNAMIC` / `BEHAVIOURAL`, with `.rank` |
| `Evidence` | `summary`, `detail`, `data` |
| `HarnessError` | exception type, message, traceback |
| `VerifierRef` | a verifier's name and stage, for reports |
| `TaskResult` | one task's verdicts, its skipped verifiers, the artifact digest |
| `RunMetadata` | versions, platform, agent name, timestamps |
| `Report` | metadata plus task results |
| `roll_up` | reduce verdicts to one status, `ERROR` dominating |
| `Artifact` | type alias, currently `str` |
| `EvidenceValue` | what `Evidence.data` values may be |

From `decidable.verifiers`:

| Name | What it is |
|------|-----------|
| `Verifier` | protocol: `name`, `stage`, `verify(artifact) -> Verdict` |
| `VerifierStack` | ordered composition, short-circuits on the first non-pass |
| `StackResult` | the verdicts produced and the verifiers skipped |

All models are frozen and reject unknown fields. The package is typed (`py.typed`) and
checked with `mypy --strict`.

`Report` exists as a model but nothing renders it yet — that is milestone 4. Likewise
`RunMetadata` is deliberately minimal until milestone 3 has real seeds, timeouts and
environment to record.

## Design principles

- **Verifiers never call models.** This is the whole thesis. A verifier that needs a model
  is not a verifier.
- **`ERROR` is not `FAIL`.** Kept distinct in types, storage, and reporting.
- **Evidence over scores.** Every verdict carries enough context to reproduce it.
- **Reproducibility is a feature.** A report that cannot be re-derived is worthless.
- **Small surface area.** Every public API is one we have to keep. Composition over
  configuration flags.

## When not to use this

If your task's correctness is a matter of taste — tone, style, helpfulness, whether a
summary is *good* — this is the wrong tool, and no amount of harness will make it the
right one. `decidable` is deliberately not a general-purpose eval framework, and it has no
opinion about tasks it cannot decide.

It is also Python-only in v0.1, by choice rather than by accident.

## Safety

Today the library executes nothing: there are no execution verifiers yet, and a verifier
you write runs in your own process.

When milestone 2 lands, dynamic and behavioural verification will use subprocess isolation
with timeouts and resource limits. That is **not a security boundary**. It guards against
runaway loops and accidental mess, not against hostile code. Do not point it at artifacts
you would not run yourself.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the checks a
pull request must pass, and what makes a good verifier. Milestone 2's Python verifier
stack is the most useful place to start.

## License

MIT — see [LICENSE](LICENSE).
