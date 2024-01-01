#!/usr/bin/env python3
"""Build, attest, and verify one immutable Python release bundle.

The release bundle is intentionally separate from registry publication. A
successful build produces the wheel and sdist exactly once, normalizes archive
timestamps, and records every byte in ``release-manifest.json``. Publication
jobs consume that bundle and use ``registry-status`` to distinguish a missing
version from an exact replay or a conflicting pre-existing version.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from email.parser import BytesParser
from importlib import metadata as importlib_metadata
from pathlib import Path, PurePosixPath
from typing import IO, Any, Mapping, NoReturn, Sequence, cast

SCHEMA_VERSION = "1.1.0"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_REGISTRY_URLS = {
    "pypi": "https://pypi.org",
    "testpypi": "https://test.pypi.org",
}
DEFAULT_REPOSITORY = "VectorMethods/videovector-python"


class ReleaseArtifactError(RuntimeError):
    """Release bundle or registry state is unsafe."""


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    capture: bool = False,
) -> str:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def _git(root: Path, *arguments: str) -> str:
    return _run(("git", *arguments), cwd=root, capture=True)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_stable_json_bytes(value))


def _require_sha256(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ReleaseArtifactError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _fixed_zip_datetime(epoch: int) -> tuple[int, int, int, int, int, int]:
    # ZIP cannot represent dates before 1980. Release commits are newer, but
    # clamping makes the normalizer total for synthetic tests.
    import datetime

    moment = datetime.datetime.fromtimestamp(max(epoch, 315532800), datetime.timezone.utc)
    return (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second)


def normalize_wheel(path: Path, epoch: int) -> None:
    """Rewrite ZIP metadata without changing wheel file contents."""
    target = path.with_suffix(f"{path.suffix}.normalized")
    fixed_time = _fixed_zip_datetime(epoch)
    with (
        zipfile.ZipFile(path, "r") as source,
        zipfile.ZipFile(
            target,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as destination,
    ):
        for current in sorted(source.infolist(), key=lambda item: item.filename):
            payload = source.read(current.filename)
            normalized = zipfile.ZipInfo(current.filename, fixed_time)
            normalized.compress_type = current.compress_type
            normalized.create_system = 3
            normalized.external_attr = current.external_attr
            normalized.internal_attr = current.internal_attr
            normalized.flag_bits = current.flag_bits & 0x800
            destination.writestr(
                normalized,
                payload,
                compress_type=current.compress_type,
                compresslevel=9,
            )
    target.replace(path)


def normalize_sdist(path: Path, epoch: int) -> None:
    """Rewrite tar and gzip metadata to a commit-derived timestamp."""
    target = path.with_suffix(f"{path.suffix}.normalized")
    with tarfile.open(path, "r:gz") as source, target.open("wb") as raw_output:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_output,
            compresslevel=9,
            mtime=epoch,
        ) as gzip_output:
            with tarfile.open(
                fileobj=cast(IO[bytes], gzip_output),
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as destination:
                for current in sorted(source.getmembers(), key=lambda item: item.name):
                    normalized = copy.copy(current)
                    normalized.mtime = epoch
                    normalized.uid = 0
                    normalized.gid = 0
                    normalized.uname = ""
                    normalized.gname = ""
                    normalized.pax_headers = {}
                    payload = source.extractfile(current) if current.isfile() else None
                    destination.addfile(normalized, payload)
    target.replace(path)


def _read_project_metadata(root: Path) -> tuple[str, str]:
    try:
        toml_module = importlib.import_module("tomllib")
    except ModuleNotFoundError:  # pragma: no cover - release runner is Python 3.11+
        try:
            toml_module = importlib.import_module("tomli")
        except ModuleNotFoundError as error:
            raise ReleaseArtifactError(
                "Python <3.11 requires tomli to run the release builder"
            ) from error
    project = toml_module.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return str(project["name"]), str(project["version"])


def _wheel_metadata(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path, "r") as wheel:
        candidates = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        if len(candidates) != 1:
            raise ReleaseArtifactError("wheel must contain exactly one METADATA file")
        metadata = BytesParser().parsebytes(wheel.read(candidates[0]))
    return {
        "name": str(metadata["Name"]),
        "version": str(metadata["Version"]),
        "requires_python": str(metadata.get("Requires-Python") or ""),
    }


def _sdist_metadata(path: Path) -> dict[str, str]:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
                or member.issym()
                or member.islnk()
                or not (member.isdir() or member.isfile())
            ):
                raise ReleaseArtifactError(f"sdist contains an unsafe entry: {member.name}")
        metadata_members = [
            member
            for member in members
            if member.isfile()
            and len(PurePosixPath(member.name).parts) == 2
            and PurePosixPath(member.name).name == "PKG-INFO"
        ]
        if len(metadata_members) != 1:
            raise ReleaseArtifactError("sdist must contain exactly one top-level PKG-INFO")
        extracted = archive.extractfile(metadata_members[0])
        if extracted is None:
            raise ReleaseArtifactError("cannot read sdist PKG-INFO")
        metadata = BytesParser().parsebytes(extracted.read())
    return {
        "name": str(metadata["Name"]),
        "version": str(metadata["Version"]),
        "requires_python": str(metadata.get("Requires-Python") or ""),
    }


def _artifact_descriptor(path: Path) -> dict[str, Any]:
    if path.name.endswith(".whl"):
        package_type = "bdist_wheel"
    elif path.name.endswith(".tar.gz"):
        package_type = "sdist"
    else:
        raise ReleaseArtifactError(f"unexpected release artifact: {path.name}")
    return {
        "filename": path.name,
        "path": f"dist/{path.name}",
        "packagetype": package_type,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def _uv_version() -> str:
    executable = shutil.which("uv")
    if executable is None:
        return "unavailable"
    try:
        output = _run((executable, "--version"), cwd=Path.cwd(), capture=True)
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    match = re.fullmatch(r"uv (?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?: .*)?", output)
    return match.group("version") if match is not None else "unavailable"


def _tool_versions() -> dict[str, str]:
    versions = {"python": sys.version.split()[0]}
    for distribution in ("build", "setuptools", "twine", "wheel"):
        try:
            versions[distribution] = importlib_metadata.version(distribution)
        except importlib_metadata.PackageNotFoundError:
            versions[distribution] = "unavailable"
    versions["uv"] = _uv_version()
    return versions


def _copy_release_source(
    root: Path,
    destination: Path,
    source_sha: str,
    *,
    allow_dirty: bool,
) -> None:
    if allow_dirty:
        ignored = shutil.ignore_patterns(
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "*.egg-info",
            "build",
            "dist",
            "release-bundle",
        )
        shutil.copytree(root, destination, ignore=ignored)
        return

    archive_path = destination.parent / "source.tar"
    _run(
        ("git", "archive", "--format=tar", f"--output={archive_path}", source_sha),
        cwd=root,
    )
    destination.mkdir()
    with tarfile.open(archive_path, "r:") as archive:
        members = archive.getmembers()
        for member in members:
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
                or member.issym()
                or member.islnk()
                or not (member.isdir() or member.isfile())
            ):
                raise ReleaseArtifactError(f"git archive contains an unsafe entry: {member.name}")
        archive.extractall(destination, members=members)
    archive_path.unlink()


def _expected_registry_metadata(
    *,
    package_metadata: Mapping[str, str],
    artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "package": dict(package_metadata),
        "artifacts": sorted(
            (
                {
                    "filename": artifact["filename"],
                    "packagetype": artifact["packagetype"],
                    "sha256": artifact["sha256"],
                    "size": artifact["size"],
                }
                for artifact in artifacts
            ),
            key=lambda artifact: str(artifact["filename"]),
        ),
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseArtifactError(f"cannot read {path}: {error}") from error


def verify_bundle(
    bundle: Path,
    *,
    source_sha: str | None = None,
    tag_sha: str | None = None,
    release_body_sha256: str | None = None,
) -> dict[str, Any]:
    manifest_path = bundle / "release-manifest.json"
    manifest_value = _load_json(manifest_path)
    if not isinstance(manifest_value, dict):
        raise ReleaseArtifactError("release manifest must be a JSON object")
    manifest: dict[str, Any] = manifest_value
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseArtifactError("unsupported release manifest schema")
    manifest_source_sha = manifest.get("source_sha")
    if (
        not isinstance(manifest_source_sha, str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", manifest_source_sha) is None
        or manifest.get("tag_sha") != manifest_source_sha
        or not isinstance(manifest.get("tag"), str)
        or not manifest["tag"]
        or not isinstance(manifest.get("source_date_epoch"), int)
        or isinstance(manifest["source_date_epoch"], bool)
        or manifest["source_date_epoch"] <= 0
        or not isinstance(manifest.get("release_body_sha256"), str)
        or SHA256_PATTERN.fullmatch(manifest["release_body_sha256"]) is None
        or manifest.get("repository") != DEFAULT_REPOSITORY
        or manifest.get("image_digest") is not None
    ):
        raise ReleaseArtifactError("release provenance fields are invalid")
    tool_versions = manifest.get("tool_versions")
    required_tools = {"python", "build", "setuptools", "twine", "uv", "wheel"}
    if (
        not isinstance(tool_versions, Mapping)
        or not required_tools.issubset(tool_versions)
        or any(
            not isinstance(tool_versions[name], str)
            or not tool_versions[name]
            or tool_versions[name] == "unavailable"
            for name in required_tools
        )
    ):
        raise ReleaseArtifactError("release tool versions are incomplete")
    if source_sha is not None and manifest.get("source_sha") != source_sha:
        raise ReleaseArtifactError("release bundle source SHA does not match")
    if tag_sha is not None and manifest.get("tag_sha") != tag_sha:
        raise ReleaseArtifactError("release bundle tag SHA does not match")
    if release_body_sha256 is not None:
        expected_body_hash = _require_sha256(
            release_body_sha256,
            "release_body_sha256",
        )
        if manifest.get("release_body_sha256") != expected_body_hash:
            raise ReleaseArtifactError("release body hash does not match")

    bundle_root = bundle.resolve()
    metadata_relative_path = manifest.get("registry_metadata_path")
    if metadata_relative_path != "registry-metadata.json":
        raise ReleaseArtifactError("registry metadata path is not canonical")
    metadata_path = (bundle_root / metadata_relative_path).resolve()
    if metadata_path.parent != bundle_root:
        raise ReleaseArtifactError("registry metadata path escapes the bundle")
    if not metadata_path.is_file():
        raise ReleaseArtifactError("registry metadata file is missing")

    artifact_paths: set[str] = set()
    package_types: set[str] = set()
    descriptors = manifest.get("artifacts")
    if not isinstance(descriptors, list):
        raise ReleaseArtifactError("release artifacts must be a list")
    for descriptor in descriptors:
        if not isinstance(descriptor, Mapping):
            raise ReleaseArtifactError("release artifact descriptor is malformed")
        filename = descriptor.get("filename")
        relative_path = descriptor.get("path")
        package_type = descriptor.get("packagetype")
        digest = descriptor.get("sha256")
        size = descriptor.get("size")
        if (
            not isinstance(filename, str)
            or not filename
            or "\\" in filename
            or Path(filename).name != filename
            or not isinstance(relative_path, str)
            or relative_path != f"dist/{filename}"
            or relative_path in artifact_paths
            or package_type not in {"bdist_wheel", "sdist"}
            or package_type in package_types
            or not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
        ):
            raise ReleaseArtifactError("release artifact path is invalid or duplicated")
        artifact_paths.add(relative_path)
        package_types.add(package_type)
        artifact_path = (bundle_root / relative_path).resolve()
        if artifact_path.parent != (bundle_root / "dist").resolve():
            raise ReleaseArtifactError("release artifact path escapes the bundle")
        if not artifact_path.is_file():
            raise ReleaseArtifactError(f"release artifact is missing: {relative_path}")
        if artifact_path.stat().st_size != size:
            raise ReleaseArtifactError(f"release artifact size mismatch: {relative_path}")
        if sha256_file(artifact_path) != digest:
            raise ReleaseArtifactError(f"release artifact hash mismatch: {relative_path}")
    if len(artifact_paths) != 2 or package_types != {"bdist_wheel", "sdist"}:
        raise ReleaseArtifactError("release bundle must contain exactly one wheel and one sdist")

    wheel_descriptor = next(
        descriptor for descriptor in descriptors if descriptor["packagetype"] == "bdist_wheel"
    )
    sdist_descriptor = next(
        descriptor for descriptor in descriptors if descriptor["packagetype"] == "sdist"
    )
    wheel_metadata = _wheel_metadata(bundle_root / wheel_descriptor["path"])
    if _sdist_metadata(bundle_root / sdist_descriptor["path"]) != wheel_metadata:
        raise ReleaseArtifactError("sdist metadata differs from wheel metadata")
    package = manifest.get("package")
    if package != {
        "name": wheel_metadata["name"],
        "version": wheel_metadata["version"],
    }:
        raise ReleaseArtifactError("release manifest package differs from wheel metadata")

    expected_metadata = _expected_registry_metadata(
        package_metadata=wheel_metadata,
        artifacts=descriptors,
    )
    actual_metadata = _load_json(metadata_path)
    if actual_metadata != expected_metadata:
        raise ReleaseArtifactError("registry metadata differs from release artifacts")
    expected_metadata_hash = _sha256_bytes(_stable_json_bytes(expected_metadata))
    if expected_metadata_hash != manifest.get("registry_metadata_sha256"):
        raise ReleaseArtifactError("registry metadata hash does not match")
    return manifest


def build_bundle(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    bundle = Path(args.output).resolve()
    release_body_sha256 = _require_sha256(
        args.release_body_sha256,
        "release_body_sha256",
    )
    source_sha = args.source_sha or _git(root, "rev-parse", "HEAD")
    tag_sha = args.tag_sha or _git(root, "rev-list", "-n", "1", args.tag)
    if source_sha != tag_sha:
        raise ReleaseArtifactError("release tag SHA must equal source SHA")
    if not args.allow_dirty and _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ReleaseArtifactError("release source must be clean")
    source_date_epoch = int(_git(root, "show", "-s", "--format=%ct", source_sha))

    if bundle.exists():
        verify_bundle(
            bundle,
            source_sha=source_sha,
            tag_sha=tag_sha,
            release_body_sha256=release_body_sha256,
        )
        print(f"[release] Reusing verified bundle at {bundle}")
        return

    package_name, package_version = _read_project_metadata(root)
    if args.version is not None and package_version != args.version:
        raise ReleaseArtifactError(
            f"project version {package_version} does not match {args.version}"
        )

    bundle.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{bundle.name}.", dir=str(bundle.parent)))
    try:
        source = staging / "source"
        _copy_release_source(
            root,
            source,
            source_sha,
            allow_dirty=bool(args.allow_dirty),
        )
        dist = staging / "dist"
        dist.mkdir()
        build_environment = dict(os.environ)
        build_environment.update(
            {
                "LC_ALL": "C.UTF-8",
                "PYTHONHASHSEED": "0",
                "SOURCE_DATE_EPOCH": str(source_date_epoch),
                "TZ": "UTC",
            }
        )
        _run(
            (
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(dist),
            ),
            cwd=source,
            env=build_environment,
        )

        wheels = sorted(dist.glob("*.whl"))
        sdists = sorted(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ReleaseArtifactError("build must produce exactly one wheel and one sdist")
        normalize_wheel(wheels[0], source_date_epoch)
        normalize_sdist(sdists[0], source_date_epoch)

        wheel_metadata = _wheel_metadata(wheels[0])
        if wheel_metadata["name"] != package_name or wheel_metadata["version"] != package_version:
            raise ReleaseArtifactError("built wheel metadata does not match project metadata")
        artifacts = [_artifact_descriptor(path) for path in sorted((*wheels, *sdists))]
        registry_metadata = _expected_registry_metadata(
            package_metadata=wheel_metadata,
            artifacts=artifacts,
        )
        metadata_path = staging / "registry-metadata.json"
        _write_json(metadata_path, registry_metadata)
        tool_versions = _tool_versions()
        unavailable_tools = sorted(
            name for name, version in tool_versions.items() if version == "unavailable"
        )
        if unavailable_tools:
            raise ReleaseArtifactError(
                "release tool versions are unavailable: " + ", ".join(unavailable_tools)
            )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "package": {"name": package_name, "version": package_version},
            "repository": DEFAULT_REPOSITORY,
            "source_sha": source_sha,
            "tag": args.tag,
            "tag_sha": tag_sha,
            "source_date_epoch": source_date_epoch,
            "release_body_sha256": release_body_sha256,
            "artifacts": artifacts,
            "image_digest": None,
            "registry_metadata_path": "registry-metadata.json",
            "registry_metadata_sha256": sha256_file(metadata_path),
            "tool_versions": tool_versions,
        }
        _write_json(staging / "release-manifest.json", manifest)
        shutil.rmtree(source)
        verify_bundle(
            staging,
            source_sha=source_sha,
            tag_sha=tag_sha,
            release_body_sha256=release_body_sha256,
        )
        staging.replace(bundle)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(f"[release] Built immutable bundle at {bundle}")


def _registry_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    info = payload.get("info")
    urls = payload.get("urls")
    if not isinstance(info, Mapping) or not isinstance(urls, list):
        raise ReleaseArtifactError("registry returned malformed project metadata")
    artifacts = []
    for entry in urls:
        if not isinstance(entry, Mapping):
            raise ReleaseArtifactError("registry returned malformed artifact metadata")
        digests = entry.get("digests")
        if not isinstance(digests, Mapping):
            raise ReleaseArtifactError("registry artifact has no digest metadata")
        artifacts.append(
            {
                "filename": entry.get("filename"),
                "packagetype": entry.get("packagetype"),
                "sha256": digests.get("sha256"),
                "size": entry.get("size"),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "package": {
            "name": info.get("name"),
            "version": info.get("version"),
            "requires_python": info.get("requires_python") or "",
        },
        "artifacts": sorted(artifacts, key=lambda artifact: str(artifact["filename"])),
    }


def _write_missing_artifacts(
    bundle: Path,
    manifest: Mapping[str, Any],
    filenames: Sequence[str],
    output: str | None,
) -> None:
    if output is None:
        return
    destination = Path(output).resolve()
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    descriptors = {
        str(descriptor["filename"]): descriptor for descriptor in manifest.get("artifacts", [])
    }
    for filename in filenames:
        descriptor = descriptors.get(filename)
        if descriptor is None:
            raise ReleaseArtifactError(f"manifest has no artifact named {filename}")
        shutil.copy2(bundle / str(descriptor["path"]), destination / filename)


def registry_status(args: argparse.Namespace) -> int:
    bundle = Path(args.bundle).resolve()
    manifest = verify_bundle(bundle)
    expected = _load_json(bundle / manifest["registry_metadata_path"])
    base_url = (args.base_url or DEFAULT_REGISTRY_URLS[args.registry]).rstrip("/")
    package_name = manifest["package"]["name"]
    version = manifest["package"]["version"]
    url = f"{base_url}/pypi/{package_name}/{version}/json"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "videovector-release-verifier/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            _write_missing_artifacts(
                bundle,
                manifest,
                [str(artifact["filename"]) for artifact in expected["artifacts"]],
                args.write_missing,
            )
            print("missing")
            return 3
        raise ReleaseArtifactError(f"{args.registry} returned HTTP {error.code}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseArtifactError(f"cannot query {args.registry}: {error}") from error

    actual = _registry_projection(payload)
    if actual["package"] != expected["package"]:
        raise ReleaseArtifactError(f"{args.registry} version exists but package metadata differs")
    expected_by_name = {str(artifact["filename"]): artifact for artifact in expected["artifacts"]}
    actual_by_name = {str(artifact["filename"]): artifact for artifact in actual["artifacts"]}
    unexpected = sorted(set(actual_by_name) - set(expected_by_name))
    if unexpected:
        raise ReleaseArtifactError(
            f"{args.registry} contains unexpected artifacts: {', '.join(unexpected)}"
        )
    conflicts = sorted(
        filename
        for filename, artifact in actual_by_name.items()
        if artifact != expected_by_name[filename]
    )
    if conflicts:
        raise ReleaseArtifactError(
            f"{args.registry} artifact bytes or metadata differ: {', '.join(conflicts)}"
        )
    missing = sorted(set(expected_by_name) - set(actual_by_name))
    if missing:
        _write_missing_artifacts(bundle, manifest, missing, args.write_missing)
        print("partial")
        return 4
    if _sha256_bytes(_stable_json_bytes(actual)) != manifest["registry_metadata_sha256"]:
        raise ReleaseArtifactError(f"{args.registry} metadata hash differs")
    print("exact")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    build = subcommands.add_parser("build", help="build or reuse one release bundle")
    build.add_argument("--root", default=".")
    build.add_argument("--output", required=True)
    build.add_argument("--tag", required=True)
    build.add_argument("--tag-sha")
    build.add_argument("--source-sha")
    build.add_argument("--version")
    build.add_argument("--release-body-sha256", required=True)
    build.add_argument("--allow-dirty", action="store_true")

    verify = subcommands.add_parser("verify-bundle", help="verify bundle hashes")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--source-sha")
    verify.add_argument("--tag-sha")
    verify.add_argument("--release-body-sha256")

    registry = subcommands.add_parser(
        "registry-status",
        help="return exact, missing (exit 3), or fail on conflict",
    )
    registry.add_argument("--bundle", required=True)
    registry.add_argument("--registry", choices=sorted(DEFAULT_REGISTRY_URLS), required=True)
    registry.add_argument("--base-url")
    registry.add_argument("--timeout", type=float, default=30.0)
    registry.add_argument("--write-missing")
    return parser


def _fail(error: BaseException) -> NoReturn:
    print(f"[release] {error}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "build":
            build_bundle(args)
            return 0
        if args.command == "verify-bundle":
            verify_bundle(
                Path(args.bundle).resolve(),
                source_sha=args.source_sha,
                tag_sha=args.tag_sha,
                release_body_sha256=args.release_body_sha256,
            )
            print("verified")
            return 0
        if args.command == "registry-status":
            return registry_status(args)
        raise AssertionError(f"unsupported command: {args.command}")
    except ReleaseArtifactError as error:
        _fail(error)


if __name__ == "__main__":
    raise SystemExit(main())
