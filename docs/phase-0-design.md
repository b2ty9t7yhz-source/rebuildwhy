# RebuildWhy Phase 0 Design

**Project:** RebuildWhy: Explainable Cache Invalidation for Local Task Pipelines
**Status:** Historical Phase 0 research; the approved V1 implementation now exists
**Research date:** 2026-08-10
**Implemented V1 platform:** Python 3.11+, local POSIX filesystem, trusted local commands

## 1. Executive Decision

**Decision: proceed only with a narrowed scope.**

RebuildWhy is viable as a portfolio project, but not because field-level configuration dependencies, dry runs, affected-subgraph analysis, content hashing, or cache-miss diagnostics are individually new. Mature tools already cover those capabilities in different combinations.

The defensible V1 focus is:

> A transparent reference implementation for small, trusted, local scientific pipelines that computes the minimal affected task subgraph and emits a deterministic causal explanation that distinguishes tasks that must run from tasks that may run because an upstream output is not known yet.

The core demonstration must be `plan` and its reason model. The executor and cache exist only to make the planner's claims testable. If the project becomes a general workflow engine, a DVC clone, or a Bazel-like build system, it has lost its differentiation.

## 2. Problem Statement, Target User, and Use Case

### 2.1 Problem statement

In local research pipelines, one configuration file often controls many tasks. Treating the whole file as one dependency causes unnecessary recomputation, while under-declaring dependencies creates stale results. Existing tools can decide that work is stale, but their explanations and hypothetical planning models vary by ecosystem and are often tied to a specific build language, Git diff, or previously executed build.

RebuildWhy should answer two questions before executing a trusted local pipeline:

1. Which tasks have a direct cache-key change, and which declared input caused it?
2. Which downstream tasks are only conditionally affected because a changed upstream task has not produced its new artifact yet?

### 2.2 Target user

A computational researcher or research-software developer who has:

- a small local DAG, approximately 5–50 tasks;
- expensive deterministic file transformations;
- JSON or YAML configuration with unrelated fields used by different tasks;
- a need for auditable, machine-readable invalidation decisions; and
- no need for remote execution, a cluster scheduler, or a web dashboard.

### 2.3 Realistic V1 use case

A synthetic MRI pipeline contains these tasks:

```text
ingest -> resample -> normalize -> features -> report
```

- `resample` declares `/image/spacing` and `/interpolation/method` as configuration dependencies.
- `normalize` consumes the published `resample` artifact.
- `report` also declares `/report/title`.

A hypothetical change to `/report/title` should affect only `report`. A hypothetical change to `/image/spacing` should directly invalidate `resample`; before `resample` runs, the planner should mark downstream artifact consumers as `MAY_RUN`, not falsely promise that their input bytes will change. If the new `resample` execution produces the same artifact digest, a downstream task may remain a cache hit.

All examples use synthetic files only. RebuildWhy does not need or accept patient data for its demonstration.

## 3. Terms and Boundaries

| Term | V1 meaning |
|---|---|
| File dependency | A declared workspace-relative regular file whose path and SHA-256 content digest enter a task snapshot. |
| Config-field dependency | A declared JSON Pointer into a JSON-compatible YAML or JSON document. Only the selected value enters the task snapshot. |
| Command dependency | The exact argument vector, working-directory policy, and command protocol version. V1 does not execute through a shell. |
| Upstream artifact dependency | A declared file within another task's immutable output bundle. Its artifact digest, not merely the producer task name, enters the consumer key. |
| Environment dependency | An explicitly named environment variable and its current value digest. Undeclared host state is outside the correctness guarantee. |
| Cache key / action key | A SHA-256 digest of a canonical declared-input snapshot that identifies one computation request. |
| Content hash | A SHA-256 digest of actual file bytes or a canonical artifact-tree manifest. It identifies content, not the computation that produced it. |
| Provenance | The immutable record connecting an action key, declared input component digests, execution result, artifact manifest, engine version, and timestamps. |
| Invalidation reason | A structured difference between a baseline snapshot and a current or hypothetical snapshot, plus causal edges to affected consumers. |

## 4. Competitor Research

### 4.1 Evidence summary

- [DVC pipeline files](https://dvc.org/doc/user-guide/project-structure/dvcyaml-files) already support dot-separated, field-level parameter dependencies in YAML, JSON, TOML, and Python parameter files. [`dvc repro --dry`](https://dvc.org/doc/command-reference/repro) previews commands, [`dvc status --json`](https://dvc.org/doc/command-reference/status) reports pipeline changes in a machine-readable form, and [`dvc exp run`](https://dvc.org/doc/command-reference/exp/run) supports on-the-fly parameter overrides, dry execution, temporary workspaces, and queued future execution.
- [Snakemake](https://snakemake.readthedocs.io/en/stable/executing/cli.html) has dry runs, rerun triggers for input/code/params/software environments, and commands that list changed params, input definitions, or code.
- [Bazel](https://bazel.build/versions/7.6.0/docs/user-manual) has `--explain` and verbose explanations. Its [remote-cache debugging guide](https://bazel.build/remote/cache-remote) recommends comparing execution logs containing file inputs, arguments, environment variables, and outputs.
- [GNU Make](https://www.gnu.org/software/make/manual/make.html) has dry-run behavior, a `--what-if`/`-W` file option, and `--debug=why` output explaining newer prerequisites. Its core decision model remains timestamp-oriented.
- [Nix](https://nix.dev/manual/nix/2.18/command-ref/new-cli/nix3-build) has dry runs, derivation-oriented storage, rebuild comparison, and repair of missing or corrupted store paths. [`nix why-depends`](https://nix.dev/manual/nix/2.28/command-ref/new-cli/nix3-why-depends.html) explains dependency paths, while [Nix reproducibility checks](https://nix.dev/manual/nix/2.24/advanced-topics/diff-hook) compare repeated outputs.
- [Gradle](https://docs.gradle.org/current/userguide/build_cache_debugging.html) documents task-input cache keys, input-level cache-miss diagnosis, and cascading misses; Develocity Build Scan comparisons automate part of that diagnosis.
- [bazel-diff](https://github.com/Tinder/bazel-diff) hashes Bazel target graphs across two Git revisions and emits the impacted target set, including optional graph-distance information.
- [Nx affected](https://nx.dev/ci/features/affected) uses Git changes and a project graph to compute and visualize a minimum affected project set.

### 4.2 Competitor matrix

The “missing” column records an evidence-bounded inference from the reviewed official documentation, not proof that no plugin, internal feature, or newer command can provide the capability.

| Project | Existing feature | Missing relative to narrowed RebuildWhy V1 | RebuildWhy differentiation | Duplication risk |
|---|---|---|---|---|
| DVC | Content hashes, pipeline DAG, output cache, granular parameter dependencies, on-the-fly parameter overrides, dry/temporary/queued execution, JSON status | No documented structured causal reason DAG connecting leaf old/new values to downstream decisions with explicit `RUN` versus upstream-unknown `MAY_RUN` semantics | Small local explainability lab with a versioned reason contract and uncertainty semantics | **Very high** |
| Snakemake | DAG execution, dry run, provenance-based rerun triggers, changed-input/code/params listing, caching | No generic JSON-Pointer dependency schema or engine-level causal overlay report independent of Python workflow logic | Restrictive declarative spec and deterministic reason JSON | **High** |
| Bazel | Hermetic action model, action cache, command/input/environment fingerprints, `--explain`, execution-log comparison | No domain-neutral scientific YAML config-field overlay interface; explanations are tied to Bazel actions and builds | Smaller educational model centered on causal invalidation rather than build-language breadth | **High** |
| GNU Make | Timestamp DAG, dry run, hypothetical newer file, `--debug=why` | No content-addressed output cache, field-level config values, or structured causal JSON | Content-based and field-aware planning for local data tasks | **Medium** |
| Nix | Derivations, immutable store, dry run, dependency-path explanation, reproducibility checks | No simple local task-pipeline JSON/YAML field overlay and affected-task reason report | Accessible local pipeline model with visible action-key components | **Medium–high** |
| Gradle / Develocity | Declared task inputs, build-cache keys, input comparison, cascade diagnosis, rich build scans | Tied to Gradle tasks; counterfactual local JSON/YAML overlays are not the primary interface | Open, small, domain-neutral CLI and JSON reason contract | **Very high conceptually** |
| bazel-diff | Exact affected Bazel targets between Git revisions, graph hashes, JSON output, distance metrics | Requires Bazel and revisions or file sets; does not model arbitrary config-leaf overlays or execution-cache outcomes | Hypothetical structured-value changes and action/artifact distinction | **High** |
| Nx affected | Minimum affected projects from Git/file changes and project graph; graph visualization | Project-level Git-oriented affectedness, not content-addressed task outputs or config leaves | Task-level scientific pipeline explanations without requiring Git history | **Medium** |

### 4.3 Gap verdict

**Verdict:** the combination retains a small gap only in how the causal explanation is modeled and exposed. Field-level dependencies and counterfactual/dry planning are already substantially covered by DVC and other tools.

The novelty claim must therefore be modest:

- **Not novel:** field-level dependencies, parameter overrides, dry runs, affected graphs, content-addressed caching, cache-miss diagnostics, or determinism checks by themselves.
- **Potentially distinctive as a compact teaching/reference system:** component-level action-key diffs, a versioned causal reason DAG, and sound uncertainty labels for downstream tasks whose future input content is unknowable before execution.
- **Invalid positioning:** “better than DVC/Snakemake/Bazel,” “new cache invalidation algorithm,” or “production build system.”

## 5. Strict V1 Scope

### 5.1 Goals

1. Validate a versioned YAML task specification.
2. Reject cycles, missing tasks, ambiguous outputs, duplicate publication paths, and missing declared inputs.
3. Produce deterministic topological order.
4. Hash file contents, exact command arguments, selected JSON/YAML fields, explicitly declared environment variables, and upstream artifact content.
5. Separate action keys from output content hashes.
6. Maintain a verified local content-addressed store and immutable action records.
7. Decide among `HIT`, `RESTORE`, `RUN`, `MAY_RUN`, and `BLOCKED`.
8. Explain every non-hit decision using structured leaf reasons and causal edges.
9. Apply hypothetical file replacements and config-field values in memory without editing source files.
10. Compute the minimal affected subgraph reachable from directly changed tasks.
11. Execute trusted tasks sequentially in staging directories.
12. Atomically publish one immutable output bundle per task.
13. Detect missing required outputs, corrupt cache objects, and incomplete publications.
14. Provide an opt-in two-run deterministic-output check.
15. Emit deterministic human-readable CLI output and versioned JSON reports.

### 5.2 Non-goals

- Replacing DVC, Snakemake, Bazel, Make, Nix, Gradle, or Nx.
- Dynamic DAGs, wildcards, scatter/gather, resource scheduling, parallel execution, Slurm integration, or retries.
- Remote execution, remote caches, cloud storage, containers, or distributed coordination.
- Sandboxing or safely executing untrusted commands.
- Automatically discovering undeclared file, network, clock, randomness, hardware, library, or environment dependencies.
- Supporting shell pipelines, command substitution, or arbitrary shell syntax in V1.
- Cross-platform atomicity; V1 targets Linux and macOS on one local filesystem.
- Atomic transactions spanning several independent filesystem mount points.
- A web UI, authentication, multi-user isolation, secrets management, or patient data.
- Performance claims, cache-hit-rate claims, or comparisons with mature systems.
- Git-revision diffing as the main planning model.

## 6. Cache Correctness Model

### 6.1 Conditional guarantee

For task `t`, let `S(t)` be the canonical snapshot of all **declared** dependencies. Let `K(t) = SHA256(canonical_encode(S(t)))` be its action key. RebuildWhy may reuse a prior output only when it has a verified action record for `K(t)` and every referenced content object passes integrity verification.

The guarantee is conditional:

> If a task is deterministic and its outputs depend only on its declared file, config-field, command, environment, and upstream-artifact inputs, equal action keys are safe to reuse.

RebuildWhy cannot make an undeclared dependency safe. A clock read, random source, network call, hidden file read, library version, or hardware property outside the declaration can invalidate the assumption.

### 6.2 Action key composition

The V1 action-key document is canonical JSON containing:

```text
engine_semantics_version
task_spec_version
task_id
command_argv
working_directory_policy
file_inputs[]: logical_path + sha256 + size
config_inputs[]: config_path + JSON_Pointer + canonical_value_digest
environment_inputs[]: variable_name + value_digest or UNSET
upstream_inputs[]: producer_id + artifact_relative_path + content_digest
output_contract: publication_path + required_relative_paths
```

Rules:

- Arrays with set semantics are sorted by their logical locator before encoding.
- Paths are normalized workspace-relative POSIX paths; absolute paths and `..` escapes are rejected.
- Config documents must be JSON-compatible. Custom YAML tags and non-string mapping keys are rejected.
- Selected config values are encoded as UTF-8 canonical JSON with sorted object keys; NaN and Infinity are rejected. Integer `1` and floating-point `1.0` remain distinct in V1.
- The exact argument vector is hashed. V1 does not normalize semantically equivalent commands.
- The task ID is included to prevent surprising cross-task action-record reuse. Output blobs may still deduplicate by content.
- The engine semantics version changes when hashing or execution rules change.

### 6.3 Action cache and content-addressed store

The cache has two layers:

1. **Action records:** `action_key -> artifact_manifest_digest + provenance`.
2. **Content-addressed objects:** `content_digest -> immutable file bytes or artifact manifest`.

An artifact manifest contains sorted relative paths, file sizes, SHA-256 digests, and executable-bit state. V1 output bundles reject symbolic links, sockets, devices, and paths escaping the bundle.

For the synthetic V1 explanation demo, provenance snapshots retain canonical selected config values as well as their digests so that a later plan can show verified old/new values. This is local metadata and is not a secrets store; the trust boundary and report warning below are part of V1.

A cache hit requires all of the following:

- the action record exists and parses under the current schema;
- the stored action key equals the newly computed action key;
- the artifact manifest digest verifies;
- every referenced object exists and its bytes verify; and
- the action record is marked complete.

If an output view is missing but the cache is valid, the decision is `RESTORE`, not `RUN`.

### 6.4 Plan decisions

| Decision | Meaning |
|---|---|
| `HIT` | The action key and published output view are valid; no work is needed. |
| `RESTORE` | A verified action record exists, but the workspace output view must be rematerialized; the command will not run. |
| `RUN` | A direct input/action-key change, missing valid record, corrupt entry, or required recovery condition makes execution necessary. |
| `MAY_RUN` | The task's direct inputs are unchanged, but an upstream task may produce a different artifact digest. The final decision cannot be known before that producer executes or restores a known artifact. |
| `BLOCKED` | Planning or execution cannot proceed because the spec or a required source input is invalid. |

The distinction between `RUN` and `MAY_RUN` is mandatory. A hypothetical upstream action-key change does not prove that its output content will change.

### 6.5 Correctness invariants

1. **Validated graph:** no execution or cache mutation occurs unless all task and artifact references resolve and the graph is acyclic.
2. **Deterministic planning:** identical spec, baseline, filesystem contents, environment inputs, and overlay produce byte-identical JSON reports.
3. **Relevant-field sensitivity:** changing a selected config value changes the direct task action key.
4. **Irrelevant-field stability:** changing only an unselected config value does not change the direct task action key.
5. **Verified reuse:** `HIT` or `RESTORE` is impossible unless the action record, manifest, and objects verify.
6. **Reason completeness:** every `RUN`, `RESTORE`, `MAY_RUN`, or `BLOCKED` decision has at least one structured reason.
7. **Reason fidelity:** each direct invalidation reason identifies an action-key component whose old and new digests differ.
8. **Uncertainty honesty:** a consumer of a not-yet-produced hypothetical artifact is never labeled `RUN` solely because its producer is `RUN`.
9. **No partial publication:** a failed command, missing required output, hash failure, or deterministic-check failure creates no complete action record and does not replace the published view.
10. **Immutable objects:** a published content object is never modified in place.
11. **Atomic visibility:** readers observe either the previous complete output bundle or the new complete output bundle, never a partially populated bundle.
12. **Corruption safety:** a corrupt cache object is never reused; it yields a structured corruption reason and safe recovery.
13. **Content-based downstream reuse:** if a changed upstream action produces an artifact with the previous content digest, downstream consumers may retain their previous action keys.
14. **Declared-input boundary:** reports state that correctness does not cover undeclared dependencies.

## 7. V1 Task Specification

### 7.1 Format decisions

- The pipeline file is YAML, versioned with `version: 1`.
- Config-field locators use RFC 6901 JSON Pointer, not dotted paths. JSON Pointer avoids ambiguity when keys contain dots.
- Commands are argument arrays and run without a shell.
- Each task publishes one logical output bundle directory. Required files are paths inside that bundle.
- Upstream dependencies reference a producer task and a path inside its bundle.
- Runtime context, including the staging output directory and resolved inputs, is provided through a generated JSON context file referenced by `REBUILDWHY_CONTEXT`.

### 7.2 Proposed example

```yaml
version: 1
project: synthetic-mri-demo

tasks:
  resample:
    command:
      argv: [python, -m, example_tasks.resample]
      working_directory: .
    inputs:
      files:
        - data/synthetic_image.bin
        - example_tasks/resample.py
        - requirements.lock
      config:
        - file: config/pipeline.yaml
          pointers:
            - /image/spacing
            - /interpolation/method
      environment:
        - LC_ALL
        - PYTHONHASHSEED
    output:
      publish: outputs/resample
      required:
        - image.bin
        - metadata.json

  normalize:
    command:
      argv: [python, -m, example_tasks.normalize]
      working_directory: .
    inputs:
      files:
        - example_tasks/normalize.py
        - requirements.lock
      artifacts:
        - task: resample
          path: image.bin
      config:
        - file: config/pipeline.yaml
          pointers:
            - /normalization/method
    output:
      publish: outputs/normalize
      required:
        - normalized.bin
```

### 7.3 Validation rules

- Task IDs are unique and match `[a-z][a-z0-9_-]*`.
- Publication paths are unique.
- Commands have a non-empty argument vector.
- Source files and config files must exist for an executable plan.
- Every JSON Pointer must resolve exactly once.
- Artifact producers and required paths must be declared.
- No source input may be inside `.rebuildwhy/` or another task's publication view unless referenced as an artifact.
- A task cannot consume its own artifact.
- The task graph must be acyclic.
- All paths must remain under the project root after normalization.
- Output bundles must be on the same filesystem as the staging and cache directories for atomic rename guarantees.

## 8. Invalidation Reason Model

### 8.1 Reason types

V1 reason codes:

```text
NEW_TASK
FILE_CONTENT_CHANGED
CONFIG_FIELD_CHANGED
COMMAND_CHANGED
ENVIRONMENT_CHANGED
OUTPUT_CONTRACT_CHANGED
UPSTREAM_ARTIFACT_CHANGED
UPSTREAM_ARTIFACT_MAY_CHANGE
ACTION_RECORD_MISSING
OUTPUT_VIEW_MISSING
CACHE_MANIFEST_MISSING
CACHE_OBJECT_MISSING
CACHE_OBJECT_CORRUPT
REQUIRED_OUTPUT_MISSING
NONDETERMINISTIC_OUTPUT
INVALID_SPEC
MISSING_SOURCE_INPUT
```

### 8.2 JSON shape

Reasons are stored as a DAG rather than recursively duplicating a tree. The CLI may render a tree view.

```json
{
  "schema_version": 1,
  "plan_id": "sha256:<digest>",
  "mode": "counterfactual",
  "tasks": [
    {
      "task_id": "resample",
      "decision": "RUN",
      "baseline_action_key": "sha256:<old>",
      "proposed_action_key": "sha256:<new>",
      "reason_ids": ["reason-1"]
    },
    {
      "task_id": "normalize",
      "decision": "MAY_RUN",
      "reason_ids": ["reason-2"]
    }
  ],
  "reasons": [
    {
      "reason_id": "reason-1",
      "code": "CONFIG_FIELD_CHANGED",
      "subject": "config/pipeline.yaml#/image/spacing",
      "old_digest": "sha256:<old-value>",
      "new_digest": "sha256:<new-value>",
      "old_value": [1.0, 1.0, 1.0],
      "new_value": [1.0, 1.0, 2.0],
      "caused_by": []
    },
    {
      "reason_id": "reason-2",
      "code": "UPSTREAM_ARTIFACT_MAY_CHANGE",
      "subject": "resample:image.bin",
      "caused_by": ["reason-1"]
    }
  ]
}
```

For V1 synthetic examples, old and new config values may appear in reports. The documentation must warn users not to place secrets in pipeline configuration. A later version may add digest-only/redacted fields; secrets management is not a V1 promise.

### 8.3 Human-readable rendering

```text
normalize MAY_RUN
└── resample:image.bin may change
    └── resample RUN
        └── config/pipeline.yaml#/image/spacing changed
            ├── old: [1.0, 1.0, 1.0]
            └── new: [1.0, 1.0, 2.0]
```

## 9. Counterfactual Planning Algorithm

### 9.1 Supported V1 overlays

The `plan` command supports two non-mutating overlay types:

```text
--set config/pipeline.yaml#/image/spacing='[1.0,1.0,2.0]'
--replace-file data/synthetic_image.bin=fixtures/alternate_image.bin
```

The first changes an in-memory parsed value. The second uses the replacement file's bytes when computing the virtual dependency digest. Neither operation writes to the source file or config file.

Hypothetical command changes and environment overrides are deferred until after the core file/config planner is correct; current command/environment changes are still detectable by normal planning.

### 9.2 Baseline

The baseline is the most recent verified successful action record for each task under the current project identity. A task without a baseline receives `NEW_TASK`. The planner never infers old values from an unverified or corrupt record.

### 9.3 Algorithm

```text
1. Parse and validate the task specification.
2. Build forward artifact edges and reverse dependency indexes.
3. Compute deterministic topological order.
4. Load and verify baseline snapshots and action records.
5. Parse overlays into an immutable virtual workspace view.
6. Use the reverse index to find tasks that directly declare each overlaid file or field.
7. Recompute only those direct dependency components and their proposed action keys.
8. Emit component-level direct reasons for every digest difference.
9. For each directly changed task:
   a. If the proposed action key has a verified action record, classify it as RESTORE or HIT.
   b. Otherwise classify it as RUN.
10. Traverse downstream artifact-consumer edges from RUN tasks.
11. Until a producer's hypothetical artifact digest is known, classify otherwise unchanged consumers as MAY_RUN and attach causal edges.
12. Exclude unrelated tasks and edges from the affected-subgraph report.
13. Canonically sort tasks, reasons, and edges; emit JSON and render the CLI from that JSON model.
```

During actual execution, decisions are refined in topological order. When a producer publishes or restores an artifact, its real digest becomes known and each `MAY_RUN` consumer is recomputed as `HIT`, `RESTORE`, or `RUN`.

### 9.4 Why the affected subgraph is minimal

The seed set contains only tasks whose declared direct dependency snapshots differ. Propagation follows only declared upstream-artifact consumer edges. Therefore, the reported subgraph contains the seed tasks plus exactly their reachable artifact consumers. Tasks that are neither direct seeds nor reachable consumers are excluded.

This is minimal relative to the declared graph. It is not proof about undeclared runtime dependencies.

### 9.5 Complexity

Let:

- `V` be the number of tasks;
- `E` be the number of artifact-dependency edges;
- `B` be the total bytes hashed for changed or initially indexed files;
- `C` be the parsed size of changed config documents;
- `P` be the total number of selected config pointers examined;
- `A` and `E_A` be the tasks and edges in the affected subgraph.

| Operation | Time | Space |
|---|---:|---:|
| Graph validation and topological sort | `O(V + E)` | `O(V + E)` |
| Full initial file snapshot | `O(B)` | `O(number of file records)` |
| Parse a changed config file and resolve selected pointers | `O(C + P * depth)` | `O(C)` |
| Seed lookup with reverse dependency indexes | `O(number of overlay locators + direct dependents)` | `O(number of dependency locators)` |
| Affected-subgraph traversal | `O(A + E_A)`; worst case `O(V + E)` | `O(A)` |
| Canonical report ordering | `O(A log A + R log R)` for `R` reasons | `O(A + R)` |

Rendering all causal paths as duplicated trees can be exponential in a highly convergent DAG. The JSON model therefore stores reason nodes once and references them by ID; the CLI must cap or deduplicate repeated paths.

## 10. Execution and Atomic Publication Model

1. Create a task staging directory under `.rebuildwhy/tmp/` on the same filesystem as the cache.
2. Write a resolved context JSON file and set `REBUILDWHY_CONTEXT` for the trusted command.
3. Run the exact argument vector without a shell.
4. Require a zero exit status and all declared required output paths.
5. Reject unsupported output file types and paths escaping the staging bundle.
6. Hash output files and build a canonical artifact manifest.
7. Write content objects to temporary cache paths, verify them, then atomically rename them into immutable digest paths.
8. Atomically write the complete action record only after all objects exist.
9. Create a new publication symlink and atomically rename the symlink over the previous task publication view.
10. On failure or crash, leave the previous publication visible. Orphan temporary objects may be cleaned later because no complete action record references them.

An atomic rename is only guaranteed within one filesystem. V1 rejects configurations that would cross filesystems.

## 11. Mandatory Failure and Behavior Tests

| Scenario | Expected decision or outcome | Invariant demonstrated |
|---|---|---|
| Cycle | `BLOCKED`; no command or cache mutation | Validated graph |
| Missing task dependency | `BLOCKED` with `INVALID_SPEC` | Validated graph |
| Missing source file | `BLOCKED` with `MISSING_SOURCE_INPUT` | Reason completeness |
| Missing required task output | Execution fails; prior publication remains; no complete action record | No partial publication |
| Changed file contents | Direct consumer is `RUN` or `RESTORE`; `FILE_CONTENT_CHANGED` records old/new digests | Relevant-input sensitivity |
| Changed relevant config field | Direct consumer key changes with `CONFIG_FIELD_CHANGED` | Relevant-field sensitivity |
| Changed irrelevant config field | Direct task remains `HIT`; no affected-subgraph entry | Irrelevant-field stability |
| Changed command argument | Direct task key changes with `COMMAND_CHANGED` | Action-key completeness |
| Corrupt cached object | Never reused; `CACHE_OBJECT_CORRUPT`; safe rebuild or restore failure | Corruption safety |
| Incomplete cache record | Never reused; treated as missing/incomplete | Verified reuse |
| Nondeterministic task | Two isolated runs yield different artifact digests; no reusable action record | Determinism boundary |
| Changed upstream action, same output digest | Direct producer runs; downstream remains eligible for `HIT` | Content-based downstream reuse |
| Changed upstream action, different output digest | Downstream refines from `MAY_RUN` to `RUN` or `RESTORE` | Uncertainty honesty |
| Missing publication view with valid cache | `RESTORE`; command is not executed | Action/cache separation |
| Crash before action-record rename | Previous publication remains; incomplete temporary data is unreachable | Atomic visibility |
| Two identical plans | Byte-identical canonical JSON | Deterministic planning |

Timing-dependent sleeps must not be the primary mechanism for publication or crash tests. Tests should use injected filesystem-operation hooks or controlled failpoints.

## 12. Proposed Repository Structure

This structure is a design only. The repository must not be created until the user approves Phase 1.

```text
rebuildwhy/
├── .github/
│   └── workflows/
│       └── ci.yml
├── docs/
│   ├── architecture.md
│   ├── cache-correctness.md
│   ├── counterfactual-planning.md
│   ├── phase-0-design.md
│   └── security-and-trust-boundary.md
├── examples/
│   └── synthetic_mri/
│       ├── config/
│       ├── data/
│       ├── example_tasks/
│       └── pipeline.yaml
├── schemas/
│   ├── error-report-v1.schema.json
│   ├── pipeline-v1.schema.json
│   ├── plan-report-v1.schema.json
│   └── run-report-v1.schema.json
├── src/
│   └── rebuildwhy/
│       ├── __init__.py
│       ├── cache.py
│       ├── canonical.py
│       ├── cli.py
│       ├── errors.py
│       ├── executor.py
│       ├── graph.py
│       ├── hashing.py
│       ├── overlays.py
│       ├── planner.py
│       ├── provenance.py
│       ├── publication.py
│       ├── reasons.py
│       └── spec.py
├── tests/
│   ├── integration/
│   ├── unit/
│   └── failure/
├── .gitignore
├── LICENSE
├── README.md
└── pyproject.toml
```

Module boundaries:

- `spec.py` parses and validates user input.
- `graph.py` owns DAG invariants and deterministic ordering.
- `canonical.py` defines versioned canonical encodings.
- `hashing.py` computes dependency and content digests.
- `overlays.py` creates immutable virtual workspace views.
- `planner.py` makes decisions but does not execute commands.
- `reasons.py` owns the reason DAG and report schema.
- `cache.py` and `provenance.py` verify immutable records.
- `executor.py` runs only already-planned trusted tasks.
- `publication.py` owns staging and atomic visibility.

## 13. Milestones

| Milestone | Scope | Exit criterion |
|---|---|---|
| M0: Phase 0 | Research, correctness model, V1 boundary, spec, algorithm, issues | This document reviewed and explicitly approved |
| M1: Spec and graph foundation | Package skeleton, schema, parser, validation, cycle detection, deterministic topological order | Invalid graphs fail before side effects; focused tests pass locally |
| M2: Direct fingerprints and reasons | Canonical values, file/config/command/environment snapshots, action keys, direct reason records | Relevant/irrelevant field behavior is demonstrated with synthetic fixtures |
| M3: Counterfactual planner | In-memory overlays, reverse indexes, minimal affected subgraph, `RUN`/`MAY_RUN`, JSON and CLI report | Core demo works without mutating source files or running commands |
| M4: Verified local cache | Action records, artifact manifests, local CAS, integrity checks, restore decisions | Corrupt/missing objects are never reused |
| M5: Trusted executor and publication | Sequential execution, context contract, staging, required outputs, atomic bundle publication | Failure never replaces the last complete publication |
| M6: Determinism and failure suite | Double-run check, failpoints, mandatory scenario coverage, synthetic pipeline | Required behavior/failure matrix is exercised reproducibly |
| M7: Portfolio polish | CI, architecture docs, security boundary, reproducible demo, versioned schemas | Fresh-clone instructions work and all documented claims match actual evidence |

No milestone may claim a test count, speedup, cache-hit rate, or reliability metric until measured from the actual repository.

## 14. Initial GitHub Issues

Issue text and titles should remain in English.

### Issue 1 — Define and validate the V1 pipeline specification

**Milestone:** M1
**Acceptance criteria:** A versioned schema covers task IDs, argv commands, file/config/environment/artifact inputs, one output bundle, and required paths. Invalid paths, duplicate publications, and unresolved references return stable structured errors.

### Issue 2 — Implement deterministic DAG validation and topological ordering

**Milestone:** M1
**Depends on:** Issue 1
**Acceptance criteria:** Cycles and missing producers fail before side effects. Equivalent valid input produces the same topological order.

### Issue 3 — Define canonical dependency snapshots and action keys

**Milestone:** M2
**Depends on:** Issue 1
**Acceptance criteria:** The canonical format is versioned and documented. Identical snapshots produce identical keys; changing each declared component changes the expected component digest.

### Issue 4 — Implement JSON Pointer config dependencies

**Milestone:** M2
**Depends on:** Issue 3
**Acceptance criteria:** Selected JSON/YAML values are canonicalized independently. A relevant-field change alters the task key; an unrelated-field change does not.

### Issue 5 — Define the plan decision and invalidation-reason schemas

**Milestone:** M2
**Acceptance criteria:** Versioned schemas represent `HIT`, `RESTORE`, `RUN`, `MAY_RUN`, and `BLOCKED`; every non-hit decision requires at least one reason ID.

### Issue 6 — Persist and verify baseline action snapshots

**Milestone:** M2
**Depends on:** Issues 3 and 5
**Acceptance criteria:** Baselines are loaded only from complete, schema-valid records. Missing or invalid baselines produce structured reasons rather than guesses.

### Issue 7 — Add non-mutating config-field overlays

**Milestone:** M3
**Depends on:** Issues 4–6
**Acceptance criteria:** `plan --set` changes an in-memory document only. Source bytes and modification time remain unchanged after successful and failed plans.

### Issue 8 — Add non-mutating file replacement overlays

**Milestone:** M3
**Depends on:** Issues 3, 5, and 6
**Acceptance criteria:** `plan --replace-file` hashes replacement bytes under the original logical locator without modifying either file.

### Issue 9 — Compute direct and conditional affected tasks

**Milestone:** M3
**Depends on:** Issues 2 and 5–8
**Acceptance criteria:** Direct key changes are `RUN` or `RESTORE`; downstream unknowns are `MAY_RUN`; unrelated tasks are excluded.

### Issue 10 — Render deterministic JSON and causal CLI explanations

**Milestone:** M3
**Depends on:** Issue 9
**Acceptance criteria:** JSON output is byte-stable for identical inputs. CLI output is rendered from the JSON model and preserves causal links without unbounded path duplication.

### Issue 11 — Implement a verified local content-addressed store

**Milestone:** M4
**Depends on:** Issues 3 and 6
**Acceptance criteria:** Objects and manifests are addressed by SHA-256, immutable after publication, and verified before reuse.

### Issue 12 — Recover safely from missing and corrupt cache entries

**Milestone:** M4
**Depends on:** Issue 11
**Acceptance criteria:** Missing, truncated, or byte-corrupt records and objects never produce `HIT`; each condition has a structured recovery reason.

### Issue 13 — Implement the trusted sequential execution context

**Milestone:** M5
**Depends on:** Issues 1, 2, 9, and 11
**Acceptance criteria:** Commands run without a shell, receive a generated context path, and cannot publish unless the exit status and required-output contract succeed.

### Issue 14 — Publish immutable output bundles atomically

**Milestone:** M5
**Depends on:** Issues 11 and 13
**Acceptance criteria:** Injected failures at every publication boundary preserve the previous complete view and create no complete action record for partial output.

### Issue 15 — Detect nondeterministic outputs with isolated repeated runs

**Milestone:** M6
**Depends on:** Issues 13 and 14
**Acceptance criteria:** Equal action keys executed twice in independent staging directories must yield equal artifact manifest digests before a verified deterministic result is recorded.

### Issue 16 — Build the synthetic scientific pipeline and failure suite

**Milestone:** M6
**Depends on:** Issues 7–15
**Acceptance criteria:** The repository demonstrates every scenario in the mandatory test matrix using synthetic data and controlled failpoints.

### Issue 17 — Add CI, architecture documentation, and reproducible demo commands

**Milestone:** M7
**Depends on:** Issues 1–16
**Acceptance criteria:** CI runs the documented checks on supported Python versions; a fresh clone can reproduce the demo; claims are limited to observed results.

## 15. Overlap Risks and Enforced Boundaries

| Overlap risk | Boundary that keeps RebuildWhy narrow |
|---|---|
| DVC granular params and pipeline cache | Do not add data versioning, remotes, experiment management, or DVC compatibility. Make causal counterfactual planning the headline. |
| Snakemake workflow language and executors | No dynamic rules, wildcards, cluster backends, resources, or parallel scheduler. |
| Bazel action graph and remote cache | No language rules, toolchains, sandbox, remote cache/execution, or build-system scale claims. |
| Make/Ninja rebuild explanation | Use content digests and structured config leaves; do not pursue general compiler dependency discovery. |
| Nix immutable store and reproducibility | Use a small project-local CAS; do not manage packages, operating-system environments, or derivation languages. |
| Gradle/Develocity cache diagnostics | Keep an open local JSON contract; do not build a general build analytics product or UI. |
| bazel-diff/Nx affected graph | Accept in-memory file/config overlays rather than making Git revision diff the core input. |

The README must lead with a counterfactual explanation example, not a generic DAG execution screenshot.

## 16. Knowledge to Learn During Implementation

The project should teach these topics rather than present them as pre-existing proficiency:

- DAG validation, deterministic topological sorting, and reverse graph traversal;
- canonical serialization and stable hashing boundaries;
- action keys versus content addresses;
- JSON Pointer and safe YAML parsing;
- cache soundness under declared-input and determinism assumptions;
- filesystem atomic rename guarantees and their same-filesystem limitation;
- immutable manifests, integrity verification, and crash-safe publication ordering;
- causal graphs and the difference between definite and conditional invalidation;
- controlled failpoints instead of timing-dependent concurrency tests;
- CLI design, structured errors, JSON schemas, pytest, and GitHub Actions.

None of Bazel, DVC, Snakemake, Nix, Gradle, distributed systems, or production caching should be listed as a mastered skill merely because their documentation informed this design.

## 17. Gate Before Phase 1

Phase 1 should begin only after explicit approval of this design. The first implementation stage must be limited to:

1. create the repository skeleton;
2. add the V1 spec schema;
3. implement graph validation and deterministic topological sorting; and
4. add focused tests for valid graphs, cycles, and missing dependencies.

It must stop before hashing, cache storage, command execution, or atomic publication.
