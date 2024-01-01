# Release Process

Releases are orchestrated by `vectormethods-public-bot` from the private control
repository. Do not create or push release tags from a personal workstation,
personal GitHub account, or a manual public workflow dispatch.

1. Update `videovector/_version.py`, `pyproject.toml`, and `CHANGELOG.md`.
2. Run local checks:

   ```bash
   python -m pip install --upgrade pip==25.3
   python -m pip install --require-hashes -r requirements-dev.lock
   python -m pip install --no-deps --no-build-isolation -e .
   ruff check videovector tests examples
   mypy videovector
   pytest -q tests
   python -m build --no-isolation
   python -m twine check dist/*
   ```

3. Run the private `Public Repo Bot` workflow in `release` mode for this
   repository. The tag must match `videovector-vX.Y.Z` and target public `main`.
4. The bot verifies the public graph, creates or verifies the public tag,
   dispatches this repository's `Release` workflow, waits for registry publish
   and install smoke tests to pass, then creates the GitHub Release with scanned
   release text and generated notes disabled.

## Immutable release bundle and resume contract

The workflow builds the wheel and sdist once from the release tag. Archive
timestamps are normalized to the source commit timestamp and the complete
bundle is uploaded between jobs. `release-manifest.json` binds the source and
tag SHA, canonical source repository, release-body hash, artifact hashes,
expected registry metadata hash, and exact tool versions.

TestPyPI and PyPI publication jobs always download that tested bundle; they
never rebuild it. A pre-existing version is successful only when its complete
filename, size, type, SHA-256, package version, and `Requires-Python` metadata
match the manifest. Missing versions publish the bundle and are polled until
the same exact comparison passes. Conflicting existing versions fail closed.
If a registry accepted only one artifact before a runner failed, the next
attempt verifies that artifact and uploads only the missing file.
Re-running a failed publication job therefore resumes from the previously
uploaded bundle without rebuilding or re-uploading an already exact registry.

The public bot must verify that the GitHub Release tag and body hash equal the
manifest before attaching the manifest to the release. Generated release notes
remain disabled because they are not covered by the scanned body hash.

The package must use GitHub OIDC trusted publishing. Do not store long-lived
PyPI API tokens in repository secrets. The trusted publishers should target
`.github/workflows/release.yml` with the `testpypi` and `pypi` environments.

`requirements-dev.lock` is the canonical Python 3.9–3.12 CI and release
toolchain. Regenerate it only after reviewing dependency updates, with the
exact command recorded in its header and `uv==0.11.29`; never hand-edit hashes.
The release builder uses `--no-isolation`, so the build frontend and backend
versions recorded in the manifest are the same hash-locked versions that
produced the artifacts.
