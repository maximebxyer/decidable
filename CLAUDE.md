# decidable

An evaluation harness for agents whose outputs can be **verified by execution**, not judged by another model.

## Why this exists

Most agent evaluation today relies on LLM-as-judge. That approach is unfalsifiable, non-reproducible, and expensive. It also throws away a fact that matters in the domains where agents are actually deployed: **correctness is often decidable**.

If an agent emits Python, you can parse it, type-check it, run it, and test properties of its behaviour. If it emits SQL, you can run it against a fixture database and compare result sets. If it emits industrial control logic, you can check invariants. In all these cases a judge model is not just unnecessary, it is strictly worse than executing the artifact.

`decidable` is a harness for building and running evaluations of this kind. It answers a narrow question well: *did the agent produce an artifact that is verifiably correct, and if not, exactly where did it break?*

It is deliberately **not** a general-purpose eval framework. If your task's correctness is a matter of taste, this is the wrong tool.

## Core concepts

These four nouns are the vocabulary of the codebase. Do not introduce synonyms.

- **Task** — a single evaluation unit: a prompt, optional context/fixtures, and an ordered list of verifiers.
- **Agent** — anything callable that maps a Task to an artifact (a string, a file, a structured object). Agents are user-supplied; the harness ships thin adapters, not integrations.
- **Verifier** — a pure function from artifact to **Verdict**. It never calls a model.
- **Verdict** — `PASS`, `FAIL`, or `ERROR`, plus structured evidence (stderr, failing assertion, diff, timing). `ERROR` means the verifier itself could not run, and is never silently folded into `FAIL`.

A **Suite** is a set of Tasks. A **Run** is a Suite executed against one Agent, producing a **Report**.

## The verifier stack

Verifiers are ordered from cheap to expensive and short-circuit on failure. This ordering is the point: it turns a pass rate into a **failure taxonomy**.

1. **Syntactic** — does it parse?
2. **Static** — does it type-check, lint, satisfy a schema?
3. **Dynamic** — does it execute without crashing, within a timeout?
4. **Behavioural** — does it satisfy property tests, invariants, expected outputs?

An agent that scores 60% is uninformative. An agent that fails 5% at parse, 30% at type-check, and 5% at behaviour tells you what to fix. The report must always break failures down by stage.

## v0.1 scope

**In scope**

- The four core abstractions above, with a clean plugin interface for custom verifiers
- A working verifier stack for **Python code generation**: `ast.parse` → `mypy`/`ruff` → subprocess execution with timeout → `pytest` property tests
- A YAML suite format and a `decidable run` CLI
- Terminal report (rich) and machine-readable JSON output
- Deterministic, cacheable runs: same suite + same artifacts = same verdicts
- One worked example suite committed to the repo, so the README is reproducible in one command

**Out of scope for v0.1** — do not build these without being asked

- LLM-as-judge or any model call inside a verifier
- Languages other than Python
- Distributed or parallel execution beyond a simple process pool
- Web UI, dashboards, hosted service
- Model provider integrations beyond a trivial example adapter

## Design principles

- **Verifiers never call models.** This is the whole thesis. A verifier that needs a model is not a verifier.
- **`ERROR` is not `FAIL`.** Conflating harness failure with agent failure produces dishonest numbers. Keep them distinct everywhere: types, storage, reporting.
- **Evidence over scores.** Every verdict carries enough context to reproduce and understand it. A bare boolean is a bug.
- **Reproducibility is a feature.** Record versions, seeds, timeouts, and environment in the Run metadata. A report that cannot be re-derived is worthless.
- **Honest about sandboxing.** v0.1 uses subprocess isolation with timeouts and resource limits. That is *not* a security boundary. Say so in the README rather than implying safety we do not provide.
- **Small surface area.** Every public API we add is one we have to keep. Prefer composition over configuration flags.

## Tech stack and conventions

- Python 3.11+, dependency management with `uv`
- `pydantic` for all data models; no bare dicts crossing module boundaries
- `typer` for CLI, `rich` for terminal output
- `pytest` for our own tests; the harness must be tested with the same rigour it measures
- Full type annotations, `mypy --strict` clean
- `ruff` for lint and format, default config, no bikeshedding

Commit style: imperative subject line, no scope prefixes. Small commits with a working tree at each step.

## Repository layout

```
src/decidable/
  models.py        # Task, Agent protocol, Verdict, Report — pydantic
  verifiers/
    base.py        # Verifier protocol, composition, short-circuit logic
    python/        # parse, static, execute, property-test verifiers
  runner.py        # suite execution, caching, metadata capture
  report.py        # terminal + JSON rendering, failure breakdown
  cli.py
examples/
  python_codegen/  # the worked suite referenced in the README
tests/
```

## Milestones

1. Core models and the Verifier protocol, with tests. No CLI yet.
2. Python verifier stack, each stage independently tested.
3. Runner with caching and reproducibility metadata.
4. Report with failure breakdown by stage.
5. CLI and YAML suite format.
6. Worked example, README, and a one-command reproduction.

Ship 1–4 before touching the CLI. A good library with no CLI is useful; a CLI over a weak core is not.

## Things to avoid

- Do not add a plugin system, config layer, or abstraction "for later". Add it when a second real use case demands it.
- Do not make the report pretty before it is correct.
- Do not add a model provider SDK as a dependency. Example adapters use `httpx` directly and live in `examples/`.
- Do not write a README that promises v1.0 features. Describe what runs today.
