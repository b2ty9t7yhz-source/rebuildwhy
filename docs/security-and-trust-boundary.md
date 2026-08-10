# Security and Trust Boundary

## Trusted commands

Pipeline commands are trusted local code. RebuildWhy uses an exact argument vector with
`shell=False`, which avoids implicit shell parsing, but it is not a sandbox. A command has the same
filesystem, network, and process privileges as the user running RebuildWhy.

Do not use RebuildWhy to execute unreviewed pipeline files or commands.

## Declared-input boundary

The cache key covers only declared data. Correctness does not automatically include:

- undeclared files or environment variables;
- wall-clock time, locale, randomness, process IDs, or temporary host state;
- network responses or external services;
- interpreter, package, native-library, driver, or operating-system changes unless declared through
  a lock file or another explicit input; or
- hardware-specific numerical behavior.

The two-run determinism check detects differing manifests in two immediate isolated executions. It
does not prove determinism for every host, time, or hidden state.

## Paths and file types

Pipeline logical paths must be relative POSIX paths without `..`, and `.rebuildwhy/` is reserved.
Source inputs must be regular files rather than links. Artifact outputs reject symbolic links and
all special file types. Publication directories may not overlap or act as direct source inputs.

These validations reduce accidental path confusion. They do not make a malicious command safe.

## Metadata and secrets

Environment values enter action snapshots only through digests. Selected config values are retained
in local action snapshots and causal reports so V1 can show old/new explanations. Therefore:

- do not select secret-bearing config fields;
- do not publish plan JSON without reviewing it; and
- protect `.rebuildwhy/` with the same permissions as the project workspace.

RebuildWhy is not a secrets manager and does not redact V1 config explanations.

## Local cache trust

Reusable bytes are verified by SHA-256 and sizes before use. This detects accidental corruption and
ordinary tampering; it is not an authenticity or authorization system. Anyone able to modify the
pipeline, source inputs, cache, or task commands is inside the V1 trust boundary.

V1 has no multi-process lock. Do not run two writers against the same project cache concurrently.
The supported deployment is one user, one process, one local POSIX filesystem.
