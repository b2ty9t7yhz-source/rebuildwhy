# Counterfactual Planning

## Virtual changes

`plan` accepts two overlay forms:

```text
--set FILE#JSON_POINTER=JSON_VALUE
--replace-file LOGICAL_FILE=REPLACEMENT_FILE
```

Config documents are parsed once per plan, copied, and changed in memory. A file replacement changes
which regular file is hashed under the original logical locator. Neither source path is written.

An overlaid config file must be declared by at least one task, but the pointer itself may be
undeclared. This is necessary to demonstrate irrelevant-field stability: changing an unselected
field has no action-key effect. The pointer must still resolve to an existing value.

## Direct reasons

The planner compares a proposed snapshot with the most recent verified baseline. Stable reason codes
identify the exact changed component:

- `FILE_CONTENT_CHANGED`
- `CONFIG_FIELD_CHANGED`
- `COMMAND_CHANGED`
- `ENVIRONMENT_CHANGED`
- `OUTPUT_CONTRACT_CHANGED`
- `UPSTREAM_ARTIFACT_CHANGED`

Config reasons retain old and new values for the synthetic V1 explanation. Other components report
digests. A task with no verified baseline receives `NEW_TASK`; invalid cache metadata has a specific
cache reason instead.

## Why `MAY_RUN` exists

Suppose `resample` has a new action key, and `normalize` consumes `resample:image.json`. Before
`resample` executes, the planner cannot know the future digest of `image.json`. Marking `normalize`
as `RUN` would make an unsupported claim: the changed producer may create identical image bytes.

The causal report therefore represents:

```text
resample RUN
└── CONFIG_FIELD_CHANGED config/pipeline.yaml#/image/spacing

normalize MAY_RUN
└── UPSTREAM_ARTIFACT_MAY_CHANGE resample:image.json
    └── caused by the resample config reason
```

During actual execution, RebuildWhy replans after `resample`. If `image.json` has the old content
digest, `normalize` keeps its old action key and is a `HIT`. If the digest changes, a concrete new
action key is checked for `HIT`/`RESTORE` before execution becomes `RUN`.

## Deterministic report identity

Tasks follow stable topological order. Component arrays, reasons, cause edges, and JSON object keys
have canonical ordering. Reason IDs are assigned from stable hashes of reason bodies, and `plan_id`
is the digest of the report before the ID field is inserted. Identical inputs and cache state produce
byte-identical compact JSON output.

## Minimality boundary

The affected task set includes direct changed tasks and only consumers reachable through declared
artifact edges. It is minimal relative to the declared graph. RebuildWhy cannot represent or protect
an undeclared runtime dependency.
