# Release Process

Releases are automation-driven from the public repository. Do not create or push
release tags from a personal workstation or personal GitHub account.

1. Update `videovector/_version.py`, `pyproject.toml`, and `CHANGELOG.md`.
2. Run local checks:

   ```bash
   ruff check videovector tests examples
   mypy videovector
   pytest -q tests
   python -m build
   python -m twine check dist/*
   ```

3. Dispatch the `Release` workflow from GitHub Actions with the exact version,
   for example `1.0.1`.

4. The workflow verifies the version metadata, builds artifacts, publishes to
   TestPyPI, smoke-installs from TestPyPI, publishes to PyPI through trusted
   publishing, then creates the `videovector-vX.Y.Z` GitHub release tag.

The package must use GitHub OIDC trusted publishing. Do not store long-lived
PyPI API tokens in repository secrets. The trusted publishers should target
`.github/workflows/release.yml` with the `testpypi` and `pypi` environments.
