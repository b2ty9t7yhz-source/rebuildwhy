# Contributing

RebuildWhy welcomes focused bug fixes, tests, and documentation improvements that preserve its
narrow V1 contract: a transparent, single-process reference implementation for trusted local task
pipelines.

## Development setup

RebuildWhy requires Python 3.11 or newer.

```bash
git clone https://github.com/b2ty9t7yhz-source/rebuildwhy.git
cd rebuildwhy
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
```

Run the same quality gates enforced by GitHub Actions:

```bash
.venv/bin/python -m ruff check src tests examples
.venv/bin/python -m ruff format --check src tests examples
.venv/bin/python -m mypy
.venv/bin/python -m pytest --cov=rebuildwhy --cov-branch --cov-report=term-missing --cov-fail-under=80
.venv/bin/python -m build
```

## Change guidelines

- Add or update tests for externally observable behavior and correctness boundaries.
- Keep reports deterministic: ordering, reason identifiers, and canonical JSON are public contracts.
- Preserve stable error and reason codes when possible.
- Document any change to action-key inputs, artifact verification, or publication semantics.
- Keep generated `.rebuildwhy/`, `outputs/`, `build/`, and `dist/` content out of commits.
- Never commit secrets, patient data, personal identifiers, machine-specific paths, or credentials.

The project deliberately excludes remote execution, distributed caches, concurrent writers, dynamic
dependency discovery, and a web interface from V1. Proposals in those areas should begin with a
scope and correctness discussion rather than an implementation.

## Pull requests

Keep each pull request small enough to explain and review. Include the user-visible problem, the
chosen correctness rule, tests performed, and any compatibility impact. All CI jobs must pass before
merge.

Security-sensitive behavior should be evaluated against
[`docs/security-and-trust-boundary.md`](docs/security-and-trust-boundary.md). Do not include secrets or
private data in a public issue.
