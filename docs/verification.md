# Verification and Acceptance Matrix

This document maps RebuildWhy's public engineering claims to executable evidence. The test suite
uses only synthetic data and temporary project copies; it does not require patient data, services,
containers, or a remote cache.

## Automated gates

The GitHub Actions matrix runs every gate on Python 3.11, 3.12, and 3.13:

```bash
python -m ruff check src tests examples
python -m ruff format --check src tests examples
python -m mypy
python -m pytest --cov=rebuildwhy --cov-branch --cov-report=term-missing --cov-fail-under=80
python -m build
python -m pip install --force-reinstall dist/*.whl
python -m pip check
rebuildwhy --version
```

`mypy` uses strict mode across the package, tests, and example tasks. Coverage includes branches
and must remain at or above 80 percent. Distribution construction produces both an sdist and wheel;
the source distribution includes the documentation, schemas, examples, and tests, while the wheel
includes the public schemas and the PEP 561 `py.typed` marker. CI reinstalls the built wheel and
executes the console entry point so source-tree success cannot mask a broken distribution.

## Claim-to-test traceability

| Claim or failure mode | Executable evidence |
|---|---|
| Deterministic DAG order and cycle rejection | `test_load_pipeline_returns_deterministic_topological_order`, `test_topological_order_uses_task_id_as_stable_tie_breaker`, `test_cycle_is_rejected` |
| Missing tasks or undeclared producer outputs fail before execution | `test_missing_task_dependency_is_rejected`, `test_undeclared_producer_output_is_rejected` |
| Paths cannot escape the project or enter engine state | `test_path_escape_is_rejected`, `test_pipeline_schema_rejects_reserved_paths_and_bad_pointer_escapes` |
| First run executes; identical second run is five verified hits | `test_full_run_then_every_task_is_a_hit` |
| Relevant field-level config change invalidates only the causal subgraph | `test_relevant_overlay_is_causal_and_does_not_mutate_source` |
| Unrelated config change produces no invalidation and stable JSON | `test_irrelevant_overlay_keeps_all_hits_and_json_is_stable` |
| File overlays hash replacement bytes without mutating the source | `test_file_overlay_uses_replacement_bytes_without_mutation` |
| Command and environment contract changes are explained | `test_changed_command_is_explained`, `test_changed_environment_contract_is_explained` |
| Unchanged artifact bytes allow downstream reuse after a producer rerun | `test_changed_producer_with_same_artifact_keeps_downstream_hits` |
| Missing publication is restored without command execution | `test_missing_publication_is_restored_without_execution` |
| Corrupt or missing cache objects are never reused | `test_corrupt_object_is_not_reused`, `test_missing_object_is_not_reused` |
| Symlinked cache metadata and objects are rejected | `test_symlinked_action_record_is_not_reused`, `test_symlinked_cache_object_is_not_reused` |
| Incomplete or internally inconsistent action records are never reused | `test_incomplete_action_record_is_not_reused`, `test_action_snapshot_must_match_its_key` |
| Managed publication never overwrites an unmanaged path | `test_regular_output_path_is_never_overwritten` |
| Missing outputs and command failures expose no partial replacement | `test_missing_required_output_preserves_no_partial_publication`, `test_failed_rebuild_keeps_previous_publication` |
| Injected failures preserve the last publication or a recoverable action | `test_failpoint_before_action_record_keeps_previous_publication`, `test_failpoint_before_publish_leaves_recoverable_action` |
| Double-run validation accepts deterministic tasks and rejects unstable output | `test_determinism_check_runs_twice_and_accepts_demo_task`, `test_determinism_check_rejects_nondeterministic_task` |
| Public schemas are valid and real CLI reports conform | `test_schema_is_valid_draft_2020_12`, `test_cli_plan_and_run_reports_match_public_schemas`, `test_cli_error_report_matches_public_schema` |
| Every non-hit plan decision carries a reason | `test_plan_schema_requires_reasons_for_non_hit_decisions` |
| CLI success and failure payloads are structured JSON | `test_plan_json_is_machine_readable`, `test_structured_json_error` |
| Human CLI output remains readable | `test_human_plan_and_run_are_readable`, `test_human_error_is_readable` |
| Package version and console entry-point metadata stay consistent | `test_runtime_version_matches_distribution_metadata`, `test_console_entry_point_is_published` |

## Manual fresh-install smoke test

After `python -m build`, install the wheel into a fresh virtual environment and run:

```bash
rebuildwhy --version
rebuildwhy plan -p examples/synthetic_mri/pipeline.yaml --json
```

The first command confirms the console entry point and packaged version. The second confirms that a
fresh installation can load the public example and emit a machine-readable plan without executing
pipeline commands.
