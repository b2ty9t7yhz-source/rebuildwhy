# RebuildWhy

[![CI](https://github.com/b2ty9t7yhz-source/rebuildwhy/actions/workflows/ci.yml/badge.svg)](https://github.com/b2ty9t7yhz-source/rebuildwhy/actions/workflows/ci.yml)
[![Python 3.11-3.13](https://img.shields.io/badge/python-3.11--3.13-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/b2ty9t7yhz-source/rebuildwhy?display_name=tag)](https://github.com/b2ty9t7yhz-source/rebuildwhy/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

RebuildWhy is a transparent reference implementation of explainable cache invalidation
for small, trusted, local task pipelines. It hashes exactly declared inputs, stores verified
immutable outputs, and explains why each task is a cache hit, restoration, definite run, or
conditional downstream run.

The narrow idea at the center of the project is uncertainty honesty: if a changed producer has
not run yet, RebuildWhy does not pretend to know whether its output bytes will change. Directly
changed work is `RUN`; otherwise unchanged consumers are `MAY_RUN` until the real artifact digest
is available.

## At a glance

- **Precise invalidation:** hash regular files, selected YAML/JSON fields, named environment
  variables, commands, output contracts, and consumed artifact bytes.
- **Causal explanations:** trace every decision to stable reason codes and nested upstream causes in
  human-readable or canonical JSON reports.
- **Verified reuse:** validate SHA-256 objects, manifests, action records, and publication links
  before returning `HIT` or `RESTORE`.
- **Safe local publication:** run trusted commands in isolated staging directories, validate required
  outputs, and atomically publish immutable artifacts.
- **Honest uncertainty:** use `MAY_RUN` for consumers whose future upstream bytes are not yet known,
  and refine those decisions after the producer completes.
- **Auditable quality:** enforce strict typing, branch coverage, versioned JSON contracts,
  determinism checks, and installed-wheel smoke tests on Python 3.11–3.13.

## Quick start

RebuildWhy requires Python 3.11 or newer.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'

.venv/bin/rebuildwhy plan -p examples/synthetic_mri/pipeline.yaml
.venv/bin/rebuildwhy run -p examples/synthetic_mri/pipeline.yaml
.venv/bin/rebuildwhy run -p examples/synthetic_mri/pipeline.yaml
```

The first run executes the five synthetic MRI tasks. The second run reports five verified cache
hits. Generated data stays below `examples/synthetic_mri/.rebuildwhy/`; workspace publications are
managed symbolic links below `examples/synthetic_mri/outputs/`.

Preview a relevant configuration change without editing the config file or running a command:

```bash
.venv/bin/rebuildwhy plan \
  -p examples/synthetic_mri/pipeline.yaml \
  --set 'config/pipeline.yaml#/image/spacing=[1.0,1.0,2.0]'
```

The result identifies `resample` as `RUN`, while its artifact consumers are `MAY_RUN`. An unrelated
field can be changed hypothetically without invalidating any task:

```text
RebuildWhy plan: synthetic-mri-demo (counterfactual)
ingest HIT
resample RUN
  - CONFIG_FIELD_CHANGED: config/pipeline.yaml#/image/spacing
normalize MAY_RUN
  - UPSTREAM_ARTIFACT_MAY_CHANGE: resample:image.json
    - CONFIG_FIELD_CHANGED: config/pipeline.yaml#/image/spacing
features MAY_RUN
report MAY_RUN
```

The complete report continues the causal chain through `features` and `report`.

```bash
.venv/bin/rebuildwhy plan \
  -p examples/synthetic_mri/pipeline.yaml \
  --set 'config/pipeline.yaml#/notes/owner="hypothetical"' \
  --json
```

Replace one logical source file in the virtual view:

```bash
.venv/bin/rebuildwhy plan \
  -p examples/synthetic_mri/pipeline.yaml \
  --replace-file data/synthetic_image.json=fixtures/alternate_image.json
```

Neither overlay mutates source files. Values supplied by `--set` must be valid JSON.

The bundled example is an executable acceptance scenario, not a static screenshot:

| Scenario | Verified behavior |
|---|---|
| First run | All five tasks execute and publish manifests. |
| Identical second run | All five tasks are verified `HIT`s. |
| Relevant spacing overlay | `resample` is `RUN`; downstream consumers are `MAY_RUN`. |
| Unselected notes overlay | All five tasks remain `HIT`; the affected set is empty. |
| Missing publication link | Valid cached content is selected as `RESTORE`. |
| Changed producer action, identical consumed bytes | A downstream `MAY_RUN` refines to `HIT`. |

See the [synthetic MRI walkthrough](examples/synthetic_mri/README.md) for the graph, commands, and
expected decisions.

## Decision model

| Decision | Meaning |
|---|---|
| `HIT` | The action record, manifest, objects, and publication view all verify. |
| `RESTORE` | Cached content verifies, but the managed publication view is missing or stale. |
| `RUN` | A concrete action has no verified reusable result. |
| `MAY_RUN` | A direct input is unchanged, but an upstream artifact digest is not known yet. |
| `BLOCKED` | Reserved in the report schema for invalid or unavailable plans; V1 CLI errors fail before emitting a plan. |

During `run`, decisions are recomputed in topological order. A producer may run and create the same
artifact bytes as before; in that case, its consumer can refine from `MAY_RUN` to `HIT`.

## What enters an action key

Each task action key is the SHA-256 digest of canonical JSON containing:

- the exact command argument vector and working-directory policy;
- every declared regular source file's logical path, content digest, and size;
- only the declared JSON Pointer values from YAML or JSON configuration;
- digests of explicitly named environment variables, including an explicit unset state;
- content digests of declared upstream artifact files;
- the output publication and required-file contract; and
- the engine semantics and task-spec versions.

Action keys identify computations. Artifact digests identify output content. Keeping these separate
allows downstream cache reuse when different producer actions create identical consumed bytes.

## Pipeline format

```yaml
version: 1
project: minimal-example
tasks:
  generate:
    command:
      argv: [python3, task.py]
      working_directory: .
    inputs:
      files: [task.py, data/input.json]
      config:
        - file: config/settings.yaml
          pointers: [/algorithm/tolerance]
      environment: [LC_ALL]
    output:
      publish: outputs/generate
      required: [result.json]
```

Commands run directly, never through a shell. They receive the path of a generated context document
in `REBUILDWHY_CONTEXT`. That JSON document contains the isolated staging output directory and
resolved file, config, and artifact inputs. See the complete
[`synthetic_mri` example](examples/synthetic_mri/pipeline.yaml).

The public contracts are versioned as JSON Schema:

- [pipeline V1](schemas/pipeline-v1.schema.json)
- [plan report V1](schemas/plan-report-v1.schema.json)
- [run report V1](schemas/run-report-v1.schema.json)
- [error report V1](schemas/error-report-v1.schema.json)

## Correctness boundary

Cache reuse is safe under a conditional contract:

> If a task is deterministic and its outputs depend only on declared inputs, equal action keys are
> safe to reuse after every referenced cache object verifies.

RebuildWhy does not sandbox commands or discover hidden dependencies. Clock reads, randomness,
network calls, undeclared files, undeclared environment state, interpreter/library changes, and
hardware behavior are outside the guarantee unless represented by a declared input. Commands are
therefore trusted local code. Do not place secrets in selected config values because explanation
reports intentionally retain old and new values.

Use an opt-in two-run check for important deterministic tasks:

```bash
.venv/bin/rebuildwhy verify-determinism features \
  -p examples/synthetic_mri/pipeline.yaml
```

## Documentation

- [Architecture](docs/architecture.md)
- [Cache correctness](docs/cache-correctness.md)
- [Counterfactual planning](docs/counterfactual-planning.md)
- [Security and trust boundary](docs/security-and-trust-boundary.md)
- [Versioned JSON schemas](schemas/README.md)
- [Verification and acceptance matrix](docs/verification.md)
- [Phase 0 research and scope decision](docs/phase-0-design.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## Development

```bash
.venv/bin/python -m ruff check src tests examples
.venv/bin/python -m ruff format --check src tests examples
.venv/bin/python -m mypy
.venv/bin/python -m pytest --cov=rebuildwhy --cov-branch --cov-report=term-missing --cov-fail-under=80
.venv/bin/python -m build
```

Tests cover parser/graph validation, canonical hashing, counterfactual relevance, causal uncertainty,
cache corruption and absence, restoration, output conflicts, command failure, required outputs,
failpoint-driven publication boundaries, same-content downstream reuse, determinism checks, and
Draft 2020-12 schema validation against real pipeline, plan, run, and error instances. See the
[acceptance matrix](docs/verification.md) for claim-to-test traceability. GitHub Actions runs
linting, formatting, strict typing, branch coverage, and the full test suite on Python 3.11, 3.12,
and 3.13, then installs and exercises the built wheel in a clean packaging job.

RebuildWhy is deliberately a small local reference system, not a replacement for DVC, Snakemake,
Bazel, Nix, or a production workflow scheduler.

## License

MIT. See [LICENSE](LICENSE).
