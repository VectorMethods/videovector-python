from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import tarfile
import zipfile
from argparse import Namespace
from importlib import metadata as importlib_metadata
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from packaging.requirements import Requirement

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9 and 3.10
    import tomli as tomllib


def _release_module() -> ModuleType:
    script = Path(__file__).parents[1] / "scripts" / "release_artifacts.py"
    spec = importlib.util.spec_from_file_location("release_artifacts", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _release_module()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_bundle(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    bundle = tmp_path / "bundle"
    dist = bundle / "dist"
    dist.mkdir(parents=True)
    wheel = dist / "package-1.0-py3-none-any.whl"
    sdist = dist / "package-1.0.tar.gz"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "package-1.0.dist-info/METADATA",
            "Name: package\nVersion: 1.0\nRequires-Python: >=3.9\n",
        )
        archive.writestr("package/__init__.py", "")
    with tarfile.open(sdist, "w:gz") as archive:
        payload = b"Name: package\nVersion: 1.0\nRequires-Python: >=3.9\n"
        metadata = tarfile.TarInfo("package-1.0/PKG-INFO")
        metadata.size = len(payload)
        archive.addfile(metadata, io.BytesIO(payload))

    def descriptor(path: Path, package_type: str) -> dict[str, Any]:
        return {
            "filename": path.name,
            "path": f"dist/{path.name}",
            "packagetype": package_type,
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }

    descriptors = [
        descriptor(wheel, "bdist_wheel"),
        descriptor(sdist, "sdist"),
    ]
    metadata = {
        "schema_version": release.SCHEMA_VERSION,
        "package": {"name": "package", "version": "1.0", "requires_python": ">=3.9"},
        "artifacts": [
            {key: descriptor[key] for key in ("filename", "packagetype", "sha256", "size")}
            for descriptor in descriptors
        ],
    }
    metadata_path = bundle / "registry-metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": release.SCHEMA_VERSION,
        "package": {"name": "package", "version": "1.0"},
        "repository": "VectorMethods/videovector-python",
        "source_sha": "a" * 40,
        "tag": "videovector-v1.0",
        "tag_sha": "a" * 40,
        "source_date_epoch": 1_700_000_000,
        "release_body_sha256": "b" * 64,
        "registry_metadata_path": metadata_path.name,
        "registry_metadata_sha256": _sha256(metadata_path),
        "artifacts": descriptors,
        "image_digest": None,
        "tool_versions": {
            "python": "3.12.8",
            "build": "1.4.4",
            "setuptools": "80.10.2",
            "twine": "6.2.0",
            "uv": "0.11.29",
            "wheel": "0.47.0",
        },
    }
    (bundle / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle, metadata


def test_wheel_timestamp_normalization_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.whl"
    second = tmp_path / "second.whl"
    with zipfile.ZipFile(first, "w") as archive:
        archive.writestr("package/value.py", "VALUE = 1\n")
        archive.writestr("package-1.0.dist-info/METADATA", "Name: package\nVersion: 1.0\n")
    with zipfile.ZipFile(second, "w") as archive:
        archive.writestr("package-1.0.dist-info/METADATA", "Name: package\nVersion: 1.0\n")
        archive.writestr("package/value.py", "VALUE = 1\n")

    release.normalize_wheel(first, 1_700_000_000)
    release.normalize_wheel(second, 1_700_000_000)

    assert first.read_bytes() == second.read_bytes()


def test_release_tool_provenance_records_uv_without_requiring_pip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = {
        "build": "1.4.4",
        "setuptools": "80.10.2",
        "twine": "6.2.0",
        "wheel": "0.47.0",
    }

    def distribution_version(name: str) -> str:
        assert name != "pip"
        return versions[name]

    monkeypatch.setattr(release.importlib_metadata, "version", distribution_version)
    monkeypatch.setattr(
        release.shutil, "which", lambda name: "/reviewed/uv" if name == "uv" else None
    )
    monkeypatch.setattr(
        release,
        "_run",
        lambda command, **_kwargs: (
            "uv 0.11.29 (901092ee1 2026-07-15 aarch64-apple-darwin)"
            if tuple(command) == ("/reviewed/uv", "--version")
            else pytest.fail(f"unexpected command: {command}")
        ),
    )

    assert release._tool_versions() == {
        "python": release.sys.version.split()[0],
        **versions,
        "uv": "0.11.29",
    }


def test_bundle_verification_requires_uv_provenance(tmp_path: Path) -> None:
    bundle, _metadata = _fake_bundle(tmp_path)
    manifest_path = bundle / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tool_versions"]["pip"] = "25.3"
    del manifest["tool_versions"]["uv"]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(release.ReleaseArtifactError, match="tool versions are incomplete"):
        release.verify_bundle(bundle)


def test_bundle_verification_fails_closed_after_artifact_tampering(
    tmp_path: Path,
) -> None:
    bundle, _metadata = _fake_bundle(tmp_path)
    wheel = bundle / "dist/package-1.0-py3-none-any.whl"

    release.verify_bundle(bundle)
    wheel.write_bytes(b"tampered")
    with pytest.raises(release.ReleaseArtifactError, match="size mismatch|hash mismatch"):
        release.verify_bundle(bundle)


def test_bundle_verification_rejects_noncanonical_paths_and_metadata(
    tmp_path: Path,
) -> None:
    bundle, _metadata = _fake_bundle(tmp_path)
    manifest_path = bundle / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["path"] = "dist/../release-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(release.ReleaseArtifactError, match="path is invalid"):
        release.verify_bundle(bundle)

    bundle, metadata = _fake_bundle(tmp_path / "metadata")
    metadata["package"]["requires_python"] = ">=3.12"
    metadata_path = bundle / "registry-metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path = bundle / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["registry_metadata_sha256"] = _sha256(metadata_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(release.ReleaseArtifactError, match="registry metadata differs"):
        release.verify_bundle(bundle)


def test_partial_registry_state_resumes_with_only_missing_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, metadata = _fake_bundle(tmp_path)
    existing = metadata["artifacts"][0]
    payload = {
        "info": {
            "name": "package",
            "version": "1.0",
            "requires_python": ">=3.9",
        },
        "urls": [
            {
                **existing,
                "digests": {"sha256": existing["sha256"]},
            }
        ],
    }

    class Response(io.BytesIO):
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: Response(json.dumps(payload).encode()),
    )
    pending = tmp_path / "pending"
    status = release.registry_status(
        Namespace(
            bundle=str(bundle),
            registry="pypi",
            base_url="https://registry.invalid",
            timeout=1.0,
            write_missing=str(pending),
        )
    )

    assert status == 4
    assert [path.name for path in pending.iterdir()] == ["package-1.0.tar.gz"]


def test_registry_projection_requires_exact_artifact_metadata() -> None:
    projected = release._registry_projection(
        {
            "info": {
                "name": "videovector",
                "version": "1.1.0",
                "requires_python": ">=3.9",
            },
            "urls": [
                {
                    "filename": "videovector-1.1.0.tar.gz",
                    "packagetype": "sdist",
                    "size": 10,
                    "digests": {"sha256": "c" * 64},
                }
            ],
        }
    )

    assert projected["artifacts"] == [
        {
            "filename": "videovector-1.1.0.tar.gz",
            "packagetype": "sdist",
            "size": 10,
            "sha256": "c" * 64,
        }
    ]


def test_hash_lock_matches_exact_build_and_development_toolchain() -> None:
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock_text = (root / "requirements-dev.lock").read_text(encoding="utf-8")
    locked = {
        re.sub(r"[-_.]+", "-", match.group("name")).lower(): match.group("version")
        for line in lock_text.splitlines()
        if (
            match := re.fullmatch(
                r"(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^ ;\\]+)(?:\s.*)?",
                line,
            )
        )
    }

    exact_requirements = [
        *project["build-system"]["requires"],
        *project["project"]["optional-dependencies"]["dev"],
    ]
    for raw_requirement in exact_requirements:
        requirement = Requirement(raw_requirement)
        specifiers = list(requirement.specifier)
        assert len(specifiers) == 1 and specifiers[0].operator == "==", raw_requirement
        normalized_name = re.sub(r"[-_.]+", "-", requirement.name).lower()
        assert locked[normalized_name] == specifiers[0].version

    for raw_requirement in project["project"]["dependencies"]:
        requirement = Requirement(raw_requirement)
        installed_version = importlib_metadata.version(requirement.name)
        assert requirement.specifier.contains(installed_version)
        normalized_name = re.sub(r"[-_.]+", "-", requirement.name).lower()
        assert locked[normalized_name] == installed_version


def test_release_jobs_checkout_the_guarded_source_sha() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("ref: refs/tags/${{ inputs.release_tag }}") == 1
    assert workflow.count("ref: ${{ needs.guard.outputs.source_sha }}") == 5
    assert re.search(
        r"expected_target_sha:\s+"
        r'description: "Exact commit SHA peeled from the immutable bot-created release tag"\s+'
        r"required: true\s+type: string",
        workflow,
    )
    assert "EXPECTED_TARGET_SHA: ${{ inputs.expected_target_sha }}" in workflow
    assert workflow.count("bash scripts/validate_release_request.sh") == 1
    assert "git fetch --no-tags origin +refs/heads/main" not in workflow
    assert "refs/remotes/origin/main" not in workflow


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _release_guard_fixture(tmp_path: Path) -> tuple[Path, dict[str, str], str, str]:
    root = tmp_path / "release-repository"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "VectorMethods Engineering")
    _git(root, "config", "user.email", "opensource@vectormethods.com")
    (root / "release.txt").write_text("release\n", encoding="utf-8")
    _git(root, "add", "release.txt")
    _git(root, "commit", "-m", "release")
    release_sha = _git(root, "rev-parse", "HEAD")
    release_tag = "videovector-v1.2.3"
    _git(root, "tag", "-a", release_tag, "-m", "release")
    (root / "release.txt").write_text("main advanced\n", encoding="utf-8")
    _git(root, "commit", "-am", "advance main")
    moving_main_sha = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "--detach", release_sha)

    output = tmp_path / "github-output"
    environment = {
        **os.environ,
        "EXPECTED_TARGET_SHA": release_sha,
        "GITHUB_ACTOR": "vectormethods-public-bot[bot]",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REF": f"refs/tags/{release_tag}",
        "GITHUB_SHA": release_sha,
        "RELEASE_BODY_SHA256": "b" * 64,
        "RELEASE_TAG": release_tag,
        "RELEASE_TAG_PREFIX": "videovector-v",
    }
    return root, environment, release_sha, moving_main_sha


def test_release_guard_peels_tag_and_ignores_moving_main(tmp_path: Path) -> None:
    root, environment, release_sha, moving_main_sha = _release_guard_fixture(tmp_path)

    assert moving_main_sha != release_sha
    subprocess.run(
        ("bash", str(Path(__file__).parents[1] / "scripts/validate_release_request.sh")),
        cwd=root,
        env=environment,
        check=True,
    )

    output = Path(environment["GITHUB_OUTPUT"]).read_text(encoding="utf-8")
    assert f"source_sha={release_sha}\n" in output
    assert "version=1.2.3\n" in output


@pytest.mark.parametrize(
    "expected_sha",
    [
        "A" * 40,
        "a" * 39,
        "a" * 41,
        "not-a-commit",
    ],
)
def test_release_guard_rejects_malformed_expected_sha(
    tmp_path: Path,
    expected_sha: str,
) -> None:
    root, environment, _, _ = _release_guard_fixture(tmp_path)
    environment["EXPECTED_TARGET_SHA"] = expected_sha

    result = subprocess.run(
        ("bash", str(Path(__file__).parents[1] / "scripts/validate_release_request.sh")),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "expected_target_sha must be a full lowercase 40-character Git commit SHA" in (
        result.stderr
    )


def test_release_guard_rejects_wrong_expected_sha(tmp_path: Path) -> None:
    root, environment, _, moving_main_sha = _release_guard_fixture(tmp_path)
    environment["EXPECTED_TARGET_SHA"] = moving_main_sha

    result = subprocess.run(
        ("bash", str(Path(__file__).parents[1] / "scripts/validate_release_request.sh")),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "must match exactly" in result.stderr


def test_release_installs_only_with_the_reviewed_uv_binary() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("run: bash scripts/install_reviewed_uv.sh") == 3
    assert "python -m pip install" not in workflow
    assert "bin/python -m pip install" not in workflow
    assert workflow.count("python -m venv --without-pip") == 3
    assert "uv pip uninstall" in workflow
    assert "python -m pip --version" in workflow


def test_ci_and_release_gate_all_maintained_python_sources() -> None:
    root = Path(__file__).parents[1]
    expected_commands = {
        "ruff check videovector tests examples scripts",
        "black --check videovector tests examples scripts",
        "mypy videovector scripts/release_artifacts.py",
    }

    for workflow_name in ("ci.yml", "release.yml"):
        workflow = (root / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        for command in expected_commands:
            assert command in workflow
