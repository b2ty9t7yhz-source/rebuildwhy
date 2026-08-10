# RebuildWhy

RebuildWhy is a transparent reference implementation of explainable cache invalidation
for small, trusted, local task pipelines. It hashes exactly declared inputs, stores verified
immutable outputs, and explains why each task is a cache hit, restoration, definite run, or
conditional downstream run.

The narrow idea at the center of the project is uncertainty honesty: if a changed producer has
not run yet, RebuildWhy does not pretend to know whether its output bytes will change. Directly
changed work is `RUN`; otherwise unchanged consumers are `MAY_RUN` until the real artifact digest
is available.

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
- [Phase 0 research and scope decision](docs/phase-0-design.md)

## Development

```bash
.venv/bin/python -m ruff check src tests examples
.venv/bin/python -m ruff format --check src tests examples
.venv/bin/python -m pytest
.venv/bin/python -m pytest --cov=rebuildwhy --cov-branch --cov-report=term-missing --cov-fail-under=80
```

Tests cover parser/graph validation, canonical hashing, counterfactual relevance, causal uncertainty,
cache corruption and absence, restoration, output conflicts, command failure, required outputs,
failpoint-driven publication boundaries, same-content downstream reuse, and determinism checks.

RebuildWhy is deliberately a small local reference system, not a replacement for DVC, Snakemake,
Bazel, Nix, or a production workflow scheduler.

## License

MIT. See [LICENSE](LICENSE).
