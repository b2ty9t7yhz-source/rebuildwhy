# Versioned JSON schemas

RebuildWhy publishes Draft 2020-12 JSON Schemas for its declarative pipeline input and every JSON
CLI envelope:

| Schema | Contract |
|---|---|
| `pipeline-v1.schema.json` | Syntactic shape of a V1 YAML/JSON pipeline after parsing. |
| `plan-report-v1.schema.json` | Current and counterfactual plan reports. |
| `run-report-v1.schema.json` | Run and determinism-check reports. |
| `error-report-v1.schema.json` | Structured errors written to standard error with `--json`. |

Each contract has an immutable `urn:rebuildwhy:schema:*:v1` identifier and uses only internal
references, so validation never depends on a network fetch.

The integration suite first checks that each document is itself a valid Draft 2020-12 schema. It
then validates the bundled synthetic pipeline and reports produced by real planner, executor, and
error code paths. This prevents the documented contracts from drifting silently away from emitted
data.

The pipeline schema covers portable document structure. Runtime validation remains authoritative
for semantic constraints that JSON Schema cannot express cleanly, including DAG acyclicity,
producer/output references, overlapping publication paths, source-file existence, and JSON Pointer
resolution. Passing the schema alone does not make a pipeline safe to execute; commands remain
trusted local code.
