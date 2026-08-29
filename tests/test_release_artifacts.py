from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import tarfile
import urllib.error
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


class _HttpResponse(io.BytesIO):
    headers: dict[str, str]

    def __init__(self, value: bytes, url: str) -> None:
        super().__init__(value)
        self._url = url
        self.headers = {"Content-Length": str(len(value))}

    def __enter__(self) -> "_HttpResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def geturl(self) -> str:
        return self._url


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_bundle(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    bundle = tmp_path / "bundle"
    dist = bundle / "dist"
    dist.mkdir(parents=True)
    wheel = dist / "videovector-1.2.3-py3-none-any.whl"
    sdist = dist / "videovector-1.2.3.tar.gz"
    wheel_files = {
        "videovector-1.2.3.dist-info/METADATA": (
            b"Name: videovector\nVersion: 1.2.3\nRequires-Python: >=3.9\n"
        ),
        "videovector-1.2.3.dist-info/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: test\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n"
        ),
        "videovector/__init__.py": b"from ._version import __version__\n",
        "videovector/_version.py": b'__version__ = "1.2.3"\n',
    }
    record_lines = []
    for name, payload in wheel_files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
        record_lines.append(f"{name},sha256={digest.decode()},{len(payload)}")
    record_lines.append("videovector-1.2.3.dist-info/RECORD,,")
    wheel_files["videovector-1.2.3.dist-info/RECORD"] = ("\n".join(record_lines) + "\n").encode()
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, payload in wheel_files.items():
            archive.writestr(name, payload)
    with tarfile.open(sdist, "w:gz") as archive:
        sdist_files = {
            "videovector-1.2.3/PKG-INFO": (
                b"Name: videovector\nVersion: 1.2.3\nRequires-Python: >=3.9\n"
            ),
            "videovector-1.2.3/pyproject.toml": (
                b'[build-system]\nrequires = ["setuptools==80.10.2", "wheel==0.47.0"]\n'
                b'build-backend = "setuptools.build_meta"\n'
                b'\n[project]\nname = "videovector"\nversion = "1.2.3"\n'
                b'requires-python = ">=3.9"\n'
            ),
            "videovector-1.2.3/videovector/__init__.py": (b"from ._version import __version__\n"),
            "videovector-1.2.3/videovector/_version.py": b'__version__ = "1.2.3"\n',
        }
        for name, payload in sdist_files.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))

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
        "package": {
            "name": "videovector",
            "version": "1.2.3",
            "requires_python": ">=3.9",
        },
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
        "package": {"name": "videovector", "version": "1.2.3"},
        "repository": "VectorMethods/videovector-python",
        "source_sha": "a" * 40,
        "tag": "videovector-v1.2.3",
        "tag_sha": "a" * 40,
        "source_date_epoch": 1_700_000_000,
        "release_body_sha256": "b" * 64,
        "registry_metadata_path": metadata_path.name,
        "registry_metadata_sha256": _sha256(metadata_path),
        "artifacts": descriptors,
        "image_digest": None,
        "tool_versions": {
            "python": "3.11.13",
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
    with zipfile.ZipFile(first) as archive:
        assert all(
            ((info.external_attr >> 16) & 0o777) == (0o755 if info.is_dir() else 0o644)
            for info in archive.infolist()
        )


def test_sdist_normalization_is_deterministic_and_canonical(tmp_path: Path) -> None:
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    entries = {
        "videovector-1.2.3/videovector/value.py": b"VALUE = 1\n",
        "videovector-1.2.3/PKG-INFO": b"Name: videovector\nVersion: 1.2.3\n",
    }
    for path, names in ((first, entries), (second, dict(reversed(entries.items())))):
        with tarfile.open(path, "w:gz") as archive:
            for name, payload in names.items():
                member = tarfile.TarInfo(name)
                member.mode = 0o777
                member.uid = 501
                member.gid = 20
                member.mtime = 99
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))

    release.normalize_sdist(first, 1_700_000_000)
    release.normalize_sdist(second, 1_700_000_000)

    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first, "r:gz") as archive:
        assert all(
            member.mode == (0o755 if member.isdir() else 0o644)
            and member.uid == 0
            and member.gid == 0
            and member.mtime == 1_700_000_000
            for member in archive
        )


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

    with pytest.raises(release.ReleaseArtifactError, match="immutable toolchain"):
        release.verify_bundle(bundle)


def test_bundle_verification_fails_closed_after_artifact_tampering(
    tmp_path: Path,
) -> None:
    bundle, _metadata = _fake_bundle(tmp_path)
    wheel = bundle / "dist/videovector-1.2.3-py3-none-any.whl"

    release.verify_bundle(bundle)
    wheel.write_bytes(b"tampered")
    with pytest.raises(release.ReleaseArtifactError, match="size mismatch|hash mismatch"):
        release.verify_bundle(bundle)


def test_wheel_verification_rejects_duplicate_paths_and_record_drift(
    tmp_path: Path,
) -> None:
    bundle, _metadata = _fake_bundle(tmp_path)
    wheel = bundle / "dist/videovector-1.2.3-py3-none-any.whl"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("videovector/__init__.py", b"duplicate")
    with pytest.raises(release.ReleaseArtifactError, match="duplicate path"):
        release._wheel_metadata(wheel)

    bundle, _metadata = _fake_bundle(tmp_path / "record")
    wheel = bundle / "dist/videovector-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "r") as source:
        files = {info.filename: source.read(info) for info in source.infolist()}
    files["videovector-1.2.3.dist-info/RECORD"] = files[
        "videovector-1.2.3.dist-info/RECORD"
    ].replace(b"sha256=", b"sha256=AAAA", 1)
    replacement = wheel.with_suffix(".replacement")
    with zipfile.ZipFile(replacement, "w") as destination:
        for name, payload in files.items():
            destination.writestr(name, payload)
    replacement.replace(wheel)
    with pytest.raises(release.ReleaseArtifactError, match="RECORD differs"):
        release._wheel_metadata(wheel)


def test_sdist_verification_rejects_links_and_project_metadata_drift(
    tmp_path: Path,
) -> None:
    linked = tmp_path / "linked.tar.gz"
    with tarfile.open(linked, "w:gz") as archive:
        link = tarfile.TarInfo("videovector-1.2.3/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    with pytest.raises(release.ReleaseArtifactError, match="not a regular file"):
        release._sdist_metadata(linked)

    bundle, _metadata = _fake_bundle(tmp_path / "metadata")
    sdist = bundle / "dist/videovector-1.2.3.tar.gz"
    replacement = sdist.with_suffix(".replacement")
    files: dict[str, bytes] = {}
    with tarfile.open(sdist, "r:gz") as source:
        for member in source.getmembers():
            if not member.isfile():
                continue
            extracted = source.extractfile(member)
            assert extracted is not None
            files[member.name] = extracted.read()
    files["videovector-1.2.3/pyproject.toml"] = files["videovector-1.2.3/pyproject.toml"].replace(
        b'version = "1.2.3"', b'version = "2.0.0"'
    )
    with tarfile.open(replacement, "w:gz") as destination:
        for name, payload in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            destination.addfile(member, io.BytesIO(payload))
    replacement.replace(sdist)
    with pytest.raises(release.ReleaseArtifactError, match="project metadata differs"):
        release._sdist_metadata(sdist)


def test_sdist_verification_rejects_build_backend_lifecycle_hooks(tmp_path: Path) -> None:
    bundle, _metadata = _fake_bundle(tmp_path)
    sdist = bundle / "dist/videovector-1.2.3.tar.gz"
    replacement = sdist.with_suffix(".replacement")
    files: dict[str, bytes] = {}
    with tarfile.open(sdist, "r:gz") as source:
        for member in source.getmembers():
            if not member.isfile():
                continue
            extracted = source.extractfile(member)
            assert extracted is not None
            files[member.name] = extracted.read()
    files["videovector-1.2.3/pyproject.toml"] = files["videovector-1.2.3/pyproject.toml"].replace(
        b'setuptools.build_meta"', b'malicious.backend"'
    )
    files["videovector-1.2.3/setup.py"] = b"raise SystemExit('must never execute')\n"
    with tarfile.open(replacement, "w:gz") as destination:
        for name, payload in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            destination.addfile(member, io.BytesIO(payload))
    replacement.replace(sdist)

    with pytest.raises(release.ReleaseArtifactError, match="project metadata differs"):
        release._sdist_metadata(sdist)


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


def test_bundle_verification_requires_closed_schema_epoch_and_size_bounds(
    tmp_path: Path,
) -> None:
    bundle, _metadata = _fake_bundle(tmp_path)
    manifest_path = bundle / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["unexpected"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(release.ReleaseArtifactError, match="keys differ"):
        release.verify_bundle(bundle)

    bundle, _metadata = _fake_bundle(tmp_path / "epoch")
    with pytest.raises(release.ReleaseArtifactError, match="commit timestamp"):
        release.verify_bundle(bundle, source_date_epoch=1_700_000_001)

    bundle, _metadata = _fake_bundle(tmp_path / "size")
    manifest_path = bundle / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["size"] = release.MAX_WHEEL_BYTES + 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(release.ReleaseArtifactError, match="invalid or duplicated"):
        release.verify_bundle(bundle)


def test_bundle_verification_rejects_duplicate_json_and_credential_paths(
    tmp_path: Path,
) -> None:
    bundle, _metadata = _fake_bundle(tmp_path)
    manifest_path = bundle / "release-manifest.json"
    raw = manifest_path.read_text(encoding="utf-8")
    raw = raw.replace(
        '"repository": "VectorMethods/videovector-python",',
        '"repository": "VectorMethods/videovector-python",\n'
        '  "repository": "VectorMethods/videovector-python",',
    )
    manifest_path.write_text(raw, encoding="utf-8")
    with pytest.raises(release.ReleaseArtifactError, match="duplicate JSON key"):
        release.verify_bundle(bundle)

    bundle, _metadata = _fake_bundle(tmp_path / "credential")
    wheel = bundle / "dist/videovector-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("videovector/service-account.json", b"{}")
    with pytest.raises(release.ReleaseArtifactError, match="credential-shaped"):
        release._wheel_metadata(wheel)


def test_partial_registry_state_resumes_with_only_missing_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, metadata = _fake_bundle(tmp_path)
    existing = metadata["artifacts"][0]
    payload = {
        "info": {
            "name": "videovector",
            "version": "1.2.3",
            "requires_python": ">=3.9",
        },
        "urls": [
            {
                **existing,
                "digests": {"sha256": existing["sha256"]},
                "url": f"https://registry.invalid/{existing['filename']}",
                "yanked": False,
            }
        ],
    }

    responses = iter(
        [
            _HttpResponse(
                json.dumps(payload).encode(),
                "https://registry.invalid/pypi/package/1.0/json",
            ),
            _HttpResponse(
                (bundle / "dist" / existing["filename"]).read_bytes(),
                f"https://registry.invalid/{existing['filename']}",
            ),
        ]
    )
    monkeypatch.setattr(release, "_open_registry_url", lambda *_args, **_kwargs: next(responses))
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
    assert [path.name for path in pending.iterdir()] == ["videovector-1.2.3.tar.gz"]


def _registry_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "info": {
            "name": metadata["package"]["name"],
            "version": metadata["package"]["version"],
            "requires_python": metadata["package"]["requires_python"],
        },
        "urls": [
            {
                **artifact,
                "digests": {"sha256": artifact["sha256"]},
                "url": f"https://registry.invalid/{artifact['filename']}",
                "yanked": False,
            }
            for artifact in metadata["artifacts"]
        ],
    }


def _registry_args(bundle: Path, *, base_url: str | None = "https://registry.invalid") -> Namespace:
    return Namespace(
        bundle=str(bundle),
        registry="pypi",
        base_url=base_url,
        timeout=1.0,
        write_missing=None,
    )


def test_registry_status_downloads_and_verifies_exact_distribution_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, metadata = _fake_bundle(tmp_path)
    payload = _registry_payload(metadata)
    artifacts = {
        artifact["filename"]: (bundle / "dist" / artifact["filename"]).read_bytes()
        for artifact in metadata["artifacts"]
    }
    responses = iter(
        [
            _HttpResponse(
                json.dumps(payload).encode(),
                "https://registry.invalid/pypi/package/1.0/json",
            ),
            *[
                _HttpResponse(
                    artifacts[artifact["filename"]],
                    artifact["url"],
                )
                for artifact in payload["urls"]
            ],
        ]
    )
    monkeypatch.setattr(
        release,
        "_open_registry_url",
        lambda *_args, **_kwargs: next(responses),
    )

    assert release.registry_status(_registry_args(bundle)) == 0


def test_registry_status_rejects_downloaded_bytes_that_differ_from_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, metadata = _fake_bundle(tmp_path)
    payload = _registry_payload(metadata)
    responses = iter(
        [
            _HttpResponse(
                json.dumps(payload).encode(),
                "https://registry.invalid/pypi/package/1.0/json",
            ),
            _HttpResponse(
                b"x" * int(metadata["artifacts"][0]["size"]),
                payload["urls"][0]["url"],
            ),
        ]
    )
    monkeypatch.setattr(
        release,
        "_open_registry_url",
        lambda *_args, **_kwargs: next(responses),
    )

    with pytest.raises(release.ReleaseArtifactError, match=r"artifact .* bytes differ"):
        release.registry_status(_registry_args(bundle))


@pytest.mark.parametrize("mutation", ["duplicate", "yanked", "untrusted"])
def test_registry_status_rejects_unsafe_artifact_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    bundle, metadata = _fake_bundle(tmp_path)
    payload = _registry_payload(metadata)
    if mutation == "duplicate":
        payload["urls"].append(dict(payload["urls"][0]))
    elif mutation == "yanked":
        payload["urls"][0]["yanked"] = True
    else:
        payload["urls"][0]["url"] = "https://attacker.invalid/package.whl"
    monkeypatch.setattr(
        release,
        "_open_registry_url",
        lambda *_args, **_kwargs: _HttpResponse(
            json.dumps(payload).encode(),
            "https://registry.invalid/pypi/package/1.0/json",
        ),
    )

    with pytest.raises(
        release.ReleaseArtifactError,
        match="duplicated|yanked|trusted HTTPS URL",
    ):
        release.registry_status(_registry_args(bundle))


def test_registry_status_fails_closed_when_distribution_cdn_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, metadata = _fake_bundle(tmp_path)
    payload = _registry_payload(metadata)
    responses: list[object] = [
        _HttpResponse(
            json.dumps(payload).encode(),
            "https://registry.invalid/pypi/package/1.0/json",
        ),
        urllib.error.URLError("cdn unavailable"),
    ]

    def open_url(*_args: object, **_kwargs: object) -> _HttpResponse:
        response = responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        assert isinstance(response, _HttpResponse)
        return response

    monkeypatch.setattr(release, "_open_registry_url", open_url)

    with pytest.raises(release.ReleaseArtifactError, match="cannot download"):
        release.registry_status(_registry_args(bundle))


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


def test_ci_uses_pinned_runtimes_with_stable_required_check_names() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "name: Python ${{ matrix.python-minor }}" in workflow
    for minor, version in (
        ("3.9", "3.9.23"),
        ("3.10", "3.10.18"),
        ("3.11", "3.11.13"),
        ("3.12", "3.12.11"),
    ):
        expected_entry = f'- python-minor: "{minor}"\n' f'            python-version: "{version}"'
        assert expected_entry in workflow


def test_release_jobs_checkout_the_guarded_source_sha() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("ref: refs/tags/${{ inputs.release_tag }}") == 1
    assert workflow.count("ref: ${{ needs.guard.outputs.source_sha }}") == 6
    assert re.search(
        r"expected_target_sha:\s+"
        r'description: "Exact commit SHA named by the immutable lightweight release tag"\s+'
        r"required: true\s+type: string",
        workflow,
    )
    assert "EXPECTED_TARGET_SHA: ${{ inputs.expected_target_sha }}" in workflow
    assert "OPERATION_NONCE: ${{ inputs.operation_nonce }}" in workflow
    assert "run-name: Release ${{ inputs.release_tag }} [${{ inputs.operation_nonce }}]" in workflow
    assert "retention-days: 90" in workflow
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
    _git(root, "tag", release_tag)
    (root / "release.txt").write_text("main advanced\n", encoding="utf-8")
    _git(root, "commit", "-am", "advance main")
    moving_main_sha = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "--detach", release_sha)

    output = tmp_path / "github-output"
    body_sha256 = "b" * 64
    nonce_payload = {
        "body_sha256": body_sha256,
        "repo": "videovector-python",
        "tag": release_tag,
        "tag_commit_sha": release_sha,
        "tag_object_sha": release_sha,
    }
    operation_nonce = hashlib.sha256(
        (
            json.dumps(
                nonce_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    environment = {
        **os.environ,
        "DRAFT_RELEASE_ID": "42",
        "EXPECTED_TARGET_SHA": release_sha,
        "GITHUB_ACTOR": "vectormethods-public-bot[bot]",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REF": f"refs/tags/{release_tag}",
        "GITHUB_REPOSITORY": "VectorMethods/videovector-python",
        "GITHUB_SHA": release_sha,
        "OPERATION_NONCE": operation_nonce,
        "RELEASE_BODY_SHA256": body_sha256,
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


def test_release_guard_rejects_well_formed_but_unbound_operation_nonce(
    tmp_path: Path,
) -> None:
    root, environment, _, _ = _release_guard_fixture(tmp_path)
    environment["OPERATION_NONCE"] = "f" * 64

    result = subprocess.run(
        ("bash", str(Path(__file__).parents[1] / "scripts/validate_release_request.sh")),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "does not bind the exact repository, tag, commit, and release body" in result.stderr


def test_release_guard_rejects_annotated_sdk_tag(tmp_path: Path) -> None:
    root, environment, release_sha, _ = _release_guard_fixture(tmp_path)
    tag = environment["RELEASE_TAG"]
    _git(root, "tag", "--delete", tag)
    _git(root, "tag", "-a", tag, release_sha, "-m", "annotated")

    result = subprocess.run(
        ("bash", str(Path(__file__).parents[1] / "scripts/validate_release_request.sh")),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "require a lightweight tag" in result.stderr


@pytest.mark.parametrize(
    "nonce",
    ["A" * 64, "a" * 63, "a" * 65, "not-a-digest"],
)
def test_release_guard_rejects_malformed_operation_nonce(
    tmp_path: Path,
    nonce: str,
) -> None:
    root, environment, _, _ = _release_guard_fixture(tmp_path)
    environment["OPERATION_NONCE"] = nonce

    result = subprocess.run(
        ("bash", str(Path(__file__).parents[1] / "scripts/validate_release_request.sh")),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "operation_nonce must be a lowercase SHA-256 digest" in result.stderr


@pytest.mark.parametrize(
    "version",
    [
        "01.2.3",
        "1.02.3",
        "1.2.03",
        "1.2.3rc1",
        "1.2.3-01",
        "1.2.3+build",
        "1.2",
    ],
)
def test_release_guard_rejects_noncanonical_semver(
    tmp_path: Path,
    version: str,
) -> None:
    root, environment, release_sha, _ = _release_guard_fixture(tmp_path)
    old_tag = environment["RELEASE_TAG"]
    new_tag = f"videovector-v{version}"
    _git(root, "tag", "--delete", old_tag)
    _git(root, "tag", new_tag, release_sha)
    environment["GITHUB_REF"] = f"refs/tags/{new_tag}"
    environment["RELEASE_TAG"] = new_tag

    result = subprocess.run(
        ("bash", str(Path(__file__).parents[1] / "scripts/validate_release_request.sh")),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "valid release version" in result.stderr


def test_release_installs_only_with_the_reviewed_uv_binary() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("run: timeout 90 bash scripts/install_reviewed_uv.sh") == 3
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
        for maintained_script in (
            "scripts/release_process.py",
            "scripts/release_draft_staging.py",
            "scripts/smoke_release_install.py",
        ):
            assert maintained_script in workflow
