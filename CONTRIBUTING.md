# Contributing

## Local Setup

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Quality Gates

Run these before opening a pull request:

```bash
ruff check videovector tests examples
mypy videovector
pytest -q tests
python -m build
python -m twine check dist/*
```

## Public SDK Rules

- Keep this repository SDK-only. Do not add backend, MCP, frontend, deployment, billing, or internal operations code.
- Do not hardcode credentials or customer-specific identifiers in tests, docs, or examples.
- Prefer environment variables for examples and integration snippets.
- Keep request retries explicit for non-idempotent writes by using `idempotency_key` when safe.
- Update `docs/backend-parity-matrix.md` whenever SDK endpoint coverage changes.

## Release Notes

User-visible SDK changes must update `CHANGELOG.md` with migration notes where relevant.

