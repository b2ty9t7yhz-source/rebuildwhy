# Changelog

All notable changes to RebuildWhy are documented in this file. The project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-10

### Added

- Declarative local DAG pipelines with regular-file, selected YAML/JSON field, environment, command,
  artifact, and output-contract inputs.
- Canonical SHA-256 action keys separated from content-addressed artifact manifests and objects.
- Human-readable and canonical JSON plans with `HIT`, `RESTORE`, `RUN`, and causally nested
  `MAY_RUN` decisions.
- Non-mutating `--set` and `--replace-file` counterfactual overlays.
- Integrity verification for action records, manifests, cached objects, and managed publications.
- Isolated staging, required-output checks, atomic cache publication, and atomic workspace links.
- Runtime refinement that can resolve a downstream `MAY_RUN` to `HIT` when changed producer actions
  emit identical consumed bytes.
- Opt-in two-run deterministic-output verification.
- Executable five-stage synthetic MRI example and correctness/trust-boundary documentation.
- Strict static typing, PEP 561 metadata, branch-coverage enforcement, Python 3.11-3.13 CI, and clean
  wheel-install smoke tests.

[0.1.0]: https://github.com/b2ty9t7yhz-source/rebuildwhy/releases/tag/v0.1.0
