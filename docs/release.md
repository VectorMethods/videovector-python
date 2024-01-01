# Release Process

Releases are tag-driven.

1. Update `videovector/_version.py`, `pyproject.toml`, and `CHANGELOG.md`.
2. Run local checks:

   ```bash
   ruff check videovector tests examples
   mypy videovector
   pytest -q tests
   python -m build
   python -m twine check dist/*
   ```

3. Create and push a release tag:

   ```bash
   git tag videovector-vX.Y.Z
   git push origin videovector-vX.Y.Z
   ```

4. GitHub Actions builds, publishes to TestPyPI, smoke-installs from TestPyPI, then publishes to PyPI through trusted publishing.

The package should use GitHub OIDC trusted publishing. Do not store long-lived PyPI API tokens in repository secrets.

