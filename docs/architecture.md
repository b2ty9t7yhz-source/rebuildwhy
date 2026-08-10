# Architecture

## Design center

RebuildWhy is organized around one separation:

```text
declared inputs -> action snapshot -> action key -> action record
                                             \-> artifact manifest -> file objects
```

An action key describes a computation request. A manifest describes the output tree produced by a
successful request. Individual object digests describe file bytes. A consumer hashes only the
declared producer files it reads, not the producer action key or entire bundle digest.

## Components

| Module | Responsibility |
|---|---|
| `spec.py` | Strict YAML/JSON parsing, paths, JSON Pointers, and publication validation. |
| `graph.py` | Artifact-edge validation and deterministic topological traversal. |
| `overlays.py` | Immutable config-value and logical-file counterfactual views. |
| `hashing.py` | Canonical declared-input snapshots and action keys. |
| `planner.py` | Cache decisions, component diffs, causal reason DAG, and `MAY_RUN`. |
| `cache.py` | Verified action records, manifests, objects, bundles, state, and publication links. |
| `publication.py` | Staging-tree validation and canonical artifact manifests. |
| `executor.py` | Sequential refinement, trusted subprocesses, deterministic checks, and publication. |
| `cli.py` | Stable JSON envelopes and human rendering. |

## Planning flow

1. Parse the complete pipeline and validate all artifact edges before cache mutation.
2. Load only verified per-task baselines.
3. Apply requested overlays through a virtual workspace view.
4. Hash concrete tasks in deterministic topological order.
5. Compare snapshot components with the verified baseline and emit leaf reasons.
6. Reuse a proposed action only if its action record, manifest, and every object verify.
7. Propagate unknown producer content as `MAY_RUN`, linking the consumer reason to the producer's
   direct reason keys.
8. Canonically order tasks and reason nodes before deriving the report ID.

## Execution flow

`run` replans before each task. This is intentional: after a producer executes, the real digest of
each artifact becomes available, so a downstream `MAY_RUN` can refine to `HIT`, `RESTORE`, or `RUN`.

For a cache miss, the executor:

1. creates a staging directory below `.rebuildwhy/tmp/`;
2. writes a canonical context document and sets `REBUILDWHY_CONTEXT`;
3. invokes the exact argument vector with `shell=False`;
4. validates all required outputs and rejects links or special files;
5. optionally repeats the command in an independent staging directory;
6. stores verified immutable file objects and a canonical manifest;
7. writes the complete action record;
8. atomically switches the managed publication symlink; and
9. updates the task's current state record.

The action record precedes publication because it references a complete, verified immutable bundle.
A crash at that boundary may leave a recoverable cache result, but never exposes a partial bundle.

## On-disk layout

```text
.rebuildwhy/
├── actions/<action-key-hex>.json
├── artifacts/<manifest-digest-hex>/...
├── manifests/<manifest-digest-hex>.json
├── objects/sha256/<file-digest-hex>
├── quarantine/
├── state/<task-id>.json
└── tmp/
```

Publication paths in the project are symbolic links to immutable artifact bundles. RebuildWhy will
replace only a symbolic link it manages; an existing regular file or directory is a hard error.

## Deliberate V1 limits

V1 is sequential and local. It has no dynamic graph, remote cache, scheduler, retry engine,
sandbox, file-access tracing, or multi-process locking. Atomic visibility assumes the cache,
staging area, and publication link are on one local POSIX filesystem.
