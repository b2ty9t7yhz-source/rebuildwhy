# Changelog

All notable changes to RebuildWhy are documented in this file. The project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2] - 2026-08-13

### Added

- Contract tests for package metadata, installed schemas, and real CLI plan, run, and error
  reports.
- A verification matrix connecting public correctness and security claims to automated tests.
- Installed-wheel smoke coverage for the executable synthetic MRI plan.

### Changed

- Hardened cache lookup against symlinked records and manifests escaping the managed cache root.
- Tightened structured report schemas and kept schema-version requirements consistent across
  successful and error responses.
- Extended strict typing and test discovery across source, tests, and examples.
- Replaced the example's placeholder dependency lock with an explicit runtime-contract input.
- Strengthened source and wheel distribution checks for documentation, schemas, entry points, and
  PEP 561 metadata.
- Excluded generated example cache and publication directories from source distributions.

## [0.1.1] - 2026-08-10

### Added

- A Draft 2020-12 schema for structured JSON error envelopes.
- Integration tests that validate the bundled pipeline and real current, counterfactual, run, and
  error reports against their published schemas.

### Changed

- Tightened path, digest, task ID, reason code, reason ID, and decision/reason invariants in the V1
  schemas.
- Replaced unowned schema identifiers with stable, network-independent URN identifiers.
- Included all schemas and their documentation in the source distribution.

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

[0.1.2]: https://github.com/b2ty9t7yhz-source/rebuildwhy/releases/tag/v0.1.2
[0.1.1]: https://github.com/b2ty9t7yhz-source/rebuildwhy/releases/tag/v0.1.1
[0.1.0]: https://github.com/b2ty9t7yhz-source/rebuildwhy/releases/tag/v0.1.0
