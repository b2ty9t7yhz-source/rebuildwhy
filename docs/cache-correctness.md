# Cache Correctness

## Conditional reuse theorem

For task `t`, let `S(t)` be its canonical declared-input snapshot and let
`K(t) = SHA256(canonical_json(S(t)))`. RebuildWhy reuses an output only if a complete action record
for `K(t)` exists and its manifest and all referenced file objects verify.

If the task is deterministic and depends only on values represented in `S(t)`, equal action keys
identify safely reusable output. This is a conditional guarantee, not automatic hermeticity.

## Verification chain

A `HIT` or `RESTORE` requires the complete chain below:

```text
computed action key
  -> matching complete action record
    -> SHA-256-addressed canonical manifest
      -> every SHA-256-addressed file object with matching size and bytes
```

A missing or malformed action record, missing/corrupt manifest, or missing/corrupt object breaks the
chain. The planner emits a stable reason code and selects safe recomputation. Cache filenames alone
are never trusted.

## Publication and restoration

Immutable artifact bundles are materialized from verified objects. A task's visible output is an
atomic symbolic-link replacement pointing at one bundle. If the cache is valid but this link is
missing or points elsewhere, the task is `RESTORE`: no command execution is required.

An unmanaged regular path is never deleted or overwritten. Failed commands, unsupported output
types, missing required files, manifest differences during a determinism check, and injected
failures before publication leave the previous managed link intact.

## Failure ordering

The write order is:

1. immutable file objects;
2. canonical manifest;
3. immutable materialized bundle;
4. complete action record;
5. publication link;
6. current task state.

Before step 4, partial cache data is unreachable by a complete action record. Between steps 4 and 5,
the action is complete and can be restored later. Between steps 5 and 6, the new complete publication
is visible; a later plan can rediscover the same action from declared inputs even if current state is
stale.

## Integrity recovery

When execution encounters a corrupt object or metadata file at an address it needs to recreate, the
old path is atomically moved into `.rebuildwhy/quarantine/` before verified content replaces it.
Quarantine is diagnostic local data; V1 does not provide garbage collection or repair commands.

## Executable state and output types

Manifests record relative path, SHA-256 digest, byte size, and executable-bit state. Output trees may
contain only directories and regular files. Symbolic links, sockets, devices, and other special files
are rejected before an action record can be completed.
