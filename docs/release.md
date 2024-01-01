# Release Process

Releases are orchestrated by `vectormethods-public-bot` from the private control
repository. Do not create or push release tags from a personal workstation,
personal GitHub account, or a manual public workflow dispatch.

1. Update `videovector/_version.py`, `pyproject.toml`, and `CHANGELOG.md`.
2. Run local checks:

   ```bash
   ruff check videovector tests examples
   mypy videovector
   pytest -q tests
   python -m build
   python -m twine check dist/*
   ```

3. Run the private `Public Repo Bot` workflow in `release` mode for this
   repository. The tag must match `videovector-vX.Y.Z` and target public `main`.
4. The bot verifies the public graph, creates or verifies the public tag,
   dispatches this repository's `Release` workflow, waits for registry publish
   and install smoke tests to pass, then creates the GitHub Release with scanned
   release text and generated notes disabled.

The package must use GitHub OIDC trusted publishing. Do not store long-lived
PyPI API tokens in repository secrets. The trusted publishers should target
`.github/workflows/release.yml` with the `testpypi` and `pypi` environments.
